package sandbox

import (
	"testing"
)

// TestLoadConfig covers LoadConfig's env parsing and, critically, the D5
// regression: MSR_DATA_HOST_DIR is a HOST path the server resolves only via
// the Docker daemon, so LoadConfig must NOT stat it (an earlier version did,
// which crashed the containerized server because the host path is absent
// from the server container's own mount namespace).
func TestLoadConfig(t *testing.T) {
	// A path that does not exist in this process's filesystem stands in for
	// a host path that is invisible inside the server container.
	const hostOnlyPath = "/host/only/data/does-not-exist-locally"

	t.Run("host path absent locally is accepted (D5)", func(t *testing.T) {
		t.Setenv(envDataHostDir, hostOnlyPath)
		t.Setenv(envSandboxImage, "")

		cfg, err := LoadConfig()
		if err != nil {
			t.Fatalf("LoadConfig() error = %v; a nonexistent-locally host path must be accepted per D5", err)
		}
		if cfg.DataHostDir != hostOnlyPath {
			t.Errorf("DataHostDir = %q, want %q", cfg.DataHostDir, hostOnlyPath)
		}
		if cfg.Image != defaultImage {
			t.Errorf("Image = %q, want default %q", cfg.Image, defaultImage)
		}
	})

	t.Run("defaults are populated", func(t *testing.T) {
		t.Setenv(envDataHostDir, hostOnlyPath)
		t.Setenv(envSandboxImage, "")

		cfg, err := LoadConfig()
		if err != nil {
			t.Fatalf("LoadConfig() error = %v", err)
		}
		if cfg.PoolSize != defaultPoolSize {
			t.Errorf("PoolSize = %d, want %d", cfg.PoolSize, defaultPoolSize)
		}
		if cfg.CPUs != defaultCPUs {
			t.Errorf("CPUs = %v, want %v", cfg.CPUs, defaultCPUs)
		}
		if cfg.MemoryBytes != defaultMemoryBytes {
			t.Errorf("MemoryBytes = %d, want %d", cfg.MemoryBytes, defaultMemoryBytes)
		}
		if cfg.PidsLimit != defaultPidsLimit {
			t.Errorf("PidsLimit = %d, want %d", cfg.PidsLimit, defaultPidsLimit)
		}
		if cfg.TmpfsSize != defaultTmpfsSize {
			t.Errorf("TmpfsSize = %d, want %d", cfg.TmpfsSize, defaultTmpfsSize)
		}
		if cfg.Timeout != defaultTimeout {
			t.Errorf("Timeout = %v, want %v", cfg.Timeout, defaultTimeout)
		}
		if cfg.IdleTTL != defaultIdleTTL {
			t.Errorf("IdleTTL = %v, want %v", cfg.IdleTTL, defaultIdleTTL)
		}
	})

	t.Run("MSR_SANDBOX_IMAGE override is honored", func(t *testing.T) {
		t.Setenv(envDataHostDir, hostOnlyPath)
		t.Setenv(envSandboxImage, "custom-sandbox:9.9")

		cfg, err := LoadConfig()
		if err != nil {
			t.Fatalf("LoadConfig() error = %v", err)
		}
		if cfg.Image != "custom-sandbox:9.9" {
			t.Errorf("Image = %q, want %q", cfg.Image, "custom-sandbox:9.9")
		}
	})

	t.Run("unset MSR_DATA_HOST_DIR fails loudly", func(t *testing.T) {
		t.Setenv(envDataHostDir, "")

		if _, err := LoadConfig(); err == nil {
			t.Fatal("LoadConfig() error = nil; want error when MSR_DATA_HOST_DIR is unset")
		}
	})
}
