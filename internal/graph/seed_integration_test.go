package graph_test

// Integration tests 6.6 and 6.7, guarded by the D6 helper in
// testhelper_test.go (requireGraphDB). These additionally invoke the loader
// CLI contract ("go run ./cmd/loader seed") via os/exec -- per the task
// brief, cmd/loader's seed/init-db subcommands land in a later wave, so
// these tests will not pass until that lands, but they are authored now
// against the pinned contract.

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"testing"
	"time"

	"github.com/blogem/msr-graph/internal/graph"
)

// repoRoot locates the module root from this test file's own path so the
// loader can be invoked with `go run ./cmd/loader ...` regardless of the
// working directory `go test` is invoked from.
func repoRoot(t *testing.T) string {
	t.Helper()
	_, thisFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("repoRoot: runtime.Caller failed")
	}
	// thisFile: <repoRoot>/internal/graph/seed_integration_test.go
	return filepath.Dir(filepath.Dir(filepath.Dir(thisFile)))
}

// runLoaderSeed runs `go run ./cmd/loader seed` against baseURL, per the
// loader CLI contract (tasks.md 5.1/5.3): it PUTs the three seed files into
// their named graphs and ensures urn:msr:staging exists without touching
// existing content.
//
// Assumption: the loader reads its GraphDB endpoint from the GRAPHDB_URL
// env var, consistent with the rest of the D6 contract. The loader CLI is
// not implemented yet (lands in a later wave), so this exact configuration
// mechanism is not pinned anywhere -- confirm it once cmd/loader exists.
func runLoaderSeed(t *testing.T, baseURL string) {
	t.Helper()
	cmd := exec.Command("go", "run", "./cmd/loader", "seed")
	cmd.Dir = repoRoot(t)
	cmd.Env = append(os.Environ(), "GRAPHDB_URL="+baseURL)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("`go run ./cmd/loader seed` failed: %v\noutput:\n%s", err, out)
	}
}

// countGraphTriples returns the triple count of a single named graph via
// SelectRaw, per task 6.7's "query counts via SelectRaw per named graph".
func countGraphTriples(t *testing.T, client *graph.Client, iri graph.GraphIRI) int {
	t.Helper()
	query := fmt.Sprintf(`SELECT (COUNT(*) AS ?count) WHERE { GRAPH <%s> { ?s ?p ?o } }`, iri)
	results, err := client.SelectRaw(context.Background(), query)
	if err != nil {
		t.Fatalf("counting triples in %s: %v", iri, err)
	}
	if len(results.Results.Bindings) != 1 {
		t.Fatalf("expected exactly one COUNT(*) binding for %s, got %d", iri, len(results.Results.Bindings))
	}
	n, err := strconv.Atoi(results.Results.Bindings[0]["count"].Value)
	if err != nil {
		t.Fatalf("parsing triple count for %s: %v", iri, err)
	}
	return n
}

// TestSeedLoadWritesNoDataGraphTriples pins seed-graph-loading spec.md's
// "Only TBox and vocab load, no A-Box" scenario (ground-demo-in-real-docs
// change): `make load-seed` (`loader seed`) loads only ontology/msr.ttl ->
// urn:msr:ontology and ontology/vocab.ttl -> urn:msr:vocab. There is no
// hand-curated A-Box seed anymore -- ontology/example-flibe.ttl was removed
// by ground-demo-in-real-docs -- so urn:msr:data MUST hold zero triples
// after `loader seed` runs alone. urn:msr:data is populated exclusively by
// the real-data writers: `loader nist` (salt + measurement) and the
// extraction pipeline's `link` step (the msr:Mention -> msr:linksTo ->
// salt edge). The FLiBe measurement's queryability after seed+nist is
// covered by nist_loader_integration_test.go's "FLiBe density measurement
// queryable via core client" subtest, not here -- this test only pins the
// seed step's own no-A-Box contract.
func TestSeedLoadWritesNoDataGraphTriples(t *testing.T) {
	client := requireGraphDB(t)
	runLoaderSeed(t, graphDBBaseURL())

	got := countGraphTriples(t, client, graph.Data)
	if got != 0 {
		t.Errorf("urn:msr:data triple count after `loader seed` alone = %d, want 0 (load-seed must not write any A-Box/data-graph triples -- there is no hand-curated seed anymore)", got)
	}
}

// TestSeedLoadIsIdempotent pins seed-graph-loading spec.md's "Graph-replace
// removes stale triples" / double-load-is-a-no-op contract and "Existing
// staging content preserved" scenario: since ground-demo-in-real-docs,
// `loader seed` only PUTs urn:msr:ontology and urn:msr:vocab (no A-Box
// graph is touched), so running the seed load twice yields identical
// per-graph triple counts across graph.CoreGraphs, and a pre-existing
// urn:msr:staging triple (an unrelated graph the seed load never writes)
// survives both runs untouched -- the staging-preservation probe stays
// valid unchanged by the seed-A-Box removal.
func TestSeedLoadIsIdempotent(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()
	baseURL := graphDBBaseURL()

	stagingSubject := fmt.Sprintf("urn:msr:test:idempotency-probe-%d", time.Now().UnixNano())
	const stagingPredicate = "urn:msr:test:predicate"
	insertProbe := fmt.Sprintf(`INSERT DATA { GRAPH <urn:msr:staging> { <%s> <%s> "still-here" . } }`, stagingSubject, stagingPredicate)
	if err := client.Update(ctx, insertProbe); err != nil {
		t.Fatalf("inserting pre-existing staging triple: %v", err)
	}

	runLoaderSeed(t, baseURL)

	counts := map[graph.GraphIRI]int{}
	for _, g := range graph.CoreGraphs {
		counts[g] = countGraphTriples(t, client, g)
	}

	runLoaderSeed(t, baseURL)

	for _, g := range graph.CoreGraphs {
		got := countGraphTriples(t, client, g)
		if got != counts[g] {
			t.Errorf("graph %s: triple count changed across a repeat seed load: %d -> %d", g, counts[g], got)
		}
	}

	probeQuery := fmt.Sprintf(`SELECT ?o WHERE { <%s> <%s> ?o }`, stagingSubject, stagingPredicate)
	probeResults, err := client.SelectRaw(ctx, probeQuery)
	if err != nil {
		t.Fatalf("SelectRaw for the staging probe: %v", err)
	}
	if len(probeResults.Results.Bindings) != 1 {
		t.Fatalf("pre-existing staging triple did not survive the seed reload: got %d bindings", len(probeResults.Results.Bindings))
	}
}
