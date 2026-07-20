package proposal_test

// TestEdit_RejectsSPARQLBreakoutPayload is the regression test for the
// confirmed SPARQL-injection finding on Engine.Edit: the previous
// implementation spliced the caller-supplied triples string verbatim
// into "INSERT DATA { GRAPH <..> { " + triples + " } }", so a triples
// value containing its own "} }" plus a trailing SPARQL Update command
// (e.g. "CLEAR ALL") would close the INSERT block early and run
// arbitrary SPARQL in the same request -- a single unauthenticated
// PUT /api/proposals/{id}/graph could wipe the entire repository.
//
// Edit now sends triples as the raw HTTP request body of a Graph Store
// Protocol PUT (graph.Client.PutProposalGraph), which GraphDB always
// parses as Turtle/RDF, never as SPARQL syntax -- so "CLEAR ALL" text
// inside the body can never execute as a command through this endpoint,
// regardless of whether the document happens to parse as valid Turtle.
// This test proves both halves: the breakout payload does not parse as
// Turtle (Edit returns an error) and, decisively, a sentinel triple
// seeded into a completely different named graph (urn:msr:vocab) is
// still present afterward -- proving no CLEAR ALL (or any other command)
// ran anywhere in the store.

import (
	"context"
	"fmt"
	"testing"

	"github.com/blogem/msr-graph/internal/graph"
	"github.com/blogem/msr-graph/internal/proposal"
)

func TestEdit_RejectsSPARQLBreakoutPayload(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()
	engine := proposal.NewEngine(client)

	suffix := uniqueSuffix()
	sentinelIRI := "https://w3id.org/msr-kg/vocab#edit-injection-sentinel-" + suffix
	seedSentinel := fmt.Sprintf(
		`INSERT DATA { GRAPH <%s> { <%s> <urn:msr:test:predicate> "sentinel" . } }`,
		graph.Vocab, sentinelIRI,
	)
	if err := client.Update(ctx, seedSentinel); err != nil {
		t.Fatalf("seeding sentinel triple in %s: %v", graph.Vocab, err)
	}
	t.Cleanup(func() {
		cleanup := fmt.Sprintf(
			`DELETE WHERE { GRAPH <%s> { <%s> <urn:msr:test:predicate> "sentinel" . } }`,
			graph.Vocab, sentinelIRI,
		)
		if err := client.Update(context.Background(), cleanup); err != nil {
			t.Logf("cleanup: removing sentinel triple %s: %v", sentinelIRI, err)
		}
	})

	if !rawGraphHasSubject(t, client, graph.Vocab, sentinelIRI) {
		t.Fatalf("sentinel triple %s not visible in %s right after seeding it", sentinelIRI, graph.Vocab)
	}

	id := "property-edit-injection-" + suffix
	breakout := "<a> <b> <c> .\n} } ;\nCLEAR ALL ;\nINSERT DATA { GRAPH <urn:msr:proposal/x> { <a> <b> <c>"

	if err := engine.Edit(ctx, id, breakout); err == nil {
		t.Error("expected Edit to return an error for a non-Turtle SPARQL-breakout payload, got nil")
	}

	if !rawGraphHasSubject(t, client, graph.Vocab, sentinelIRI) {
		t.Fatal("sentinel triple no longer present after the breakout Edit attempt -- CLEAR ALL (or similar) executed")
	}
}
