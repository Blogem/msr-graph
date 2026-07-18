package main

// Unit tests for subcommand dispatch (tasks.md 5.1/5.2 CLI contract). These
// run unconditionally: dispatch itself needs no external service, and the
// seed/init-db bodies are exercised via runInitDB directly (init_test.go) or
// left to the tester's GraphDB-backed integration tests (seed).

import (
	"bytes"
	"strings"
	"testing"
)

func noEnv(string) string { return "" }

func TestRun_Dispatch(t *testing.T) {
	tests := []struct {
		name        string
		args        []string
		wantErr     bool
		wantErrText string
		wantStderr  bool
	}{
		{
			name:       "missing subcommand",
			args:       []string{},
			wantErr:    true,
			wantStderr: true,
		},
		{
			name:        "unknown subcommand",
			args:        []string{"bogus"},
			wantErr:     true,
			wantErrText: `unknown subcommand "bogus"`,
			wantStderr:  true,
		},
		{
			name:    "help",
			args:    []string{"help"},
			wantErr: false,
		},
		{
			name:    "-h flag",
			args:    []string{"-h"},
			wantErr: false,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			var stdout, stderr bytes.Buffer
			err := run(tc.args, noEnv, &stdout, &stderr)

			if tc.wantErr && err == nil {
				t.Fatalf("run(%v) = nil error, want an error", tc.args)
			}
			if !tc.wantErr && err != nil {
				t.Fatalf("run(%v) = %v, want no error", tc.args, err)
			}
			if tc.wantErrText != "" && (err == nil || !strings.Contains(err.Error(), tc.wantErrText)) {
				t.Errorf("run(%v) error = %v, want it to contain %q", tc.args, err, tc.wantErrText)
			}
			if tc.wantStderr && stderr.Len() == 0 {
				t.Errorf("run(%v): expected usage on stderr, got empty", tc.args)
			}
		})
	}
}

func TestLoadConfig_Defaults(t *testing.T) {
	cfg := loadConfig(noEnv)

	if cfg.graphDBURL != defaultGraphDBURL {
		t.Errorf("graphDBURL = %q, want default %q", cfg.graphDBURL, defaultGraphDBURL)
	}
	if cfg.graphDBRepo != defaultGraphDBRepo {
		t.Errorf("graphDBRepo = %q, want default %q", cfg.graphDBRepo, defaultGraphDBRepo)
	}
	if cfg.ontologyDir != defaultOntologyDir {
		t.Errorf("ontologyDir = %q, want default %q", cfg.ontologyDir, defaultOntologyDir)
	}
	if cfg.dbPath != defaultDBPath {
		t.Errorf("dbPath = %q, want default %q", cfg.dbPath, defaultDBPath)
	}
}

func TestLoadConfig_EnvOverrides(t *testing.T) {
	env := map[string]string{
		"GRAPHDB_URL":      "http://graphdb.example:9999",
		"GRAPHDB_REPO":     "custom-repo",
		"MSR_ONTOLOGY_DIR": "/tmp/ontology",
		"MSR_DB_PATH":      "/tmp/msr.db",
	}
	lookup := func(key string) string { return env[key] }

	cfg := loadConfig(lookup)

	if cfg.graphDBURL != env["GRAPHDB_URL"] {
		t.Errorf("graphDBURL = %q, want %q", cfg.graphDBURL, env["GRAPHDB_URL"])
	}
	if cfg.graphDBRepo != env["GRAPHDB_REPO"] {
		t.Errorf("graphDBRepo = %q, want %q", cfg.graphDBRepo, env["GRAPHDB_REPO"])
	}
	if cfg.ontologyDir != env["MSR_ONTOLOGY_DIR"] {
		t.Errorf("ontologyDir = %q, want %q", cfg.ontologyDir, env["MSR_ONTOLOGY_DIR"])
	}
	if cfg.dbPath != env["MSR_DB_PATH"] {
		t.Errorf("dbPath = %q, want %q", cfg.dbPath, env["MSR_DB_PATH"])
	}
}
