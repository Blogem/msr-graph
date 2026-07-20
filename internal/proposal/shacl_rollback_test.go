package proposal_test

// TestApprove_SHACLValidationErrorPassesThroughAndProposalStaysPending pins
// task 2.4's real requirement -- "Surface a GraphDB SHACL rejection as the
// existing typed ValidationError ... leaving the proposal pending" -- and
// approval-typed-routing spec.md's "SHACL rejection rolls back the whole
// promotion" scenario, at the unit level against a fake proposal.GraphClient
// rather than a live GraphDB.
//
// Why not an integration test: a genuinely SHACL-violating bundle cannot be
// *staged* in the first place against the live dockerized GraphDB, because
// the ShaclSail validates writes to every graph, including
// urn:msr:proposal/{id} -- so seeding an invalid fixture proposal fails at
// setup time (the client.Update call that stages it), never reaching
// Approve. "Approve routes a violating triple and the sail rejects the
// combined UPDATE" is therefore a can't-happen path against the live sail,
// and is instead pinned here as a fake-client unit test that exercises the
// engine's own error classification/pass-through logic directly: the fake's
// Update call returns a *graph.ValidationError (constructed directly via
// its exported fields, exactly as GraphDB's real rejection response would
// be classified into one by graph.Client.Update), and this test asserts
// Approve surfaces it unchanged via errors.As, with no partial mutation --
// the single-transaction design (design D1) means there is no separate
// status-flip write to undo, so "no partial mutation" is asserted here as
// "exactly one Update call was made, and it was the one that failed."

import (
	"context"
	"errors"
	"testing"

	"github.com/blogem/msr-graph/internal/graph"
	"github.com/blogem/msr-graph/internal/proposal"
)

// fakeApproveClient is a minimal proposal.GraphClient double: SelectRaw
// always reports the fixture proposal as "pending" (so Approve's status
// guard passes), Select always reports the ontology header at "0.4.0" (so
// the version read/bump computation succeeds), and Update always fails as
// GraphDB's ShaclSail would for a violating combined UPDATE, recording
// every call it received so the test can assert exactly one was made.
type fakeApproveClient struct {
	updateCalls []string
}

func newFakeResults(bindings ...map[string]graph.Binding) *graph.Results {
	r := &graph.Results{}
	r.Results.Bindings = bindings
	return r
}

func (f *fakeApproveClient) Select(_ context.Context, _ string) (*graph.Results, error) {
	return newFakeResults(map[string]graph.Binding{
		"v": {Type: "literal", Value: "0.4.0"},
	}), nil
}

func (f *fakeApproveClient) SelectRaw(_ context.Context, _ string) (*graph.Results, error) {
	return newFakeResults(map[string]graph.Binding{
		"status": {Type: "literal", Value: "pending"},
	}), nil
}

func (f *fakeApproveClient) Update(_ context.Context, update string) error {
	f.updateCalls = append(f.updateCalls, update)
	return &graph.ValidationError{
		Report: `@prefix sh: <http://www.w3.org/ns/shacl#> .
[] a sh:ValidationReport ;
	sh:conforms false ;
	sh:result [
		a sh:ValidationResult ;
		sh:focusNode <https://w3id.org/msr-kg/data#test-measurement-shacl-rollback> ;
		sh:sourceConstraintComponent sh:MinCountConstraintComponent ;
		sh:resultMessage "Less than 1 values on msr:forProperty" ;
	] .`,
		Violations: []graph.Violation{
			{
				FocusNode:                 "https://w3id.org/msr-kg/data#test-measurement-shacl-rollback",
				SourceConstraintComponent: "sh:MinCountConstraintComponent",
				Message:                   "Less than 1 values on msr:forProperty",
			},
		},
	}
}

func TestApprove_SHACLValidationErrorPassesThroughAndProposalStaysPending(t *testing.T) {
	client := &fakeApproveClient{}
	engine := proposal.NewEngine(client)

	err := engine.Approve(context.Background(), "instance-badmeasurement-fake", testApproveRequest())
	if err == nil {
		t.Fatal("expected Approve to return an error when the combined UPDATE is rejected by SHACL, got nil")
	}

	var ve *graph.ValidationError
	if !errors.As(err, &ve) {
		t.Fatalf("expected errors.As to find a *graph.ValidationError in the Approve error chain, got: %v", err)
	}
	if len(ve.Violations) != 1 || ve.Violations[0].FocusNode != "https://w3id.org/msr-kg/data#test-measurement-shacl-rollback" {
		t.Errorf("ValidationError.Violations = %+v, want the fake's single MinCount violation to pass through unchanged", ve.Violations)
	}

	if len(client.updateCalls) != 1 {
		t.Fatalf("expected exactly one Update call (the single combined transaction, design D1), got %d: %v", len(client.updateCalls), client.updateCalls)
	}
}
