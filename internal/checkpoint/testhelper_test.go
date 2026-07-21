package checkpoint_test

// requireGraphDB used to replicate internal/graph/testhelper_test.go's D6
// reachability/skip/fatal guard package-local (see
// internal/proposal/testhelper_test.go for the identical duplication and
// its rationale). That duplicated logic now lives in internal/testutil (see
// docs/plans/isolate-integration-test-repo.md, D1/D2/D2a); this file is a
// thin wrapper that translates testutil.RequireGraphDB's Decision into
// t.Skip/t.Fatal.

import (
	"os"
	"testing"

	"github.com/blogem/msr-graph/internal/graph"
	"github.com/blogem/msr-graph/internal/testutil"
)

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
