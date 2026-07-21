package proposal_test

// Integration tests for proposal-lifecycle spec.md (task 3.6), guarded by
// requireGraphDB (testhelper_test.go): version bump, reject, edit, invalid
// transitions, and decision provenance.

import (
	"context"
	"errors"
	"fmt"
	"testing"

	"github.com/blogem/msr-graph/internal/graph"
	"github.com/blogem/msr-graph/internal/proposal"
)

// TestApprove_VersionBumpsMinorExactlyOnce pins "Version minor-bumps on
// approval": with owl:versionInfo at a known value, approving bumps it by
// exactly one minor (via proposal.BumpMinor) and leaves exactly one version
// literal.
func TestApprove_VersionBumpsMinorExactlyOnce(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()
	fx := seedSolubilityProposal(t, client)
	setOntologyVersion(t, client, "0.4.0")
	engine := proposal.NewEngine(client)

	if err := engine.Approve(ctx, fx.ID, testApproveRequest()); err != nil {
		t.Fatalf("Approve(%s): %v", fx.ID, err)
	}

	want, err := proposal.BumpMinor("0.4.0")
	if err != nil {
		t.Fatalf("proposal.BumpMinor(\"0.4.0\"): %v", err)
	}
	if got := ontologyVersion(t, client); got != want {
		t.Errorf("owl:versionInfo after approval = %q, want %q", got, want)
	}
	if n := countVersionLiterals(t, client); n != 1 {
		t.Errorf("owl:versionInfo literal count after approval = %d, want exactly 1", n)
	}
}

// TestApprove_ReapprovalDoesNotDoubleBumpVersion pins "The bump is not
// repeated on re-approval": approving an already-approved proposal again
// leaves owl:versionInfo unchanged.
func TestApprove_ReapprovalDoesNotDoubleBumpVersion(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()
	fx := seedSolubilityProposal(t, client)
	setOntologyVersion(t, client, "0.7.0")
	engine := proposal.NewEngine(client)

	if err := engine.Approve(ctx, fx.ID, testApproveRequest()); err != nil {
		t.Fatalf("first Approve(%s): %v", fx.ID, err)
	}
	afterFirst := ontologyVersion(t, client)
	if afterFirst == "0.7.0" {
		t.Fatalf("setup problem: Approve did not bump owl:versionInfo at all (still 0.7.0)")
	}

	if err := engine.Approve(ctx, fx.ID, testApproveRequest()); err != nil {
		t.Fatalf("second Approve(%s): %v", fx.ID, err)
	}
	afterSecond := ontologyVersion(t, client)

	if afterSecond != afterFirst {
		t.Errorf("owl:versionInfo changed on re-approval: %q -> %q, want unchanged (no second bump)", afterFirst, afterSecond)
	}
	if n := countVersionLiterals(t, client); n != 1 {
		t.Errorf("owl:versionInfo literal count after re-approval = %d, want exactly 1", n)
	}
}

// TestReject_LeavesCoreAndVersionUntouched pins "Reject leaves core and
// version untouched": rejecting a pending proposal flips status to
// rejected, adds nothing to any core graph, leaves owl:versionInfo alone,
// and keeps the proposal graph in place.
func TestReject_LeavesCoreAndVersionUntouched(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()
	fx := seedSolubilityProposal(t, client)
	setOntologyVersion(t, client, "0.6.0")
	engine := proposal.NewEngine(client)

	if err := engine.Reject(ctx, fx.ID); err != nil {
		t.Fatalf("Reject(%s): %v", fx.ID, err)
	}

	if got := reviewStatus(t, client, fx.ID); got != "rejected" {
		t.Errorf("msr:reviewStatus after Reject = %q, want %q", got, "rejected")
	}
	if rawGraphHasSubject(t, client, graph.Ontology, fx.PropertyIRI) {
		t.Errorf("expected %s NOT to be routed into %s after Reject", fx.PropertyIRI, graph.Ontology)
	}
	if rawGraphHasSubject(t, client, graph.Vocab, fx.ConceptIRI) {
		t.Errorf("expected %s NOT to be routed into %s after Reject", fx.ConceptIRI, graph.Vocab)
	}
	if got := ontologyVersion(t, client); got != "0.6.0" {
		t.Errorf("owl:versionInfo after Reject = %q, want unchanged %q", got, "0.6.0")
	}
	if countSubjectTriples(t, client, graph.ProposalGraph(fx.ID), fx.PropertyIRI) == 0 {
		t.Errorf("expected proposal graph %s to still contain %s after Reject", graph.ProposalGraph(fx.ID), fx.PropertyIRI)
	}
}

// TestEdit_PromotedTriplesReflectEditedContent pins "Edited triples are
// what get promoted": Edit replaces the proposal graph's triples, status
// stays pending, and a subsequent Approve promotes the edited content, not
// the pre-edit triples.
func TestEdit_PromotedTriplesReflectEditedContent(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()
	fx := seedSolubilityProposal(t, client)
	engine := proposal.NewEngine(client)

	suffix := uniqueSuffix()
	editedIRI := "https://w3id.org/msr-kg/ontology#edited-" + suffix
	editedTriples := fmt.Sprintf(
		"<%s> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <https://w3id.org/msr-kg/ontology#PhysicalProperty> .\n"+
			"<%s> <https://w3id.org/msr-kg/ontology#quantityKind> <http://qudt.org/vocab/quantitykind/MassConcentration> .\n"+
			"<%s> <https://w3id.org/msr-kg/ontology#canonicalUnit> <http://qudt.org/vocab/unit/GM-PER-L> .\n",
		editedIRI, editedIRI, editedIRI)

	if err := engine.Edit(ctx, fx.ID, editedTriples); err != nil {
		t.Fatalf("Edit(%s): %v", fx.ID, err)
	}

	if got := reviewStatus(t, client, fx.ID); got != "pending" {
		t.Errorf("msr:reviewStatus after Edit = %q, want %q (edit does not change status)", got, "pending")
	}
	if countSubjectTriples(t, client, graph.ProposalGraph(fx.ID), fx.PropertyIRI) != 0 {
		t.Errorf("expected Edit to replace the proposal graph's triples: pre-edit subject %s still present in %s", fx.PropertyIRI, graph.ProposalGraph(fx.ID))
	}

	if err := engine.Approve(ctx, fx.ID, testApproveRequest()); err != nil {
		t.Fatalf("Approve(%s) after Edit: %v", fx.ID, err)
	}

	if !coreGraphHasSubject(t, client, graph.Ontology, editedIRI) {
		t.Errorf("expected the edited subject %s to be promoted into %s", editedIRI, graph.Ontology)
	}
	if rawGraphHasSubject(t, client, graph.Ontology, fx.PropertyIRI) {
		t.Errorf("expected the pre-edit subject %s NOT to be promoted", fx.PropertyIRI)
	}
}

// TestReject_InvalidTransitionOnApprovedProposalIsRefused pins "Rejecting
// an approved proposal is refused": once approved, Reject returns
// proposal.ErrInvalidTransition and the proposal remains approved.
func TestReject_InvalidTransitionOnApprovedProposalIsRefused(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()
	fx := seedSolubilityProposal(t, client)
	engine := proposal.NewEngine(client)

	if err := engine.Approve(ctx, fx.ID, testApproveRequest()); err != nil {
		t.Fatalf("Approve(%s): %v", fx.ID, err)
	}

	err := engine.Reject(ctx, fx.ID)
	if !errors.Is(err, proposal.ErrInvalidTransition) {
		t.Fatalf("Reject on an approved proposal: err = %v, want errors.Is(err, proposal.ErrInvalidTransition)", err)
	}

	if got := reviewStatus(t, client, fx.ID); got != "approved" {
		t.Errorf("msr:reviewStatus after a refused Reject = %q, want unchanged %q", got, "approved")
	}
}

// TestApprove_UnknownIDReturnsErrNotFound is a light coverage check for
// proposal.ErrNotFound, which the pinned contract exports but no scenario
// in the spec artifacts individually names.
func TestApprove_UnknownIDReturnsErrNotFound(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()
	engine := proposal.NewEngine(client)

	id := "property-does-not-exist-" + uniqueSuffix()
	err := engine.Approve(ctx, id, testApproveRequest())
	if !errors.Is(err, proposal.ErrNotFound) {
		t.Fatalf("Approve(%s) on an unknown id: err = %v, want errors.Is(err, proposal.ErrNotFound)", id, err)
	}
}

// TestApprove_WritesReviewerAttributedProvenanceActivity pins "Approval
// writes a reviewer-attributed activity": approving with a supplied
// reviewer and timestamp writes a urn:msr:run:approve/{id} prov:Activity
// into urn:msr:staging, wasAssociatedWith the reviewer, linked (either
// direction) to the proposal resource, carrying the request-supplied
// startedAtTime, and urn:msr:provenance gains nothing about it.
func TestApprove_WritesReviewerAttributedProvenanceActivity(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()
	fx := seedSolubilityProposal(t, client)
	engine := proposal.NewEngine(client)

	req := proposal.ApproveRequest{
		Reviewer:  "reviewer-" + uniqueSuffix() + "@example.com",
		Timestamp: "2026-07-20T15:30:00Z",
	}
	if err := engine.Approve(ctx, fx.ID, req); err != nil {
		t.Fatalf("Approve(%s): %v", fx.ID, err)
	}

	activityIRI := "urn:msr:run:approve/" + fx.ID
	query := fmt.Sprintf(commonPrefixes+`
		SELECT ?agent ?ts WHERE {
			GRAPH <urn:msr:staging> {
				<%s> a prov:Activity ;
					prov:wasAssociatedWith ?agent ;
					prov:startedAtTime ?ts .
			}
		}`, activityIRI)
	results, err := client.SelectRaw(ctx, query)
	if err != nil {
		t.Fatalf("querying the decision activity %s: %v", activityIRI, err)
	}
	if len(results.Results.Bindings) != 1 {
		t.Fatalf("expected exactly one prov:Activity binding for %s in urn:msr:staging, got %d", activityIRI, len(results.Results.Bindings))
	}
	if got := results.Results.Bindings[0]["ts"].Value; got != req.Timestamp {
		t.Errorf("prov:startedAtTime = %q, want the request-supplied %q", got, req.Timestamp)
	}

	linkQuery := fmt.Sprintf(`
		SELECT ?p WHERE {
			GRAPH <urn:msr:staging> {
				{ <%[1]s> ?p <%[2]s> } UNION { <%[2]s> ?p <%[1]s> }
			}
		}`, activityIRI, changeProposalIRI(fx.ID))
	linkResults, err := client.SelectRaw(ctx, linkQuery)
	if err != nil {
		t.Fatalf("querying the activity<->proposal link: %v", err)
	}
	if len(linkResults.Results.Bindings) == 0 {
		t.Errorf("expected the decision activity %s to be linked (either direction) to the proposal %s in urn:msr:staging", activityIRI, changeProposalIRI(fx.ID))
	}

	if countSubjectTriples(t, client, graph.Provenance, activityIRI) != 0 {
		t.Errorf("expected urn:msr:provenance to gain nothing about the approval activity %s", activityIRI)
	}
}
