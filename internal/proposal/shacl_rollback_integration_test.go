package proposal_test

// TestApprove_SHACLRejectionRollsBackWholePromotion pins
// approval-typed-routing spec.md's "SHACL rejection rolls back the whole
// promotion" scenario (task 2.5), on a best-effort basis per the task
// brief: it relies on deploy/graphdb/msr-shapes.ttl's
// msr:PropertyMeasurementShape (from the shacl-validation change, task
// 2.1), which requires (minCount 1 each) prov:wasDerivedFrom,
// prov:wasGeneratedBy, msr:dataLocator, msr:forProperty, msr:ofSalt,
// msr:hasUnit, and msr:equationForm on every msr:PropertyMeasurement
// individual (deploy/graphdb/msr-shapes.ttl lines 44-88). The fixture
// bundle (seedBadMeasurementProposal, fixture_test.go) asserts a bare
// `a msr:PropertyMeasurement` typing with NONE of those seven properties,
// so the shape rejects it on all seven MinCount constraints at once.
//
// Being an individual (not a TBox axiom or SKOS concept), the routing
// classifier sends it to urn:msr:data per design D1 -- so the violation is
// surfaced only once GraphDB validates the single combined UPDATE that also
// carries the version bump / status flip / provenance insert, proving the
// whole promotion rolls back atomically rather than partially committing.
//
// If msr:PropertyMeasurementShape's required-property set changes upstream
// (deploy/graphdb/msr-shapes.ttl), this test needs revisiting alongside it
// -- documented here rather than silently going green on a fixture that no
// longer violates anything.

import (
	"context"
	"errors"
	"testing"

	"github.com/blogem/msr-graph/internal/graph"
	"github.com/blogem/msr-graph/internal/proposal"
)

func TestApprove_SHACLRejectionRollsBackWholePromotion(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()
	id, measurementIRI := seedBadMeasurementProposal(t, client)
	engine := proposal.NewEngine(client)

	err := engine.Approve(ctx, id, testApproveRequest())
	if err == nil {
		t.Fatal("expected Approve to fail for a bundle that violates msr:PropertyMeasurementShape, got nil error")
	}

	var ve *graph.ValidationError
	if !errors.As(err, &ve) {
		t.Fatalf("expected errors.As to find a *graph.ValidationError in the Approve error chain, got: %v", err)
	}

	if rawGraphHasSubject(t, client, graph.Data, measurementIRI) {
		t.Errorf("expected %s NOT to appear in %s after a rolled-back approval", measurementIRI, graph.Data)
	}
	if got := reviewStatus(t, client, id); got != "pending" {
		t.Errorf("msr:reviewStatus after a rolled-back approval = %q, want unchanged %q", got, "pending")
	}
}
