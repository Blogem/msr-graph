package sandbox

import (
	"context"
	"time"
)

// SandboxLabel is the label KEY applied to every sandbox container (value
// "1"). It lets a fresh server process find and force-remove every
// container left behind by a previous process on startup (design D9),
// regardless of how that previous process died (crash, OOM, kill, host
// reboot).
const SandboxLabel = "msr.sandbox"

// ContainerSpec fixes every isolation/resource control the runtime applies
// at create time. Fixed policy controls that are always applied
// unconditionally by the runtime -- network none, read-only rootfs, noexec
// tmpfs, non-root UID 10001, drop-all-caps, no-new-privileges, AutoRemove --
// are NOT fields here; they are not configurable per spec because the
// threat they address (exfiltration, image tampering, privilege escalation,
// orphaned auto-removal) applies to every sandbox unconditionally (design
// D4).
type ContainerSpec struct {
	// Image is the image reference to run (e.g. "msr-sandbox-base:latest").
	Image string

	// DataHostDir is the HOST path bind-mounted read-only at /data. It must
	// be a path the Docker daemon can resolve, not a path inside the
	// caller's own container (design D5 -- the classic sibling-mount
	// gotcha): mounting the value store read-only prevents any script
	// write to the data.
	DataHostDir string

	// CPUs is the --cpus limit, bounding CPU exhaustion of the host by a
	// runaway or malicious script.
	CPUs float64

	// MemoryBytes is the --memory limit (swap disabled), bounding memory
	// exhaustion / OOM of the host.
	MemoryBytes int64

	// PidsLimit is the --pids-limit, preventing fork bombs.
	PidsLimit int64

	// TmpfsSize is the /tmp tmpfs size in bytes. /tmp is mounted noexec so
	// a script has scratch space to write to without a persistent or
	// executable filesystem.
	TmpfsSize int64

	// IdleTTL is the bounded idle sleep TTL for the container's PID 1: it
	// idles on a bounded no-op instead of running forever, so an orphaned
	// container that is never claimed (e.g. its server process crashed and
	// never restarted to sweep it) self-reaps via AutoRemove when the TTL
	// elapses -- the backstop half of orphan reaping (design D9). It MUST
	// be set far larger than the per-run wall-clock timeout so it never
	// races a legitimate run.
	IdleTTL time.Duration

	// Labels are applied to the created container. MUST include
	// SandboxLabel: "1" so the container is discoverable by the startup
	// sweep (Reap) and greppable as a sandbox by operators.
	Labels map[string]string
}

// ExecResult captures the verbatim output of one script execution: stdout
// and stderr are returned unparsed and un-interpreted, and ExitCode is the
// process exit code. A non-zero ExitCode is a normal result, not a Go
// error -- error is reserved for infrastructure/daemon failures (design
// D6).
type ExecResult struct {
	Stdout   []byte
	Stderr   []byte
	ExitCode int
}

// Runtime is the injected seam over the container runtime. The pool
// depends only on this interface and contains no Docker types (design D2),
// so its lifecycle, timeout, and concurrency logic can be unit-tested
// against a fake implementation with no Docker daemon present. Production
// code implements Runtime against the Docker socket.
type Runtime interface {
	// Create creates and starts a warm, idle container from spec and
	// returns its id. The container applies every fixed and configured
	// isolation control from spec unconditionally and idles on a bounded
	// no-op (spec.IdleTTL) as PID 1 until Exec is called or the TTL
	// elapses.
	Create(ctx context.Context, spec ContainerSpec) (id string, err error)

	// Exec runs exactly one script inside the container identified by id:
	// the script bytes are fed to `python -` on stdin, and stdout, stderr,
	// and the exit code are captured and returned verbatim. Exec is called
	// at most once per container id -- containers are single-use (design
	// D1).
	Exec(ctx context.Context, id string, script []byte) (ExecResult, error)

	// Remove force-removes the container identified by id, killing any
	// live process inside it. It is the sole teardown path: used after
	// every run (success, failure, or timeout) so no state or artifact
	// ever survives from one run to the next (design D1, D7).
	Remove(ctx context.Context, id string) error

	// Reap force-removes every container carrying SandboxLabel, regardless
	// of which process created them. It is called once at pool startup,
	// before warming the pool, so a restarted server sweeps any orphans
	// left by a previous, non-gracefully-stopped process before it begins
	// serving (design D9).
	Reap(ctx context.Context) error
}
