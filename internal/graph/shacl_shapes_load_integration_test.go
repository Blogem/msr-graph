package graph_test

// Task 7.6: opt-in GraphDB integration test for "shapes-graph load
// installs the catalogue into the reserved graph and is idempotent on
// re-run" (spec.md "Bootstrap installs the shapes" / "Shapes are a
// versioned artifact", design D2).
//
// design.md D2 notes the real bootstrap load is a `curl` PUT inside
// scripts/ensure-repo.sh (Graph Store Protocol PUT, replace semantics)
// targeting the RDF4J reserved shapes graph
// (http://rdf4j.org/schema/rdf4j#SHACLShapeGraph), followed by a POST of
// the generated unit-allowlist fragment (append semantics) -- mirrored
// here via putShapesGraph/postShapesGraph.
//
// PASS-2 CORRECTION (verified live against GraphDB 11.4.2, sail-type
// rdf4j:ShaclSail): the ShaclSail wrapper INTERNALIZES shapes written to
// the reserved shapes graph into its own private shapes cache -- they are
// NOT retained as queryable triples in that named graph. A
// `SELECT (COUNT(*)) WHERE { GRAPH <reserved> {?s ?p ?o} }` against a
// SHACL-enabled repo reliably returns 0 triples even immediately after a
// successful PUT, because ShaclSail consumes/internalizes the graph's
// contents rather than storing them as ordinary retrievable data. A
// triple-count assertion on that graph is therefore not a valid way to
// observe "did the load install the shapes" on this GraphDB version --
// DO NOT reintroduce a count-based assertion here. The functional
// alternative used below (does an invalid write get rejected / a valid
// write get accepted) is the only reliable observable for "are the shapes
// active."
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

// graphStoreProtocolRequest issues a Graph Store Protocol request (PUT or
// POST) against the reserved shapes graph, exactly the mechanism design D2
// specifies for ensure-repo.sh's own load step (PUT replace semantics for
// the hand-authored shapes, POST append semantics for the generated unit
// fragment -- mirrored here to stay aligned with the real script).
func graphStoreProtocolRequest(t *testing.T, ctx context.Context, method, baseURL string, ttl []byte) {
	t.Helper()
	params := url.Values{}
	params.Set("graph", shaclShapesGraphIRI)
	endpoint := fmt.Sprintf("%s/repositories/msr/rdf-graphs/service?%s", baseURL, params.Encode())

	req, err := http.NewRequestWithContext(ctx, method, endpoint, bytes.NewReader(ttl))
	if err != nil {
		t.Fatalf("building %s request for the reserved shapes graph: %v", method, err)
	}
	req.Header.Set("Content-Type", "text/turtle")

	resp, err := (&http.Client{Timeout: 30 * time.Second}).Do(req)
	if err != nil {
		t.Fatalf("%s to the reserved shapes graph: %v", method, err)
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		t.Fatalf("%s to the reserved shapes graph failed: %s: %s", method, resp.Status, bytes.TrimSpace(body))
	}
}

// putShapesGraph PUTs ttl into the reserved shapes graph (replace
// semantics), mirroring ensure-repo.sh's load of the hand-authored shapes
// file(s).
func putShapesGraph(t *testing.T, ctx context.Context, baseURL string, ttl []byte) {
	t.Helper()
	graphStoreProtocolRequest(t, ctx, http.MethodPut, baseURL, ttl)
}

// postShapesGraph POSTs ttl into the reserved shapes graph (append
// semantics), mirroring ensure-repo.sh's load of the generated
// unit-allowlist fragment immediately after the PUT.
func postShapesGraph(t *testing.T, ctx context.Context, baseURL string, ttl []byte) {
	t.Helper()
	graphStoreProtocolRequest(t, ctx, http.MethodPost, baseURL, ttl)
}

// assertShapesActive proves the shape catalogue is actually enforcing
// constraints (the only reliable observable on a ShaclSail repo, per the
// file-level note above): a msr:PropertyMeasurement missing a required
// property is rejected, and a complete one is accepted. Reuses the same
// measurement fixtures shacl_measurement_integration_test.go (task 7.1)
// exercises against the measurement-completeness shape specifically.
func assertShapesActive(t *testing.T, client *graph.Client, label string) {
	t.Helper()

	incompleteID := uniqueLocal(label + "-incomplete")
	incomplete := completeMeasurementFields(incompleteID)
	incomplete.hasUnit = "" // drop one required property
	err := insertData(t, client, incomplete.triples(incompleteID))
	assertRejected(t, err, label+": incomplete PropertyMeasurement (missing msr:hasUnit)")

	completeID := uniqueLocal(label + "-complete")
	complete := completeMeasurementFields(completeID)
	completeTriples := complete.triples(completeID)
	err = insertData(t, client, completeTriples)
	assertAccepted(t, err, label+": complete PropertyMeasurement")
	t.Cleanup(func() { deleteData(t, client, completeTriples) })
}

// TestShapesGraphLoad_InstallsAndIsIdempotent pins spec.md's "Bootstrap
// installs the shapes" and "Shapes are a versioned artifact" scenarios
// (task 7.6): loading the shape catalogue into the reserved shapes graph
// (PUT the hand-authored shapes, then POST the generated unit fragment,
// mirroring ensure-repo.sh) makes the shapes ACTIVE (a known-invalid write
// is rejected, a valid one is accepted), and re-running the same
// PUT-then-POST sequence (replace-then-append semantics) leaves that same
// reject/accept behavior intact -- idempotent re-load, not a
// disappearance or duplicate-to-breakage of the installed shapes.
//
// This does NOT count triples in the reserved shapes graph (see the
// file-level PASS-2 CORRECTION note above for why that is unreliable on
// ShaclSail).
func TestShapesGraphLoad_InstallsAndIsIdempotent(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()
	baseURL := graphDBBaseURL()
	root := repoRoot(t)

	shapesTTL := loadShapesCatalogueTTL(t, root)
	unitsTTL, err := os.ReadFile(filepath.Join(root, "deploy", "graphdb", "msr-shapes-units.ttl"))
	if err != nil {
		t.Fatalf("reading generated unit-allowlist fragment: %v", err)
	}

	putShapesGraph(t, ctx, baseURL, shapesTTL)
	postShapesGraph(t, ctx, baseURL, unitsTTL)
	assertShapesActive(t, client, "first-load")

	// Re-run the same PUT-then-POST sequence: replace semantics on the PUT
	// means the hand-authored shapes are wholesale replaced (not
	// duplicated), and the POST re-appends the same unit fragment. The
	// shapes must still be active afterward, proving the reload neither
	// dropped the catalogue nor broke it via duplication.
	putShapesGraph(t, ctx, baseURL, shapesTTL)
	postShapesGraph(t, ctx, baseURL, unitsTTL)
	assertShapesActive(t, client, "second-load")
}
