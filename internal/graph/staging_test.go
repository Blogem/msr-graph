package graph_test

// Integration tests 6.4 and 6.5, guarded by the D6 helper in
// testhelper_test.go (requireGraphDB). Require a live GraphDB with repo
// "msr"; skip (or fail, per GRAPHDB_REQUIRED) when it is absent.

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/blogem/msr-graph/internal/graph"
)

// TestStagingExcludedFromCoreReads pins core-dataset-access spec.md's
// "Staging is invisible to core reads" and "The same triple is visible raw"
// scenarios: a triple inserted into urn:msr:staging via client.Update must
// not appear via Select (the core-dataset client) but must appear via
// SelectRaw.
func TestStagingExcludedFromCoreReads(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()

	subject := fmt.Sprintf("urn:msr:test:staging-probe-%d", time.Now().UnixNano())
	const predicate = "urn:msr:test:predicate"
	const object = "sentinel-value"

	update := fmt.Sprintf(`INSERT DATA { GRAPH <urn:msr:staging> { <%s> <%s> "%s" . } }`, subject, predicate, object)
	if err := client.Update(ctx, update); err != nil {
		t.Fatalf("inserting staging probe triple: %v", err)
	}

	query := fmt.Sprintf(`SELECT ?o WHERE { <%s> <%s> ?o }`, subject, predicate)

	coreResults, err := client.Select(ctx, query)
	if err != nil {
		t.Fatalf("Select: %v", err)
	}
	if got := len(coreResults.Results.Bindings); got != 0 {
		t.Errorf("Select (core dataset) found %d bindings for a staging-only triple, want 0", got)
	}

	rawResults, err := client.SelectRaw(ctx, query)
	if err != nil {
		t.Fatalf("SelectRaw: %v", err)
	}
	if got := len(rawResults.Results.Bindings); got != 1 {
		t.Fatalf("SelectRaw found %d bindings for the staging probe triple, want 1", got)
	}
	if got := rawResults.Results.Bindings[0]["o"].Value; got != object {
		t.Errorf("SelectRaw returned object %q, want %q", got, object)
	}
}

// TestGraphPatternWithinCoreSet pins the "GRAPH patterns work within the
// core set" scenario: named-graph set == default-graph set, so a GRAPH ?g
// pattern over a term known to live in urn:msr:vocab must bind ?g to
// urn:msr:vocab rather than silently matching nothing.
//
// The fact re-asserted here is the real seed triple from ontology/vocab.ttl
// (voc:flibe skos:prefLabel "FLiBe"@en). INSERT DATA has RDF set semantics,
// so re-asserting it is a no-op whether or not `make load-seed` has already
// run -- this test does not depend on load-seed ordering.
func TestGraphPatternWithinCoreSet(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()

	const flibeIRI = "https://w3id.org/msr-kg/vocab#flibe"
	assertFact := fmt.Sprintf(`
		PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
		INSERT DATA { GRAPH <%s> { <%s> skos:prefLabel "FLiBe"@en . } }
	`, graph.Vocab, flibeIRI)
	if err := client.Update(ctx, assertFact); err != nil {
		t.Fatalf("asserting the vocab probe fact: %v", err)
	}

	query := fmt.Sprintf(`
		PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
		SELECT ?g ?label WHERE {
			GRAPH ?g { <%s> skos:prefLabel ?label . }
		}
	`, flibeIRI)

	results, err := client.Select(ctx, query)
	if err != nil {
		t.Fatalf("Select: %v", err)
	}

	found := false
	for _, b := range results.Results.Bindings {
		if b["g"].Value == string(graph.Vocab) {
			found = true
			if b["label"].Value != "FLiBe" {
				t.Errorf("bound label = %q, want %q", b["label"].Value, "FLiBe")
			}
		}
	}
	if !found {
		t.Errorf("expected a result binding ?g to %s, got bindings: %+v", graph.Vocab, results.Results.Bindings)
	}
}
