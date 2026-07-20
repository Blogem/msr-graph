package graph_test

// Integration tests 5.9 and 5.10 for the provenance-run-lineage change,
// guarded by the D6 requireGraphDB helper (testhelper_test.go). These run
// `loader nist` twice against a live GraphDB (two distinct wall-clock runs,
// per design D1/D2) and assert the crux of the change:
//
//   - a re-asserted fact (the FLiBe salt) accumulates one
//     prov:wasGeneratedBy edge per run in the append-only urn:msr:provenance
//     graph (task 5.9, spec "A fact asserted by multiple runs accumulates
//     one edge per run")
//   - the SAME fact still resolves to exactly one prov:wasGeneratedBy edge
//     -- the stable msrd:activity-loader-nist -- under a core-scoped read,
//     because urn:msr:provenance is not a member of graph.CoreGraphs (task
//     5.10, spec "Provenance graph is not in the core read set")
//
// runLoader, runLoaderSeed, repoRoot, graphDBBaseURL, requireGraphDB, and
// flibeSaltCURIE are reused from nist_loader_integration_test.go /
// seed_integration_test.go / testhelper_test.go rather than redefined here.

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"github.com/blogem/msr-graph/internal/graph"
)

// flibeProvenanceRuns returns the set of distinct prov:wasGeneratedBy
// objects for the FLiBe salt within GRAPH <urn:msr:provenance>, queried via
// SelectRaw with an explicit GRAPH clause (per design D5: provenance is
// opt-in via an explicit GRAPH scope, not a core Select). Used to compute a
// before/after delta rather than an absolute count, since urn:msr:provenance
// is append-only and persists across loads (design D6) and may already
// carry lineage from runs outside this test on a shared GraphDB instance.
func flibeProvenanceRuns(t *testing.T, ctx context.Context, client *graph.Client) map[string]bool {
	t.Helper()
	query := `
		PREFIX msrd: <https://w3id.org/msr-kg/data#>
		PREFIX prov: <http://www.w3.org/ns/prov#>
		SELECT ?run WHERE {
			GRAPH <urn:msr:provenance> {
				msrd:salt-BeF2-LiF-34.0-66.0 prov:wasGeneratedBy ?run .
			}
		}
	`
	results, err := client.SelectRaw(ctx, query)
	if err != nil {
		t.Fatalf("SelectRaw for provenance-scoped lineage of the FLiBe salt: %v", err)
	}
	runs := make(map[string]bool)
	for _, b := range results.Results.Bindings {
		runs[b["run"].Value] = true
	}
	return runs
}

// stableLoaderActivityIRI is the full-IRI form of the deterministic
// msrd:activity-loader-nist Activity every loader-emitted fact references
// via prov:wasGeneratedBy in urn:msr:data (design D1). Full-IRI form is
// used (rather than the msrd: CURIE) because Results bindings return
// resolved IRIs, not prefixed names.
const stableLoaderActivityIRI = "https://w3id.org/msr-kg/data#activity-loader-nist"

// TestProvenanceLineage_MultiRunAccumulatesEdgesCoreReadStaysStable pins
// tasks 5.9 and 5.10 together: after two distinct loader runs assert the
// same FLiBe salt, urn:msr:provenance holds two distinct per-run
// prov:wasGeneratedBy edges for it (append-only lineage, task 5.9), while a
// core-scoped Select for the same predicate on the same subject returns
// exactly one object -- the stable msrd:activity-loader-nist -- because
// urn:msr:provenance is outside graph.CoreGraphs and never leaks into core
// reads (task 5.10).
func TestProvenanceLineage_MultiRunAccumulatesEdgesCoreReadStaysStable(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()
	baseURL := graphDBBaseURL()

	dbPath := filepath.Join(t.TempDir(), "measurements.db")
	env := []string{"GRAPHDB_URL=" + baseURL, "MSR_DB_PATH=" + dbPath}

	// urn:msr:provenance is explicitly append-only and persists across loads
	// (design D6) -- on a shared/persistent GraphDB instance (as opposed to
	// a throwaway per-test repo) it may already carry per-run lineage edges
	// for the FLiBe salt from runs outside this test (including another test
	// in this same package, e.g. TestNistLoadIdempotentAcrossBothStores,
	// which also loads the FLiBe salt). So this test asserts a DELTA (exactly
	// 2 NEW distinct per-run objects appear) rather than an absolute total,
	// which would be flaky against any pre-existing state.
	baselineRuns := flibeProvenanceRuns(t, ctx, client)

	// Settle onto a fresh wall-clock second before minting this test's own
	// two runs: buildProvenanceData's per-run activity IRI has only second
	// precision (time.RFC3339), so a preceding test's loader invocation
	// landing in the same second as this test's first run would otherwise
	// make the baseline capture above indistinguishable from this test's
	// own first run -- collapsing the delta below 2 and making the test
	// flaky depending on how fast consecutive tests execute.
	time.Sleep(1200 * time.Millisecond)
	runLoaderSeed(t, baseURL)
	runLoader(t, "nist", env...)
	// Same reasoning, between this test's own two runs: guarantee a distinct
	// per-run IRI for the second run rather than risking a same-second
	// collision with the first.
	time.Sleep(1200 * time.Millisecond)
	runLoader(t, "nist", env...)

	t.Run("urn:msr:provenance accumulates one generation edge per run", func(t *testing.T) {
		afterRuns := flibeProvenanceRuns(t, ctx, client)

		newRuns := make(map[string]bool)
		for run := range afterRuns {
			if !baselineRuns[run] {
				newRuns[run] = true
			}
		}
		if len(newRuns) != 2 {
			t.Fatalf("expected exactly 2 NEW distinct per-run prov:wasGeneratedBy objects for the FLiBe salt in urn:msr:provenance after this test's 2 runs, got %d (baseline had %d, total now %d): new=%v",
				len(newRuns), len(baselineRuns), len(afterRuns), newRuns)
		}
		for run := range newRuns {
			if run == stableLoaderActivityIRI {
				t.Errorf("urn:msr:provenance generation edge unexpectedly points at the stable activity %s, want a per-run urn:msr:run:loader/<ts> IRI", stableLoaderActivityIRI)
			}
		}
	})

	t.Run("core-scoped read sees only the single stable activity", func(t *testing.T) {
		query := `
			PREFIX msrd: <https://w3id.org/msr-kg/data#>
			PREFIX prov: <http://www.w3.org/ns/prov#>
			SELECT ?activity WHERE {
				msrd:salt-BeF2-LiF-34.0-66.0 prov:wasGeneratedBy ?activity .
			}
		`
		results, err := client.Select(ctx, query)
		if err != nil {
			t.Fatalf("Select (core-scoped) for the FLiBe salt's prov:wasGeneratedBy: %v", err)
		}
		if len(results.Results.Bindings) != 1 {
			t.Fatalf("expected exactly 1 core-scoped prov:wasGeneratedBy binding for the FLiBe salt (the stable activity only), got %d: %v", len(results.Results.Bindings), results.Results.Bindings)
		}
		if got := results.Results.Bindings[0]["activity"].Value; got != stableLoaderActivityIRI {
			t.Errorf("core-scoped prov:wasGeneratedBy object = %q, want the stable activity %q -- per-run lineage in urn:msr:provenance must not leak into core reads", got, stableLoaderActivityIRI)
		}
	})
}
