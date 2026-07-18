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

// TestSeedLoadExposesFlibeMeasurement pins seed-graph-loading spec.md's
// "Seed data queryable after load" scenario using the concrete FLiBe
// example from ontology/example-flibe.ttl:
// msrd:m-nist-srd27-density-BeF2-LiF-66.0-34.0, a msr:PropertyMeasurement
// with msr:dataLocator "nist-srd27/density#BeF2-LiF|66.0-34.0".
func TestSeedLoadExposesFlibeMeasurement(t *testing.T) {
	client := requireGraphDB(t)
	runLoaderSeed(t, graphDBBaseURL())

	const measurementIRI = "https://w3id.org/msr-kg/data#m-nist-srd27-density-BeF2-LiF-66.0-34.0"
	const wantLocator = "nist-srd27/density#BeF2-LiF|66.0-34.0"

	query := fmt.Sprintf(`
		PREFIX msr: <https://w3id.org/msr-kg/ontology#>
		SELECT ?locator WHERE {
			<%s> a msr:PropertyMeasurement ;
				msr:dataLocator ?locator .
		}
	`, measurementIRI)

	results, err := client.Select(context.Background(), query)
	if err != nil {
		t.Fatalf("Select: %v", err)
	}
	if len(results.Results.Bindings) != 1 {
		t.Fatalf("expected exactly one PropertyMeasurement binding for the FLiBe example, got %d", len(results.Results.Bindings))
	}
	if got := results.Results.Bindings[0]["locator"].Value; got != wantLocator {
		t.Errorf("dataLocator = %q, want %q", got, wantLocator)
	}
}

// TestSeedLoadIsIdempotent pins seed-graph-loading spec.md's "Double load
// changes nothing" and "Existing staging content preserved" scenarios:
// running the seed load twice yields identical per-graph triple counts, and
// a pre-existing urn:msr:staging triple survives both runs.
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
