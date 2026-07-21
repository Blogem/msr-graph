package graph_test

// Design constraint D6 (openspec/changes/bootstrap-graph-infra/design.md) --
// the shared integration-test reachability/skip/fatal guard.
//
// This used to be duplicated package-local across internal/graph,
// internal/proposal, and internal/checkpoint, each hardcoding the "msr"
// repo. The reachability probe, disposable test-repo resolution, and the
// hard guard now live in internal/testutil (see
// docs/plans/isolate-integration-test-repo.md, D1/D2/D2a); this file is a
// thin wrapper that translates testutil.RequireGraphDB's Decision into
// t.Skip/t.Fatal.
//
// graphDBBaseURL is kept here (not duplicated reachability logic, just a
// trivial GRAPHDB_URL-with-default accessor) because other integration test
// files in this package (e.g. nist_loader_integration_test.go,
// seed_integration_test.go, shacl_shapes_load_integration_test.go,
// provenance_lineage_integration_test.go) call it directly to build request
// URLs against the same GraphDB instance requireGraphDB's client targets.

import (
	"os"
	"testing"

	"github.com/blogem/msr-graph/internal/graph"
	"github.com/blogem/msr-graph/internal/testutil"
)

// defaultGraphDBURL is used when GRAPHDB_URL is unset, matching
// internal/testutil's default.
const defaultGraphDBURL = "http://localhost:7200"

// graphDBBaseURL returns the configured GRAPHDB_URL, defaulting to
// http://localhost:7200. Other integration test files in this package use
// it directly to build request URLs.
func graphDBBaseURL() string {
	if v := os.Getenv("GRAPHDB_URL"); v != "" {
		return v
	}
	return defaultGraphDBURL
}

// requireGraphDB delegates to testutil.RequireGraphDB and translates the
// returned Decision into t.Skip/t.Fatal, returning a ready-to-use
// *graph.Client for the resolved test repo (GRAPHDB_TEST_REPO, default
// "msr-test") when reachable.
func requireGraphDB(t *testing.T) *graph.Client {
	t.Helper()

	d := testutil.RequireGraphDB(os.Getenv)
	switch d.Action {
	case testutil.ActionSkip:
		t.Skip(d.Reason)
	case testutil.ActionFatal:
		t.Fatal(d.Reason)
	}
	return d.Client
}
