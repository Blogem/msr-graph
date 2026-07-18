package graph_test

// Design constraint D6 (openspec/changes/bootstrap-graph-infra/design.md) --
// the shared integration-test reachability/skip/fatal guard.
//
// This lives package-local to internal/graph for chunk 1; a comment in
// design.md notes that later chunks (which also need a live GraphDB for
// their own integration tests) may promote this helper to a shared package
// such as internal/testutil rather than duplicating it.

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"syscall"
	"testing"
	"time"

	"github.com/blogem/msr-graph/internal/graph"
)

const (
	defaultGraphDBURL   = "http://localhost:7200"
	integrationRepo     = "msr"
	reachabilityTimeout = 5 * time.Second
	clientTimeout       = 30 * time.Second
)

// graphDBBaseURL returns the configured GRAPHDB_URL, defaulting to
// http://localhost:7200 per D6.
func graphDBBaseURL() string {
	if v := os.Getenv("GRAPHDB_URL"); v != "" {
		return v
	}
	return defaultGraphDBURL
}

// graphDBRequired reports whether GRAPHDB_REQUIRED is set to any non-empty
// value (the exact trigger D6 specifies for switching skip -> fatal).
func graphDBRequired() bool {
	return os.Getenv("GRAPHDB_REQUIRED") != ""
}

// requireGraphDB implements D6's reachability/skip/fatal guard and returns a
// ready-to-use *graph.Client for repo "msr" against GRAPHDB_URL.
//
//   - connection refused / timeout, GRAPHDB_REQUIRED unset -> t.Skip (clear reason)
//   - connection refused / timeout, GRAPHDB_REQUIRED set   -> t.Fatal
//   - GraphDB responds but errors (5xx, missing repo)      -> t.Fatal in BOTH modes
//   - GraphDB responds healthy                              -> returns the client
//
// The reachability check hits GraphDB's /repositories/{repo}/size endpoint:
// a single GET that both proves the server is up and that the "msr"
// repository actually exists (a missing repo yields a non-2xx status, which
// this helper treats as "responds but errors", never as "absent").
func requireGraphDB(t *testing.T) *graph.Client {
	t.Helper()

	baseURL := graphDBBaseURL()
	checkClient := &http.Client{Timeout: reachabilityTimeout}
	checkURL := fmt.Sprintf("%s/repositories/%s/size", baseURL, integrationRepo)

	req, err := http.NewRequestWithContext(context.Background(), http.MethodGet, checkURL, nil)
	if err != nil {
		t.Fatalf("requireGraphDB: building reachability request: %v", err)
	}

	resp, err := checkClient.Do(req)
	if err != nil {
		if isUnreachable(err) {
			reason := fmt.Sprintf(
				"GraphDB unreachable at %s (repo %q): %v -- start the compose stack (`make up`) or set GRAPHDB_URL",
				baseURL, integrationRepo, err,
			)
			if graphDBRequired() {
				t.Fatalf("GRAPHDB_REQUIRED is set but %s", reason)
			}
			t.Skip(reason)
			return nil
		}
		// Any other transport-level failure (DNS, TLS, ...) is a broken
		// environment, not an absent one -- fail hard in both modes.
		t.Fatalf("requireGraphDB: broken environment reaching GraphDB at %s: %v", baseURL, err)
		return nil
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		t.Fatalf(
			"requireGraphDB: GraphDB at %s responded but repo %q is unhealthy or missing (status %d) -- this is a broken environment, not an absent one",
			baseURL, integrationRepo, resp.StatusCode,
		)
	}

	return graph.New(baseURL, integrationRepo, &http.Client{Timeout: clientTimeout})
}

// isUnreachable reports whether err represents connection-refused or timeout
// at the transport level -- the ONLY conditions D6 permits skipping for.
// Any other transport error (DNS failure, TLS error, etc.) is treated as a
// broken environment and must fail hard in both modes.
func isUnreachable(err error) bool {
	if err == nil {
		return false
	}
	if errors.Is(err, syscall.ECONNREFUSED) {
		return true
	}
	var netErr net.Error
	if errors.As(err, &netErr) && netErr.Timeout() {
		return true
	}
	return false
}
