package checkpoint_test

// TestCheckpointRoundTrip_ApproveThenRestoreReverts pins
// store-checkpoint-restore spec.md's headline "Approve then restore
// reverts everything" and "The demo can be re-run after restore" scenarios
// (task 4.4): checkpoint -> approve (routes triples, bumps version,
// mutates the live SQLite store) -> restore must return the graph triple
// counts, the ontology version, the proposal's status, and the SQLite
// content to the pre-checkpoint state; a subsequent re-approval must
// reproduce the first approval's result.
//
// KNOWN CROSS-PACKAGE RISK (flagged for the orchestrator, not fixed here --
// it is a test-infrastructure concern outside internal/checkpoint's allowed
// paths): Restore performs a full-repository ClearRepo + ImportRepo against
// the shared "msr" integration repo (design D4). `go test ./...` runs
// different packages' test binaries concurrently by default (this repo's
// Makefile does not pin -p 1), so if internal/graph's or
// internal/proposal's integration tests are mid-flight against the same
// live GraphDB when this test's Restore runs, they may transiently observe
// an emptied/rolled-back repository. Recommended mitigation: run this
// package's integration tests with `go test -p 1` alongside the others, or
// point the checkpoint suite at a dedicated GraphDB repo.

import (
	"context"
	"testing"

	"github.com/blogem/msr-graph/internal/checkpoint"
	"github.com/blogem/msr-graph/internal/graph"
	"github.com/blogem/msr-graph/internal/proposal"
)

func TestCheckpointRoundTrip_ApproveThenRestoreReverts(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()
	dbPath, locator := newTestSQLiteDB(t)
	root := t.TempDir()
	label := "roundtrip-" + uniqueSuffix()

	id, propertyIRI, conceptIRI := seedSolubilityFixtureForRoundTrip(t, client)

	preOntologyCount := countGraphTriples(t, client, graph.Ontology)
	preVocabCount := countGraphTriples(t, client, graph.Vocab)
	preDataCount := countGraphTriples(t, client, graph.Data)
	preStagingCount := countGraphTriples(t, client, graph.Staging)
	preVersion := ontologyVersion(t, client)

	cpEngine := checkpoint.NewEngine(client, dbPath, root)
	if _, err := cpEngine.Create(ctx, label); err != nil {
		t.Fatalf("Create(%s): %v", label, err)
	}

	// Drift the live SQLite store after the checkpoint, so restoring it is
	// actually exercised (not merely a no-op because nothing changed).
	mutateMeasurementC0(t, dbPath, locator, 99.9)

	propEngine := proposal.NewEngine(client)
	approveReq := proposal.ApproveRequest{Reviewer: "roundtrip-tester", Timestamp: "2026-07-20T16:00:00Z"}
	if err := propEngine.Approve(ctx, id, approveReq); err != nil {
		t.Fatalf("Approve(%s): %v", id, err)
	}

	if !hasSubject(t, client, graph.Ontology, propertyIRI) {
		t.Fatalf("setup problem: %s not routed into %s by Approve", propertyIRI, graph.Ontology)
	}
	postApproveVersion := ontologyVersion(t, client)
	if postApproveVersion == preVersion {
		t.Fatalf("setup problem: Approve did not bump owl:versionInfo (still %q)", preVersion)
	}

	if err := cpEngine.Restore(ctx, label); err != nil {
		t.Fatalf("Restore(%s): %v", label, err)
	}

	if hasSubject(t, client, graph.Ontology, propertyIRI) {
		t.Errorf("expected %s to be ABSENT from %s after restore (the approval should have been reverted)", propertyIRI, graph.Ontology)
	}
	if hasSubject(t, client, graph.Vocab, conceptIRI) {
		t.Errorf("expected %s to be ABSENT from %s after restore", conceptIRI, graph.Vocab)
	}
	if got := reviewStatus(t, client, id); got != "pending" {
		t.Errorf("proposal status after restore = %q, want %q (reverted)", got, "pending")
	}
	if got := ontologyVersion(t, client); got != preVersion {
		t.Errorf("owl:versionInfo after restore = %q, want the pre-checkpoint %q", got, preVersion)
	}
	if got := countGraphTriples(t, client, graph.Ontology); got != preOntologyCount {
		t.Errorf("%s triple count after restore = %d, want the pre-checkpoint %d", graph.Ontology, got, preOntologyCount)
	}
	if got := countGraphTriples(t, client, graph.Vocab); got != preVocabCount {
		t.Errorf("%s triple count after restore = %d, want the pre-checkpoint %d", graph.Vocab, got, preVocabCount)
	}
	if got := countGraphTriples(t, client, graph.Data); got != preDataCount {
		t.Errorf("%s triple count after restore = %d, want the pre-checkpoint %d", graph.Data, got, preDataCount)
	}
	if got := countGraphTriples(t, client, graph.Staging); got != preStagingCount {
		t.Errorf("%s triple count after restore = %d, want the pre-checkpoint %d", graph.Staging, got, preStagingCount)
	}
	if got := readMeasurementC0(t, dbPath, locator); got != 1.5 {
		t.Errorf("measurement_value.c0 for %s after restore = %v, want the checkpointed 1.5 (post-checkpoint drift to 99.9 should have been reverted)", locator, got)
	}

	// The demo can be re-run: re-approving after restore reproduces the
	// first approval's result.
	if err := propEngine.Approve(ctx, id, approveReq); err != nil {
		t.Fatalf("re-Approve(%s) after restore: %v", id, err)
	}
	if !hasSubject(t, client, graph.Ontology, propertyIRI) {
		t.Errorf("expected %s to be routed into %s again after re-approval", propertyIRI, graph.Ontology)
	}
	if got := ontologyVersion(t, client); got != postApproveVersion {
		t.Errorf("owl:versionInfo after re-approval = %q, want it to reproduce the first approval's %q", got, postApproveVersion)
	}
}
