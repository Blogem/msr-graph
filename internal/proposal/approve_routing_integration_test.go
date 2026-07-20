package proposal_test

// Integration tests for approval-typed-routing spec.md (task 2.5), guarded
// by requireGraphDB (testhelper_test.go). Each test seeds its own
// unique-per-run fixture proposal (fixture_test.go) and drives it through
// proposal.NewEngine(requireGraphDB(t)).

import (
	"context"
	"testing"

	"github.com/blogem/msr-graph/internal/graph"
	"github.com/blogem/msr-graph/internal/proposal"
)

// TestApprove_SolubilityRoutesToOntologyAndVocab pins "A property proposal
// routes to ontology and vocab": the msr:PhysicalProperty individual (with
// quantityKind/canonicalUnit) lands in urn:msr:ontology and the skos:Concept
// lands in urn:msr:vocab, both visible through the core-dataset Select, and
// urn:msr:data gains neither.
func TestApprove_SolubilityRoutesToOntologyAndVocab(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()
	fx := seedSolubilityProposal(t, client)
	engine := proposal.NewEngine(client)

	if err := engine.Approve(ctx, fx.ID, testApproveRequest()); err != nil {
		t.Fatalf("Approve(%s): %v", fx.ID, err)
	}

	if !coreGraphHasSubject(t, client, graph.Ontology, fx.PropertyIRI) {
		t.Errorf("expected %s to be visible in %s via the core client after approval", fx.PropertyIRI, graph.Ontology)
	}
	if !coreGraphHasSubject(t, client, graph.Vocab, fx.ConceptIRI) {
		t.Errorf("expected %s to be visible in %s via the core client after approval", fx.ConceptIRI, graph.Vocab)
	}
	if rawGraphHasSubject(t, client, graph.Data, fx.PropertyIRI) {
		t.Errorf("expected the TBox property %s NOT to be routed into %s", fx.PropertyIRI, graph.Data)
	}
	if rawGraphHasSubject(t, client, graph.Data, fx.ConceptIRI) {
		t.Errorf("expected the SKOS concept %s NOT to be routed into %s", fx.ConceptIRI, graph.Data)
	}
}

// TestApprove_MixedGraphiteBundleRoutesEachTripleByType pins "A mixed class
// bundle routes each triple by type": the owl:Class and owl:ObjectProperty
// land in urn:msr:ontology while the individual they type lands in
// urn:msr:data, ignoring the proposal's single msr:kind "class".
func TestApprove_MixedGraphiteBundleRoutesEachTripleByType(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()
	fx := seedGraphiteProposal(t, client)
	engine := proposal.NewEngine(client)

	if err := engine.Approve(ctx, fx.ID, testApproveRequest()); err != nil {
		t.Fatalf("Approve(%s): %v", fx.ID, err)
	}

	if !coreGraphHasSubject(t, client, graph.Ontology, fx.ClassIRI) {
		t.Errorf("expected class %s in %s after approval", fx.ClassIRI, graph.Ontology)
	}
	if !coreGraphHasSubject(t, client, graph.Ontology, fx.PropertyIRI) {
		t.Errorf("expected object property %s in %s after approval", fx.PropertyIRI, graph.Ontology)
	}
	if !coreGraphHasSubject(t, client, graph.Data, fx.IndividualIRI) {
		t.Errorf("expected individual %s in %s after approval", fx.IndividualIRI, graph.Data)
	}
	if rawGraphHasSubject(t, client, graph.Ontology, fx.IndividualIRI) {
		t.Errorf("expected individual %s NOT to be routed into %s", fx.IndividualIRI, graph.Ontology)
	}
	if rawGraphHasSubject(t, client, graph.Data, fx.ClassIRI) {
		t.Errorf("expected class %s NOT to be routed into %s", fx.ClassIRI, graph.Data)
	}
}

// TestApprove_ProposalGraphRetainedAsAuditRecord pins "Proposal graph
// survives approval": the urn:msr:proposal/{id} graph still contains the
// original proposed triples after approval, unmodified by the copy-out.
func TestApprove_ProposalGraphRetainedAsAuditRecord(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()
	fx := seedSolubilityProposal(t, client)
	engine := proposal.NewEngine(client)

	beforeCount := countSubjectTriples(t, client, graph.ProposalGraph(fx.ID), fx.PropertyIRI)
	if beforeCount == 0 {
		t.Fatalf("fixture setup problem: proposal graph %s does not contain %s before approval", graph.ProposalGraph(fx.ID), fx.PropertyIRI)
	}

	if err := engine.Approve(ctx, fx.ID, testApproveRequest()); err != nil {
		t.Fatalf("Approve(%s): %v", fx.ID, err)
	}

	afterCount := countSubjectTriples(t, client, graph.ProposalGraph(fx.ID), fx.PropertyIRI)
	if afterCount != beforeCount {
		t.Errorf("proposal graph %s triple count for %s changed across approval: %d -> %d, want unchanged (audit record retained)",
			graph.ProposalGraph(fx.ID), fx.PropertyIRI, beforeCount, afterCount)
	}
}

// TestApprove_SecondApprovalAddsNoDuplicateCoreTriples pins "Second
// approval adds no duplicate core triples": approving an already-approved
// proposal again leaves the core graphs' triple counts for the routed
// subject unchanged.
func TestApprove_SecondApprovalAddsNoDuplicateCoreTriples(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()
	fx := seedSolubilityProposal(t, client)
	engine := proposal.NewEngine(client)

	if err := engine.Approve(ctx, fx.ID, testApproveRequest()); err != nil {
		t.Fatalf("first Approve(%s): %v", fx.ID, err)
	}
	firstCount := countSubjectTriples(t, client, graph.Ontology, fx.PropertyIRI)
	if firstCount == 0 {
		t.Fatalf("setup problem: %s not present in %s after the first approval", fx.PropertyIRI, graph.Ontology)
	}

	if err := engine.Approve(ctx, fx.ID, testApproveRequest()); err != nil {
		t.Fatalf("second Approve(%s) on an already-approved proposal: %v", fx.ID, err)
	}
	secondCount := countSubjectTriples(t, client, graph.Ontology, fx.PropertyIRI)

	if secondCount != firstCount {
		t.Errorf("%s triple count in %s changed on re-approval: %d -> %d, want unchanged (no duplicates)",
			fx.PropertyIRI, graph.Ontology, firstCount, secondCount)
	}
}
