package graph_test

// Task 7.6: opt-in GraphDB integration test for "shapes-graph load
// installs the catalogue into the reserved graph and is idempotent on
// re-run" (spec.md "Bootstrap installs the shapes" / "Shapes are a
// versioned artifact", design D2).
//
// design.md D2 notes the real bootstrap load is a `curl` PUT inside
// scripts/ensure-repo.sh (Graph Store Protocol PUT, replace semantics)
// targeting the RDF4J reserved shapes graph
// (http://rdf4j.org/schema/rdf4j#SHACLShapeGraph) -- "this bootstrap load
// is curl in ensure-repo.sh, so it is not subject to the Go
// Client.PutGraph known-graph guard." This test therefore does not use
// graph.Client.PutGraph (which refuses unknown graph IRIs by design) and
// instead performs the same PUT directly via net/http, mirroring
// ensure-repo.sh's own approach, then reads the graph back via
// client.SelectRaw (which has no dataset restriction).
//
// The shape catalogue's exact file layout is not fully pinned as of this
// test's authoring (design D3 allows the unit-allowlist fragment to be
// either folded into msr-shapes.ttl or loaded as a "companion fragment
// alongside it"). To stay correct either way, this test globs and
// concatenates every deploy/graphdb/msr-shapes*.ttl file before the PUT,
// so the "installs the catalogue" assertion covers whatever combination
// of files the coder lands.

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"testing"
	"time"

	"github.com/blogem/msr-graph/internal/graph"
)

// shaclShapesGraphIRI is the RDF4J reserved shapes graph (design D1/D2).
const shaclShapesGraphIRI = "http://rdf4j.org/schema/rdf4j#SHACLShapeGraph"

// loadShapesCatalogueTTL globs and concatenates every
// deploy/graphdb/msr-shapes*.ttl file in the repo, per the file-layout
// note above. Fails the test if none are found (the catalogue has not
// been authored yet in this worktree).
func loadShapesCatalogueTTL(t *testing.T, root string) []byte {
	t.Helper()
	pattern := filepath.Join(root, "deploy", "graphdb", "msr-shapes*.ttl")
	files, err := filepath.Glob(pattern)
	if err != nil {
		t.Fatalf("globbing %s: %v", pattern, err)
	}
	if len(files) == 0 {
		t.Fatalf("no files matched %s -- design D2/D3's shape catalogue artifact(s) not present yet", pattern)
	}
	sort.Strings(files)

	var buf bytes.Buffer
	for _, f := range files {
		data, err := os.ReadFile(f)
		if err != nil {
			t.Fatalf("reading %s: %v", f, err)
		}
		buf.Write(data)
		buf.WriteString("\n")
	}
	return buf.Bytes()
}

// putShapesGraph PUTs ttl into the reserved shapes graph via the Graph
// Store Protocol, exactly the mechanism design D2 specifies for
// ensure-repo.sh's own load step (replace semantics -- a second PUT with
// the same content is idempotent).
func putShapesGraph(t *testing.T, ctx context.Context, baseURL string, ttl []byte) {
	t.Helper()
	params := url.Values{}
	params.Set("graph", shaclShapesGraphIRI)
	endpoint := fmt.Sprintf("%s/repositories/msr/rdf-graphs/service?%s", baseURL, params.Encode())

	req, err := http.NewRequestWithContext(ctx, http.MethodPut, endpoint, bytes.NewReader(ttl))
	if err != nil {
		t.Fatalf("building PUT request for the reserved shapes graph: %v", err)
	}
	req.Header.Set("Content-Type", "text/turtle")

	resp, err := (&http.Client{Timeout: 30 * time.Second}).Do(req)
	if err != nil {
		t.Fatalf("PUT to the reserved shapes graph: %v", err)
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		t.Fatalf("PUT to the reserved shapes graph failed: %s: %s", resp.Status, bytes.TrimSpace(body))
	}
}

// countShapesGraphTriples mirrors seed_integration_test.go's
// countGraphTriples but for the reserved shapes graph IRI, which is not a
// graph.GraphIRI constant (it is RDF4J-internal, not one of this
// deployment's named graphs), so it queries via client.SelectRaw with an
// explicit GRAPH clause rather than reusing countGraphTriples directly.
func countShapesGraphTriples(t *testing.T, client *graph.Client, ctx context.Context) int {
	t.Helper()
	query := fmt.Sprintf(`SELECT (COUNT(*) AS ?count) WHERE { GRAPH <%s> { ?s ?p ?o } }`, shaclShapesGraphIRI)
	results, err := client.SelectRaw(ctx, query)
	if err != nil {
		t.Fatalf("counting triples in the reserved shapes graph: %v", err)
	}
	if len(results.Results.Bindings) != 1 {
		t.Fatalf("expected exactly one COUNT(*) binding for the shapes graph, got %d", len(results.Results.Bindings))
	}
	n, err := strconv.Atoi(results.Results.Bindings[0]["count"].Value)
	if err != nil {
		t.Fatalf("parsing shapes-graph triple count: %v", err)
	}
	return n
}

// TestShapesGraphLoad_InstallsAndIsIdempotent pins spec.md's "Bootstrap
// installs the shapes" and "Shapes are a versioned artifact" scenarios
// (task 7.6): PUT-ing the shape catalogue into the reserved shapes graph
// installs it (non-zero triple count), and re-running the same PUT
// (replace semantics) leaves the graph's triple count unchanged --
// idempotent re-load, not an accumulation.
func TestShapesGraphLoad_InstallsAndIsIdempotent(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()
	baseURL := graphDBBaseURL()
	root := repoRoot(t)

	shapesTTL := loadShapesCatalogueTTL(t, root)

	putShapesGraph(t, ctx, baseURL, shapesTTL)
	firstCount := countShapesGraphTriples(t, client, ctx)
	if firstCount == 0 {
		t.Fatalf("reserved shapes graph is empty after loading the shape catalogue -- expected its triples to be installed")
	}

	putShapesGraph(t, ctx, baseURL, shapesTTL)
	secondCount := countShapesGraphTriples(t, client, ctx)

	if secondCount != firstCount {
		t.Errorf("reserved shapes graph triple count changed across a repeat PUT load: %d -> %d, want an idempotent replace (identical count)", firstCount, secondCount)
	}
}
