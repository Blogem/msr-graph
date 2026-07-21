// Package testutil centralizes shared integration-test scaffolding that must
// not depend on the "testing" package -- most notably the GraphDB
// reachability probe, disposable test-repo resolution, and the hard guard
// that refuses to run destructive integration tests against the production
// "msr" repository.
//
// See docs/plans/isolate-integration-test-repo.md (design decisions D1, D2,
// D2a, D3) for the incident and rationale this package addresses. Chunk-1
// design D6 (openspec/changes/bootstrap-graph-infra/design.md) originally
// specified the reachability/skip/fatal semantics this package now owns; it
// used to be duplicated across internal/graph, internal/proposal, and
// internal/checkpoint testhelper_test.go files, each hardcoding the "msr"
// repo. Those packages now delegate to RequireGraphDB and translate the
// returned Decision into t.Skip / t.Fatal.
//
// This package must never import "testing": callers own the *testing.T
// interactions so the reachability/guard logic itself stays free of test
// framework assumptions and independently unit-testable.
package testutil

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"syscall"
	"time"

	"github.com/blogem/msr-graph/internal/graph"
)

const (
	// defaultGraphDBURL is used when GRAPHDB_URL is unset.
	defaultGraphDBURL = "http://localhost:7200"
	// defaultTestRepo is used when GRAPHDB_TEST_REPO is unset (D1). This must
	// never be the production repo name.
	defaultTestRepo = "msr-test"
	// defaultProdRepo is used when GRAPHDB_REPO is unset, and is always
	// treated as forbidden for integration tests regardless of GRAPHDB_REPO
	// (D2).
	defaultProdRepo = "msr"

	reachabilityTimeout = 5 * time.Second
	clientTimeout       = 30 * time.Second
)

// Action describes what a caller should do after RequireGraphDB resolves the
// test repo and probes reachability.
type Action int

const (
	// ActionRun indicates GraphDB is reachable, the resolved test repo
	// exists, and Decision.Client is ready to use.
	ActionRun Action = iota
	// ActionSkip indicates the caller should skip the test (e.g. t.Skip)
	// with Decision.Reason as the message. This is always non-destructive.
	ActionSkip
	// ActionFatal indicates the caller should fail the test hard (e.g.
	// t.Fatal) with Decision.Reason as the message -- reserved for broken
	// environments or, when GRAPHDB_REQUIRED is set, unreachable/absent
	// repos that would otherwise just skip.
	ActionFatal
)

// Decision is the result of RequireGraphDB: what the caller should do, why,
// and (only when Action == ActionRun) a ready-to-use client.
type Decision struct {
	// Client is non-nil only when Action == ActionRun.
	Client *graph.Client
	Action Action
	// Reason is a human-readable message for Skip/Fatal callers to surface
	// via t.Skip/t.Fatal. Empty when Action == ActionRun.
	Reason string
}

// RequireGraphDB implements the D1/D2/D2a reachability, repo-resolution, and
// safety-guard logic shared by integration tests across packages. It takes
// no *testing.T (this package must not import "testing"); callers translate
// the returned Decision into t.Skip/t.Fatal/proceed.
//
// getenv is the environment lookup function (typically os.Getenv); it is
// injectable so unit tests can exercise this logic hermetically without
// touching process environment variables.
//
// Behavior:
//
//   - D1: the target repo is resolved from GRAPHDB_TEST_REPO, defaulting to
//     "msr-test" (never hardcoded to "msr"). GRAPHDB_URL selects the server
//     (default http://localhost:7200). GRAPHDB_REQUIRED (any non-empty
//     value) flips skip -> fatal for unreachability/absent-repo cases. The
//     production repo name is read from GRAPHDB_REPO (default "msr") for the
//     guard comparison below.
//   - D2: if the resolved test repo equals the production repo -- literally
//     "msr", or whatever GRAPHDB_REPO resolves to -- this returns ActionSkip
//     with a loud, explicit refusal reason, checked BEFORE any network call.
//     This is a skip (not fatal) so a bare `go test ./...` stays
//     non-destructive by default.
//   - Reachability probe: GET {baseURL}/repositories/{testRepo}/size with a
//     5s timeout.
//   - connection refused / timeout + GRAPHDB_REQUIRED unset -> ActionSkip.
//   - connection refused / timeout + GRAPHDB_REQUIRED set   -> ActionFatal.
//   - D2a: GraphDB responds but the test repo itself is absent/unhealthy
//     (non-2xx, e.g. 404) -> ActionSkip telling the caller to run
//     `make test-repo` first, UNLESS GRAPHDB_REQUIRED is set, in which case
//     ActionFatal. This differs from treating an absent repo as always
//     fatal: for the disposable test repo, absent just means "not
//     provisioned yet".
//   - Any other transport error (DNS, TLS, ...) -> ActionFatal (broken
//     environment) in both modes.
//   - Healthy 2xx -> ActionRun with a *graph.Client built via
//     graph.New(baseURL, testRepo, &http.Client{Timeout: 30s}).
func RequireGraphDB(getenv func(string) string) Decision {
	if getenv == nil {
		getenv = os.Getenv
	}

	baseURL := graphDBBaseURL(getenv)
	testRepo := graphDBTestRepo(getenv)
	prodRepo := graphDBProdRepo(getenv)
	required := graphDBRequired(getenv)

	// D2: hard guard, checked before any network call.
	if testRepo == defaultProdRepo || testRepo == prodRepo {
		return Decision{
			Action: ActionSkip,
			Reason: fmt.Sprintf(
				"refusing to run destructive integration tests against the production repo %q; "+
					"set GRAPHDB_TEST_REPO to a disposable repo (see make test-repo)",
				testRepo,
			),
		}
	}

	checkClient := &http.Client{Timeout: reachabilityTimeout}
	checkURL := fmt.Sprintf("%s/repositories/%s/size", baseURL, testRepo)

	req, err := http.NewRequestWithContext(context.Background(), http.MethodGet, checkURL, nil)
	if err != nil {
		return Decision{
			Action: ActionFatal,
			Reason: fmt.Sprintf("RequireGraphDB: building reachability request: %v", err),
		}
	}

	resp, err := checkClient.Do(req)
	if err != nil {
		if isUnreachable(err) {
			reason := fmt.Sprintf(
				"GraphDB unreachable at %s (repo %q): %v -- start the compose stack (`make up`) or set GRAPHDB_URL",
				baseURL, testRepo, err,
			)
			if required {
				return Decision{Action: ActionFatal, Reason: "GRAPHDB_REQUIRED is set but " + reason}
			}
			return Decision{Action: ActionSkip, Reason: reason}
		}
		// Any other transport-level failure (DNS, TLS, ...) is a broken
		// environment, not an absent one -- fail hard in both modes.
		return Decision{
			Action: ActionFatal,
			Reason: fmt.Sprintf("RequireGraphDB: broken environment reaching GraphDB at %s: %v", baseURL, err),
		}
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		// D2a: GraphDB is up but the disposable test repo isn't provisioned
		// yet -- skippable, not a broken environment.
		reason := fmt.Sprintf(
			"RequireGraphDB: GraphDB at %s responded but test repo %q is missing or unhealthy (status %d) -- run `make test-repo` first",
			baseURL, testRepo, resp.StatusCode,
		)
		if required {
			return Decision{Action: ActionFatal, Reason: "GRAPHDB_REQUIRED is set but " + reason}
		}
		return Decision{Action: ActionSkip, Reason: reason}
	}

	return Decision{
		Action: ActionRun,
		Client: graph.New(baseURL, testRepo, &http.Client{Timeout: clientTimeout}),
	}
}

// graphDBBaseURL returns the configured GRAPHDB_URL, defaulting to
// http://localhost:7200 per D1.
func graphDBBaseURL(getenv func(string) string) string {
	if v := getenv("GRAPHDB_URL"); v != "" {
		return v
	}
	return defaultGraphDBURL
}

// graphDBTestRepo returns the configured GRAPHDB_TEST_REPO, defaulting to
// "msr-test" per D1. Never hardcode "msr" here.
func graphDBTestRepo(getenv func(string) string) string {
	if v := getenv("GRAPHDB_TEST_REPO"); v != "" {
		return v
	}
	return defaultTestRepo
}

// graphDBProdRepo returns the configured GRAPHDB_REPO, defaulting to "msr",
// used only as the D2 guard comparison target.
func graphDBProdRepo(getenv func(string) string) string {
	if v := getenv("GRAPHDB_REPO"); v != "" {
		return v
	}
	return defaultProdRepo
}

// graphDBRequired reports whether GRAPHDB_REQUIRED is set to any non-empty
// value (the exact trigger D1 specifies for switching skip -> fatal).
func graphDBRequired(getenv func(string) string) bool {
	return getenv("GRAPHDB_REQUIRED") != ""
}

// isUnreachable reports whether err represents connection-refused or timeout
// at the transport level -- the ONLY conditions that are skippable for
// unreachability. Any other transport error (DNS failure, TLS error, etc.) is
// treated as a broken environment and must fail hard in both modes.
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
