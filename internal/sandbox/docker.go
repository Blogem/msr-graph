package sandbox

import (
	"bytes"
	"context"
	"fmt"
	"log"
	"time"

	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/filters"
	"github.com/docker/docker/api/types/mount"
	"github.com/docker/docker/client"
	"github.com/docker/docker/pkg/stdcopy"
	"github.com/google/uuid"
)

// dockerSocketHost is the mounted Unix socket the server talks to the
// daemon over. The server's own image is distroless-static (no shell, no
// docker CLI), so dockerRuntime dials this socket directly via the Docker
// Go SDK rather than shelling out (design D3).
const dockerSocketHost = "unix:///var/run/docker.sock"

// sandboxUser is the fixed non-root UID:GID every sandbox container runs
// as, matching the sandbox base image's UID 10001 (design D4 -- prevents
// privilege escalation inside the container).
const sandboxUser = "10001:10001"

// sandboxNamePrefix names every sandbox container so orphans are greppable
// by an operator and container names never collide across concurrent
// creates (task 3.3).
const sandboxNamePrefix = "msr-sandbox-"

// dockerRuntime implements Runtime against a real Docker daemon reached
// over the mounted Unix socket. It is the production implementation
// injected behind the Runtime interface (design D2); the pool itself
// contains no Docker types.
type dockerRuntime struct {
	cli *client.Client
}

// NewDockerRuntime dials the Docker daemon over the mounted socket
// (unix:///var/run/docker.sock) using the official Docker Go SDK with API
// version negotiation, and returns a Runtime backed by it.
func NewDockerRuntime() (Runtime, error) {
	cli, err := client.NewClientWithOpts(
		client.WithHost(dockerSocketHost),
		client.WithAPIVersionNegotiation(),
	)
	if err != nil {
		return nil, fmt.Errorf("sandbox: create docker client: %w", err)
	}
	return &dockerRuntime{cli: cli}, nil
}

// Create creates and starts a warm, idle sandbox container applying every
// fixed and configured isolation control from spec unconditionally (design
// D4): no network, read-only root FS with a noexec tmpfs /tmp, non-root
// user, the data directory bind-mounted read-only, CPU/memory/pids limits,
// dropped capabilities, no-new-privileges, and AutoRemove as the D9
// backstop. PID 1 idles on a bounded `sleep <IdleTTL>` rather than
// `sleep infinity`, so an abandoned orphan self-reaps when the TTL elapses.
func (r *dockerRuntime) Create(ctx context.Context, spec ContainerSpec) (string, error) {
	idleSeconds := int(spec.IdleTTL.Seconds())

	containerCfg := &container.Config{
		Image:  spec.Image,
		Cmd:    []string{"sleep", fmt.Sprintf("%d", idleSeconds)},
		User:   sandboxUser,
		Labels: spec.Labels,
	}

	pidsLimit := spec.PidsLimit
	hostCfg := &container.HostConfig{
		NetworkMode:    "none",
		ReadonlyRootfs: true,
		Tmpfs: map[string]string{
			"/tmp": fmt.Sprintf("rw,noexec,nosuid,size=%d", spec.TmpfsSize),
		},
		Mounts: []mount.Mount{
			{
				Type:     mount.TypeBind,
				Source:   spec.DataHostDir,
				Target:   "/data",
				ReadOnly: true,
			},
		},
		Resources: container.Resources{
			NanoCPUs:   int64(spec.CPUs * 1e9),
			Memory:     spec.MemoryBytes,
			MemorySwap: spec.MemoryBytes,
			PidsLimit:  &pidsLimit,
		},
		CapDrop:     []string{"ALL"},
		SecurityOpt: []string{"no-new-privileges:true"},
		AutoRemove:  true,
	}

	name := sandboxNamePrefix + uuid.NewString()

	created, err := r.cli.ContainerCreate(ctx, containerCfg, hostCfg, nil, nil, name)
	if err != nil {
		return "", fmt.Errorf("sandbox: create container: %w", err)
	}

	if err := r.cli.ContainerStart(ctx, created.ID, container.StartOptions{}); err != nil {
		// AutoRemove only fires on exit, and a container that never started
		// never exits, so without an explicit removal here it would escape
		// both the D9 backstops and accumulate across replenish retries. Use
		// a detached context so removal still runs even if ctx is already
		// past its deadline or cancelled.
		if rmErr := r.cli.ContainerRemove(context.Background(), created.ID, container.RemoveOptions{Force: true}); rmErr != nil {
			log.Printf("sandbox: failed to remove container %s after failed start: %v", created.ID, rmErr)
		}
		return "", fmt.Errorf("sandbox: start container %s: %w", created.ID, err)
	}

	return created.ID, nil
}

// Exec runs exactly one script inside the container identified by id: the
// script bytes are fed to `python -` on stdin, and stdout, stderr, and the
// exit code are captured and returned verbatim (design D6). The hijacked,
// length-framed multiplexed exec stream is demultiplexed via stdcopy rather
// than hand-parsed, since re-implementing that framing is exactly the kind
// of subtle parsing bug to avoid in a security-sensitive path (design D3).
func (r *dockerRuntime) Exec(ctx context.Context, id string, script []byte) (ExecResult, error) {
	execCfg := container.ExecOptions{
		Cmd:          []string{"python", "-"},
		AttachStdin:  true,
		AttachStdout: true,
		AttachStderr: true,
		Tty:          false,
	}

	execCreated, err := r.cli.ContainerExecCreate(ctx, id, execCfg)
	if err != nil {
		return ExecResult{}, fmt.Errorf("sandbox: exec create in container %s: %w", id, err)
	}

	attachResp, err := r.cli.ContainerExecAttach(ctx, execCreated.ID, container.ExecAttachOptions{Tty: false})
	if err != nil {
		return ExecResult{}, fmt.Errorf("sandbox: exec attach in container %s: %w", id, err)
	}
	defer attachResp.Close()

	writeErrCh := make(chan error, 1)
	go func() {
		_, werr := attachResp.Conn.Write(script)
		attachResp.CloseWrite()
		writeErrCh <- werr
	}()

	var stdout, stderr bytes.Buffer
	copyDoneCh := make(chan error, 1)
	go func() {
		_, cerr := stdcopy.StdCopy(&stdout, &stderr, attachResp.Reader)
		copyDoneCh <- cerr
	}()

	select {
	case <-ctx.Done():
		return ExecResult{}, fmt.Errorf("sandbox: exec in container %s: %w", id, ctx.Err())
	case cerr := <-copyDoneCh:
		if cerr != nil {
			return ExecResult{}, fmt.Errorf("sandbox: demultiplex exec stream in container %s: %w", id, cerr)
		}
	}

	if werr := <-writeErrCh; werr != nil {
		return ExecResult{}, fmt.Errorf("sandbox: write script to container %s stdin: %w", id, werr)
	}

	// A single inspect immediately after StdCopy returns is not reliable:
	// under a loaded daemon it can still report Running: true / ExitCode: 0
	// for a script that has not actually finished, silently returning exit 0
	// for a script that actually failed. Poll until the daemon reports the
	// exec has stopped running, bounded by ctx, before trusting ExitCode.
	var exitCode int
	for {
		inspect, err := r.cli.ContainerExecInspect(ctx, execCreated.ID)
		if err != nil {
			return ExecResult{}, fmt.Errorf("sandbox: exec inspect in container %s: %w", id, err)
		}
		if !inspect.Running {
			exitCode = inspect.ExitCode
			break
		}
		select {
		case <-ctx.Done():
			return ExecResult{}, fmt.Errorf("sandbox: exec in container %s: %w", id, ctx.Err())
		case <-time.After(10 * time.Millisecond):
		}
	}

	return ExecResult{
		Stdout:   stdout.Bytes(),
		Stderr:   stderr.Bytes(),
		ExitCode: exitCode,
	}, nil
}

// Remove force-removes the container identified by id, killing any live
// process inside it. It is the sole teardown path (design D1, D7).
func (r *dockerRuntime) Remove(ctx context.Context, id string) error {
	if err := r.cli.ContainerRemove(ctx, id, container.RemoveOptions{Force: true}); err != nil {
		return fmt.Errorf("sandbox: remove container %s: %w", id, err)
	}
	return nil
}

// Reap force-removes every container carrying SandboxLabel, regardless of
// which process created them. It is called once at pool startup, before
// warming the pool, so a restarted server sweeps any orphans left by a
// previous, non-gracefully-stopped process (design D9). Errors are
// accumulated across containers rather than stopping at the first failure.
func (r *dockerRuntime) Reap(ctx context.Context) error {
	listFilters := filters.NewArgs(filters.Arg("label", SandboxLabel))
	containers, err := r.cli.ContainerList(ctx, container.ListOptions{
		All:     true,
		Filters: listFilters,
	})
	if err != nil {
		return fmt.Errorf("sandbox: list labeled containers: %w", err)
	}

	var errs []error
	for _, c := range containers {
		if rmErr := r.cli.ContainerRemove(ctx, c.ID, container.RemoveOptions{Force: true}); rmErr != nil {
			errs = append(errs, fmt.Errorf("sandbox: reap container %s: %w", c.ID, rmErr))
		}
	}

	if len(errs) > 0 {
		combined := errs[0].Error()
		for _, e := range errs[1:] {
			combined += "; " + e.Error()
		}
		return fmt.Errorf("sandbox: reap encountered %d error(s): %s", len(errs), combined)
	}

	return nil
}
