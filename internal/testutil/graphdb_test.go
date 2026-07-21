package testutil

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// fakeEnv builds an injectable getenv func(string) string backed by a map,
// so these tests never touch process environment variables.
func fakeEnv(vars map[string]string) func(string) string {
	return func(key string) string {
		return vars[key]
	}
}

func TestTestRepo(t *testing.T) {
	t.Run("defaults to msr-test when GRAPHDB_TEST_REPO is unset", func(t *testing.T) {
		got := TestRepo(fakeEnv(nil))
		if got != defaultTestRepo {
			t.Fatalf("TestRepo() = %q, want %q", got, defaultTestRepo)
		}
	})

	t.Run("honors an explicit GRAPHDB_TEST_REPO", func(t *testing.T) {
		env := fakeEnv(map[string]string{"GRAPHDB_TEST_REPO": "custom-repo"})
		got := TestRepo(env)
		if got != "custom-repo" {
			t.Fatalf("TestRepo() = %q, want %q", got, "custom-repo")
		}
	})
}

func TestRequireGraphDB_RepoResolution(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/repositories/custom-repo/size") {
			w.WriteHeader(http.StatusOK)
			return
		}
		w.WriteHeader(http.StatusNotFound)
	}))
	defer srv.Close()

	t.Run("default test repo is msr-test when unset", func(t *testing.T) {
		env := fakeEnv(map[string]string{"GRAPHDB_URL": srv.URL})
		d := RequireGraphDB(env)
		// msr-test isn't served by our handler (only custom-repo is), so we
		// expect a skip pointing at make test-repo -- proving the resolved
		// repo really is the default "msr-test", not e.g. "msr" or empty.
		if d.Action != ActionSkip {
			t.Fatalf("Action = %v, want ActionSkip", d.Action)
		}
		if !strings.Contains(d.Reason, "msr-test") {
			t.Fatalf("Reason = %q, want it to mention msr-test", d.Reason)
		}
	})

	t.Run("custom GRAPHDB_TEST_REPO is honored", func(t *testing.T) {
		env := fakeEnv(map[string]string{
			"GRAPHDB_URL":       srv.URL,
			"GRAPHDB_TEST_REPO": "custom-repo",
		})
		d := RequireGraphDB(env)
		if d.Action != ActionRun {
			t.Fatalf("Action = %v, want ActionRun; reason: %s", d.Action, d.Reason)
		}
		if d.Client == nil {
			t.Fatal("Client is nil, want non-nil on ActionRun")
		}
	})
}

func TestRequireGraphDB_Guard(t *testing.T) {
	// The guard (D2) must trip before any network call, so point at a
	// closed server to prove no request is actually made.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	srv.Close()

	guardCases := []struct {
		name string
		env  map[string]string
	}{
		{
			name: "explicit msr trips guard",
			env: map[string]string{
				"GRAPHDB_URL":       srv.URL,
				"GRAPHDB_TEST_REPO": "msr",
			},
		},
		{
			name: "test repo equals GRAPHDB_REPO trips guard",
			env: map[string]string{
				"GRAPHDB_URL":       srv.URL,
				"GRAPHDB_TEST_REPO": "production",
				"GRAPHDB_REPO":      "production",
			},
		},
		{
			// D2: literal "msr" is always forbidden regardless of
			// GRAPHDB_REPO -- prove the guard still trips even when
			// GRAPHDB_REPO is overridden to a different value, so route A
			// (testRepo == defaultProdRepo) can't be bypassed by
			// reconfiguring GRAPHDB_REPO.
			name: "explicit msr trips guard even when GRAPHDB_REPO points elsewhere",
			env: map[string]string{
				"GRAPHDB_URL":       srv.URL,
				"GRAPHDB_TEST_REPO": "msr",
				"GRAPHDB_REPO":      "some-other-prod-repo",
			},
		},
		{
			// GRAPHDB_TEST_REPO unset resolves to the default "msr-test",
			// which is safe UNLESS GRAPHDB_REPO has been (mis)configured to
			// equal that same default -- prove the guard still trips via
			// route B (testRepo == prodRepo) in that case, even though no
			// GRAPHDB_TEST_REPO was ever set explicitly.
			name: "unset GRAPHDB_TEST_REPO trips guard when GRAPHDB_REPO is misconfigured to match the default test repo",
			env: map[string]string{
				"GRAPHDB_URL":  srv.URL,
				"GRAPHDB_REPO": "msr-test",
			},
		},
	}

	for _, tc := range guardCases {
		t.Run(tc.name, func(t *testing.T) {
			d := RequireGraphDB(fakeEnv(tc.env))
			if d.Action != ActionSkip {
				t.Fatalf("Action = %v, want ActionSkip", d.Action)
			}
			if !strings.Contains(d.Reason, "refusing to run destructive integration tests") {
				t.Fatalf("Reason = %q, want refusal message", d.Reason)
			}
			if d.Client != nil {
				t.Fatal("Client should be nil on guard trip")
			}
		})
	}
}

func TestRequireGraphDB_ReachableRepoPresent(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	env := fakeEnv(map[string]string{
		"GRAPHDB_URL":       srv.URL,
		"GRAPHDB_TEST_REPO": "msr-test",
	})
	d := RequireGraphDB(env)
	if d.Action != ActionRun {
		t.Fatalf("Action = %v, want ActionRun; reason: %s", d.Action, d.Reason)
	}
	if d.Client == nil {
		t.Fatal("Client is nil, want non-nil on ActionRun")
	}
	if d.Reason != "" {
		t.Fatalf("Reason = %q, want empty on ActionRun", d.Reason)
	}
}

func TestRequireGraphDB_ReachableRepoAbsent(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	defer srv.Close()

	t.Run("skip without GRAPHDB_REQUIRED", func(t *testing.T) {
		env := fakeEnv(map[string]string{
			"GRAPHDB_URL":       srv.URL,
			"GRAPHDB_TEST_REPO": "msr-test",
		})
		d := RequireGraphDB(env)
		if d.Action != ActionSkip {
			t.Fatalf("Action = %v, want ActionSkip", d.Action)
		}
		if !strings.Contains(d.Reason, "make test-repo") {
			t.Fatalf("Reason = %q, want it to mention make test-repo", d.Reason)
		}
	})

	t.Run("fatal with GRAPHDB_REQUIRED", func(t *testing.T) {
		env := fakeEnv(map[string]string{
			"GRAPHDB_URL":       srv.URL,
			"GRAPHDB_TEST_REPO": "msr-test",
			"GRAPHDB_REQUIRED":  "1",
		})
		d := RequireGraphDB(env)
		if d.Action != ActionFatal {
			t.Fatalf("Action = %v, want ActionFatal", d.Action)
		}
		if !strings.Contains(d.Reason, "make test-repo") {
			t.Fatalf("Reason = %q, want it to mention make test-repo", d.Reason)
		}
	})
}

func TestRequireGraphDB_Unreachable(t *testing.T) {
	// A server that's been closed simulates connection-refused.
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	closedURL := srv.URL
	srv.Close()

	t.Run("skip without GRAPHDB_REQUIRED", func(t *testing.T) {
		env := fakeEnv(map[string]string{
			"GRAPHDB_URL":       closedURL,
			"GRAPHDB_TEST_REPO": "msr-test",
		})
		d := RequireGraphDB(env)
		if d.Action != ActionSkip {
			t.Fatalf("Action = %v, want ActionSkip; reason: %s", d.Action, d.Reason)
		}
		if !strings.Contains(d.Reason, "unreachable") {
			t.Fatalf("Reason = %q, want it to mention unreachable", d.Reason)
		}
	})

	t.Run("fatal with GRAPHDB_REQUIRED", func(t *testing.T) {
		env := fakeEnv(map[string]string{
			"GRAPHDB_URL":       closedURL,
			"GRAPHDB_TEST_REPO": "msr-test",
			"GRAPHDB_REQUIRED":  "1",
		})
		d := RequireGraphDB(env)
		if d.Action != ActionFatal {
			t.Fatalf("Action = %v, want ActionFatal; reason: %s", d.Action, d.Reason)
		}
		if !strings.Contains(d.Reason, "GRAPHDB_REQUIRED is set") {
			t.Fatalf("Reason = %q, want it to mention GRAPHDB_REQUIRED is set", d.Reason)
		}
	})
}
