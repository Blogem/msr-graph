package sandbox

import (
	"fmt"
	"os"
	"time"
)

// Conservative defaults for the sandbox pool. This is a controlled POC:
// these values are chosen for sanity, not tuned against a workload (design
// D4, "Resolved decisions"). defaultIdleTTL is deliberately far larger than
// defaultTimeout -- it must always exceed the per-run wall-clock timeout so
// the idle-TTL backstop (design D9) never races a legitimate run.
const (
	// defaultPoolSize is the number of warm containers the pool holds.
	defaultPoolSize = 3

	// defaultCPUs is the --cpus limit applied to each sandbox.
	defaultCPUs = 1.0

	// defaultMemoryBytes is the --memory limit (256 MiB) applied to each
	// sandbox, with swap disabled.
	defaultMemoryBytes = 256 << 20

	// defaultPidsLimit is the --pids-limit applied to each sandbox,
	// bounding fork bombs.
	defaultPidsLimit = 128

	// defaultTmpfsSize is the size (64 MiB) of the noexec tmpfs mounted at
	// /tmp in each sandbox.
	defaultTmpfsSize = 64 << 20

	// defaultTimeout is the per-run wall-clock timeout: a run exceeding it
	// is terminated by force-removing its container.
	defaultTimeout = 30 * time.Second

	// defaultIdleTTL is the bounded idle sleep TTL for a sandbox's PID 1.
	// It MUST be, and is, far larger than defaultTimeout.
	defaultIdleTTL = time.Hour

	// defaultImage is the sandbox image reference used when
	// MSR_SANDBOX_IMAGE is unset, matching the tag `make up` builds.
	defaultImage = "msr-sandbox-base:latest"
)

// envSandboxImage names the sandbox image to run; defaults to defaultImage
// when unset or empty.
const envSandboxImage = "MSR_SANDBOX_IMAGE"

// envDataHostDir names the HOST path of the data directory that every
// sandbox bind-mounts read-only at /data. It must be the path as resolved
// by the Docker daemon on the host, not any path inside the caller's own
// container's mount namespace (design D5) -- the classic docker-socket
// sibling-mount gotcha: getting it wrong silently mounts the wrong, or an
// empty, directory. There is no safe default, so LoadConfig fails loudly
// if it is unset or does not resolve to an existing directory.
const envDataHostDir = "MSR_DATA_HOST_DIR"

// Config holds the sandbox pool's configuration: pool size, per-container
// resource limits, timeouts, and the image/data-mount identifying where
// and what each sandbox runs.
type Config struct {
	// PoolSize is the number of warm containers the pool holds. Default 3.
	PoolSize int

	// CPUs is the --cpus limit applied to each sandbox.
	CPUs float64

	// MemoryBytes is the --memory limit (swap disabled) applied to each
	// sandbox.
	MemoryBytes int64

	// PidsLimit is the --pids-limit applied to each sandbox.
	PidsLimit int64

	// TmpfsSize is the size in bytes of the noexec tmpfs mounted at /tmp in
	// each sandbox.
	TmpfsSize int64

	// Timeout is the per-run wall-clock timeout.
	Timeout time.Duration

	// IdleTTL is the bounded idle sleep TTL for a sandbox's PID 1. MUST be
	// far larger than Timeout so it never races a legitimate run.
	IdleTTL time.Duration

	// Image is the sandbox image reference, from MSR_SANDBOX_IMAGE
	// (default "msr-sandbox-base:latest").
	Image string

	// DataHostDir is the HOST path of the data directory bind-mounted
	// read-only at /data in every sandbox, from MSR_DATA_HOST_DIR. It must
	// be an existing directory.
	DataHostDir string
}

// LoadConfig reads MSR_DATA_HOST_DIR and MSR_SANDBOX_IMAGE from the
// environment and fills all other fields with conservative defaults.
//
// MSR_DATA_HOST_DIR has no default: LoadConfig fails loudly if it is
// unset, empty, or does not resolve (via os.Stat) to an existing
// directory, since a silently wrong value would mount an empty or
// incorrect directory into every sandbox (design D5).
func LoadConfig() (Config, error) {
	image := os.Getenv(envSandboxImage)
	if image == "" {
		image = defaultImage
	}

	dataHostDir := os.Getenv(envDataHostDir)
	if dataHostDir == "" {
		return Config{}, fmt.Errorf("sandbox: %s is unset; it must be set to the HOST path of the data directory (the path as resolved by the Docker daemon on the host, not a path inside this process's own container) so sandbox containers bind-mount the correct directory read-only", envDataHostDir)
	}
	fi, err := os.Stat(dataHostDir)
	if err != nil {
		return Config{}, fmt.Errorf("sandbox: %s=%q does not exist or is not accessible; it must be the HOST path of the data directory (the path as resolved by the Docker daemon on the host, not a path inside this process's own container): %w", envDataHostDir, dataHostDir, err)
	}
	if !fi.IsDir() {
		return Config{}, fmt.Errorf("sandbox: %s=%q is not a directory; it must be the HOST path of the data directory (the path as resolved by the Docker daemon on the host, not a path inside this process's own container)", envDataHostDir, dataHostDir)
	}

	return Config{
		PoolSize:    defaultPoolSize,
		CPUs:        defaultCPUs,
		MemoryBytes: defaultMemoryBytes,
		PidsLimit:   defaultPidsLimit,
		TmpfsSize:   defaultTmpfsSize,
		Timeout:     defaultTimeout,
		IdleTTL:     defaultIdleTTL,
		Image:       image,
		DataHostDir: dataHostDir,
	}, nil
}
