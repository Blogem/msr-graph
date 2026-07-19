package sandbox_test

// Integration test (task 6.8) exercising the real Docker-backed Runtime
// and Pool against the isolation properties pinned by
// openspec/changes/sandbox-exec-pool/specs/sandbox-execution/spec.md.
//
// Gated exactly like internal/graph/testhelper_test.go's requireGraphDB
// (design D6's reachability/skip/fatal pattern, called out for reuse here
// in design.md's Risks/Trade-offs: "gated like the existing GraphDB
// integration tests"), using env var SANDBOX_DOCKER_REQUIRED in place of
// GRAPHDB_REQUIRED:
//
//   - Docker unreachable, SANDBOX_DOCKER_REQUIRED unset -> t.Skip (clear reason)
//   - Docker unreachable, SANDBOX_DOCKER_REQUIRED set   -> t.Fatal
//   - Docker responds but the environment is broken     -> t.Fatal in BOTH modes
//
// Requires the built msr-sandbox-base:latest image (`make up`) and a real
// Docker daemon reachable at the default socket.

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/blogem/msr-graph/internal/sandbox"
	"github.com/blogem/msr-graph/internal/store"
)

const (
	// integrationImage matches the tag `make up` builds and the pool's
	// LoadConfig default (see config.go, defaultImage).
	integrationImage = "msr-sandbox-base:latest"

	reachabilityTimeout   = 5 * time.Second
	integrationRunTimeout = 10 * time.Second
)

// --- gate (task 6.9, helper portion) ---

// sandboxDockerRequired reports whether SANDBOX_DOCKER_REQUIRED is set to
// any non-empty value -- the trigger for switching skip -> fatal, mirroring
// GRAPHDB_REQUIRED in internal/graph/testhelper_test.go.
func sandboxDockerRequired() bool {
	return os.Getenv("SANDBOX_DOCKER_REQUIRED") != ""
}

// isDockerUnreachable reports whether err represents a Docker daemon that
// is simply not there (missing socket, connection refused, or a timeout)
// -- the ONLY conditions this test skips for. Any other error (permission
// denied, malformed response, ...) is a broken environment and must fail
// hard in both modes.
func isDockerUnreachable(err error) bool {
	if err == nil {
		return false
	}
	if errors.Is(err, syscall.ECONNREFUSED) || errors.Is(err, syscall.ENOENT) || os.IsNotExist(err) {
		return true
	}
	var netErr net.Error
	if errors.As(err, &netErr) && netErr.Timeout() {
		return true
	}
	return false
}

// requireDocker implements the reachability/skip/fatal guard and returns a
// ready-to-use sandbox.Runtime backed by the real Docker daemon.
// Reachability is checked by constructing the runtime via NewDockerRuntime
// and then calling Reap -- a real list-and-remove-by-label round trip to
// the daemon, exactly the probe New() itself performs on the startup path.
func requireDocker(t *testing.T) sandbox.Runtime {
	t.Helper()

	rt, err := sandbox.NewDockerRuntime()
	if err != nil {
		reason := fmt.Sprintf(
			"Docker runtime unavailable: %v -- start Docker / the compose stack (`make up`) or set SANDBOX_DOCKER_REQUIRED",
			err,
		)
		if sandboxDockerRequired() {
			t.Fatalf("SANDBOX_DOCKER_REQUIRED is set but %s", reason)
		}
		t.Skip(reason)
		return nil
	}

	ctx, cancel := context.WithTimeout(context.Background(), reachabilityTimeout)
	defer cancel()

	if err := rt.Reap(ctx); err != nil {
		if isDockerUnreachable(err) {
			reason := fmt.Sprintf(
				"Docker daemon unreachable: %v -- start Docker (`make up`) or set SANDBOX_DOCKER_REQUIRED",
				err,
			)
			if sandboxDockerRequired() {
				t.Fatalf("SANDBOX_DOCKER_REQUIRED is set but %s", reason)
			}
			t.Skip(reason)
			return nil
		}
		t.Fatalf("requireDocker: broken Docker environment reaching the daemon: %v -- this is a broken environment, not an absent one", err)
		return nil
	}

	return rt
}

// --- fixtures ---

// seedDataDir creates a temp directory containing a minimal msr.db (the
// measurement_value schema from internal/store, with one seeded row) and
// returns the directory path to use as ContainerSpec/Config.DataHostDir.
// The test process runs directly on the host (not inside a sibling
// "server" container), so t.TempDir() is already a host-resolvable path --
// the docker-socket sibling-mount gotcha (design D5) does not apply here.
func seedDataDir(t *testing.T) string {
	t.Helper()

	dir := t.TempDir()
	dbPath := filepath.Join(dir, "msr.db")

	db, err := store.Open(dbPath)
	if err != nil {
		t.Fatalf("store.Open(%s): %v", dbPath, err)
	}
	defer db.Close()

	if err := store.Init(context.Background(), db); err != nil {
		t.Fatalf("store.Init: %v", err)
	}

	if _, err := db.Exec(
		`INSERT INTO measurement_value (locator, salt, property, source) VALUES (?, ?, ?, ?)`,
		"nist-srd27/density#BeF2-LiF|66.0-34.0", "BeF2-LiF|66.0-34.0", "density", "nist",
	); err != nil {
		t.Fatalf("seeding measurement_value: %v", err)
	}

	return dir
}

func newIntegrationConfig(dataHostDir string) sandbox.Config {
	image := os.Getenv("MSR_SANDBOX_IMAGE")
	if image == "" {
		image = integrationImage
	}
	return sandbox.Config{
		PoolSize:    1,
		CPUs:        1,
		MemoryBytes: 256 << 20,
		PidsLimit:   128,
		TmpfsSize:   64 << 20,
		Timeout:     integrationRunTimeout,
		IdleTTL:     time.Hour,
		Image:       image,
		DataHostDir: dataHostDir,
	}
}

// --- docker CLI introspection (teardown / orphan-reaping assertions) ---
//
// The Runtime interface (Create/Exec/Remove/Reap) deliberately exposes no
// "list" or "inspect" operation to the pool, so these two assertions shell
// out to the docker CLI, which any host running `make up` already has.
// If it is unexpectedly absent, the affected subtests skip individually
// rather than failing the whole gated test.

func dockerCLIAvailable() bool {
	_, err := exec.LookPath("docker")
	return err == nil
}

func dockerContainerIDsWithLabel(t *testing.T, label string) []string {
	t.Helper()
	out, err := exec.Command("docker", "ps", "-aq", "--filter", "label="+label).Output()
	if err != nil {
		t.Fatalf("docker ps --filter label=%s: %v", label, err)
	}
	var ids []string
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		if line != "" {
			ids = append(ids, line)
		}
	}
	return ids
}

func dockerContainerExists(t *testing.T, id string) bool {
	t.Helper()
	return exec.Command("docker", "inspect", id).Run() == nil
}

// --- scripts ---
//
// Each script asserts one isolation PROPERTY (spec.md), not a numeric
// resource limit: read succeeds, writes fail, network fails, imports
// still work under noexec /tmp.

const readScript = `
import sqlite3, json
conn = sqlite3.connect("/data/msr.db")
cur = conn.execute("SELECT COUNT(*) FROM measurement_value")
print(json.dumps({"count": cur.fetchone()[0]}))
`

const dbWriteScript = `
import sqlite3, sys
conn = sqlite3.connect("/data/msr.db")
try:
    conn.execute(
        "INSERT INTO measurement_value (locator, salt, property, source) VALUES (?, ?, ?, ?)",
        ("integration-test-write", "x", "x", "nist"),
    )
    conn.commit()
    sys.exit(0)
except Exception as e:
    print(f"write failed: {e}", file=sys.stderr)
    sys.exit(1)
`

const dataFileCreateScript = `
import sys
try:
    with open("/data/canary.txt", "w") as f:
        f.write("x")
    sys.exit(0)
except Exception as e:
    print(f"create failed: {e}", file=sys.stderr)
    sys.exit(1)
`

const networkScript = `
import socket, sys
try:
    s = socket.create_connection(("8.8.8.8", 53), timeout=3)
    s.close()
    sys.exit(0)
except Exception as e:
    print(f"connect failed: {e}", file=sys.stderr)
    sys.exit(1)
`

const rootfsWriteScript = `
import sys
try:
    with open("/canary.txt", "w") as f:
        f.write("x")
    sys.exit(0)
except Exception as e:
    print(f"write failed: {e}", file=sys.stderr)
    sys.exit(1)
`

const scratchAndImportScript = `
with open("/tmp/scratch.txt", "w") as f:
    f.write("scratch ok")
import numpy
import pandas
print("ok")
`

// --- tests ---

func TestSandboxIntegration(t *testing.T) {
	rt := requireDocker(t)

	dataDir := seedDataDir(t)
	cfg := newIntegrationConfig(dataDir)

	p, err := sandbox.New(context.Background(), cfg, rt)
	if err != nil {
		t.Fatalf("sandbox.New: %v", err)
	}
	t.Cleanup(func() { p.Close() })

	t.Run("read succeeds and returns JSON", func(t *testing.T) {
		stdout, stderr, exitCode, err := p.Run(context.Background(), []byte(readScript))
		if err != nil {
			t.Fatalf("Run: %v (stderr=%s)", err, stderr)
		}
		if exitCode != 0 {
			t.Fatalf("exit code = %d, want 0; stderr=%s", exitCode, stderr)
		}
		var got struct {
			Count int `json:"count"`
		}
		if jsonErr := json.Unmarshal(bytes.TrimSpace(stdout), &got); jsonErr != nil {
			t.Fatalf("unmarshal stdout %q: %v", stdout, jsonErr)
		}
		if got.Count < 1 {
			t.Errorf("expected at least 1 seeded row, got count=%d", got.Count)
		}
	})

	t.Run("db write attempt fails (read-only mount)", func(t *testing.T) {
		_, stderr, exitCode, err := p.Run(context.Background(), []byte(dbWriteScript))
		if err != nil {
			t.Fatalf("Run: %v", err)
		}
		if exitCode == 0 {
			t.Fatalf("expected a non-zero exit for a DB write against a read-only mount, stderr=%s", stderr)
		}
	})

	t.Run("file create in /data fails (read-only mount)", func(t *testing.T) {
		_, stderr, exitCode, err := p.Run(context.Background(), []byte(dataFileCreateScript))
		if err != nil {
			t.Fatalf("Run: %v", err)
		}
		if exitCode == 0 {
			t.Fatalf("expected a non-zero exit creating a file in /data, stderr=%s", stderr)
		}
	})

	t.Run("outbound network fails (--network none)", func(t *testing.T) {
		_, stderr, exitCode, err := p.Run(context.Background(), []byte(networkScript))
		if err != nil {
			t.Fatalf("Run: %v", err)
		}
		if exitCode == 0 {
			t.Fatalf("expected an outbound connection to fail with --network none, stderr=%s", stderr)
		}
	})

	t.Run("write outside /tmp fails (read-only rootfs)", func(t *testing.T) {
		_, stderr, exitCode, err := p.Run(context.Background(), []byte(rootfsWriteScript))
		if err != nil {
			t.Fatalf("Run: %v", err)
		}
		if exitCode == 0 {
			t.Fatalf("expected a non-zero exit writing outside /tmp, stderr=%s", stderr)
		}
	})

	t.Run("scratch write and numpy/pandas import under noexec /tmp", func(t *testing.T) {
		stdout, stderr, exitCode, err := p.Run(context.Background(), []byte(scratchAndImportScript))
		if err != nil {
			t.Fatalf("Run: %v", err)
		}
		if exitCode != 0 {
			t.Fatalf("exit code = %d, want 0; stderr=%s", exitCode, stderr)
		}
		if !bytes.Contains(stdout, []byte("ok")) {
			t.Fatalf("expected stdout to contain \"ok\", got %q (stderr=%s)", stdout, stderr)
		}
	})

	t.Run("teardown: used container gone, fresh one present", func(t *testing.T) {
		if !dockerCLIAvailable() {
			t.Skip("docker CLI not found in PATH; cannot introspect containers directly")
		}
		label := sandbox.SandboxLabel + "=1"

		before := dockerContainerIDsWithLabel(t, label)
		if len(before) != cfg.PoolSize {
			t.Fatalf("expected %d labelled container(s) before Run, got %v", cfg.PoolSize, before)
		}

		if _, _, _, err := p.Run(context.Background(), []byte(readScript)); err != nil {
			t.Fatalf("Run: %v", err)
		}

		waitFor(t, 5*time.Second, func() bool {
			return len(dockerContainerIDsWithLabel(t, label)) == cfg.PoolSize
		})
		after := dockerContainerIDsWithLabel(t, label)

		if before[0] == after[0] {
			t.Fatalf("expected a freshly created container after the run, got the same id %s", before[0])
		}
		if dockerContainerExists(t, before[0]) {
			t.Errorf("expected the used container %s to be removed after its run", before[0])
		}
	})
}

// Orphan reaping (task 6.8's last bullet): a container labelled out-of-band
// (modeling one left behind by a crashed prior server process) is
// force-removed by a fresh New's startup sweep (design D9), before that
// new pool is considered ready.
func TestSandboxIntegration_OrphanReaping(t *testing.T) {
	rt := requireDocker(t)
	if !dockerCLIAvailable() {
		t.Skip("docker CLI not found in PATH; cannot create an out-of-band labelled container")
	}

	image := os.Getenv("MSR_SANDBOX_IMAGE")
	if image == "" {
		image = integrationImage
	}
	label := sandbox.SandboxLabel + "=1"

	out, err := exec.Command("docker", "run", "-d", "--label", label, image, "sleep", "300").Output()
	if err != nil {
		t.Fatalf("docker run (seeding an out-of-band orphan container): %v", err)
	}
	orphanID := strings.TrimSpace(string(out))
	t.Cleanup(func() {
		if dockerContainerExists(t, orphanID) {
			_ = exec.Command("docker", "rm", "-f", orphanID).Run()
		}
	})

	if !dockerContainerExists(t, orphanID) {
		t.Fatalf("expected the seeded orphan container %s to exist before the sweep", orphanID)
	}

	dataDir := seedDataDir(t)
	cfg := newIntegrationConfig(dataDir)

	p, err := sandbox.New(context.Background(), cfg, rt)
	if err != nil {
		t.Fatalf("sandbox.New (startup sweep): %v", err)
	}
	defer p.Close()

	if dockerContainerExists(t, orphanID) {
		t.Errorf("expected the pre-existing labelled orphan %s to be swept by New's startup Reap", orphanID)
	}
}
