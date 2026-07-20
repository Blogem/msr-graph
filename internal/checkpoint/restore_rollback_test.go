package checkpoint_test

// TestRestore_ImportFailureTriggersBestEffortRollback is a pure unit test
// (no live GraphDB) that pins the code-review fix to Restore: ClearRepo and
// ImportRepo are two separate REST calls, not one transaction, so a failure
// of ImportRepo after ClearRepo already succeeded must not silently leave
// the repository empty. Restore is expected to have captured a pre-clear
// export via ExportRepo before calling ClearRepo, and to attempt a
// best-effort re-import of that snapshot when the checkpoint import fails,
// returning an error that clearly distinguishes this partial-failure/
// rollback mode from an ordinary no-op failure.

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/blogem/msr-graph/internal/checkpoint"
	"github.com/blogem/msr-graph/internal/graph"
)

// fakeRestoreGraphClient is a hand-rolled checkpoint.GraphClient double: no
// live GraphDB is contacted, and ImportRepo's behavior (success/failure) is
// controlled by matching the exact trig payload it is called with, so the
// test can tell a checkpoint-import attempt apart from a rollback attempt.
type fakeRestoreGraphClient struct {
	preClearSnapshot []byte
	exportErr        error
	exportCalls      int

	clearErr   error
	clearCalls int

	// failOn is the exact trig payload that ImportRepo should fail on
	// (the checkpoint's store.trig); any other payload (i.e. the rollback
	// re-import of preClearSnapshot) succeeds unless rollbackErr is set.
	failOn      []byte
	failOnErr   error
	rollbackErr error
	importCalls [][]byte
}

func (f *fakeRestoreGraphClient) ExportRepo(ctx context.Context) ([]byte, error) {
	f.exportCalls++
	if f.exportErr != nil {
		return nil, f.exportErr
	}
	return f.preClearSnapshot, nil
}

func (f *fakeRestoreGraphClient) ClearRepo(ctx context.Context) error {
	f.clearCalls++
	return f.clearErr
}

func (f *fakeRestoreGraphClient) ImportRepo(ctx context.Context, trig []byte) error {
	f.importCalls = append(f.importCalls, append([]byte(nil), trig...))
	if bytes.Equal(trig, f.failOn) {
		return f.failOnErr
	}
	// This is the rollback re-import of the pre-clear snapshot.
	return f.rollbackErr
}

func (f *fakeRestoreGraphClient) SelectRaw(ctx context.Context, query string) (*graph.Results, error) {
	return &graph.Results{}, nil
}

// writeFixtureCheckpoint writes a minimal, structurally valid checkpoint
// directory (store.trig, msr.db, manifest.json) under root/label, mirroring
// Engine.Create's on-disk layout. msr.db's content is never read on the
// import-failure path this test exercises (the SQLite swap only runs after
// a successful graph import), so a placeholder is sufficient.
func writeFixtureCheckpoint(t *testing.T, root, label, trigContent string) {
	t.Helper()
	dir := filepath.Join(root, label)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatalf("MkdirAll(%s): %v", dir, err)
	}
	if err := os.WriteFile(filepath.Join(dir, "store.trig"), []byte(trigContent), 0o644); err != nil {
		t.Fatalf("write store.trig: %v", err)
	}
	if err := os.WriteFile(filepath.Join(dir, "msr.db"), []byte("not-a-real-sqlite-file"), 0o644); err != nil {
		t.Fatalf("write msr.db: %v", err)
	}
	manifest := `{"label":"` + label + `","ontology_version":"0.4.0"}`
	if err := os.WriteFile(filepath.Join(dir, "manifest.json"), []byte(manifest), 0o644); err != nil {
		t.Fatalf("write manifest.json: %v", err)
	}
}

func TestRestore_ImportFailureTriggersBestEffortRollback(t *testing.T) {
	const (
		checkpointTrig   = "checkpoint-trig-content"
		preClearSnapshot = "pre-restore-live-repo-content"
	)

	t.Run("rollback succeeds", func(t *testing.T) {
		root := t.TempDir()
		label := "demo"
		writeFixtureCheckpoint(t, root, label, checkpointTrig)

		fake := &fakeRestoreGraphClient{
			preClearSnapshot: []byte(preClearSnapshot),
			failOn:           []byte(checkpointTrig),
			failOnErr:        errors.New("shacl rejected checkpoint trig"),
		}

		engine := checkpoint.NewEngine(fake, filepath.Join(root, "live.db"), root)
		err := engine.Restore(context.Background(), label)

		if err == nil {
			t.Fatal("Restore: expected an error, got nil")
		}

		// The error message must convey the partial-failure/rollback
		// semantics -- distinguishable from an ordinary no-op failure --
		// and, since the rollback succeeded here, must not claim the repo
		// is empty.
		msg := err.Error()
		if !strings.Contains(msg, "clearing the repository") || !strings.Contains(msg, "rollback") {
			t.Errorf("Restore error %q does not convey the clear+rollback partial-failure mode", msg)
		}
		if !strings.Contains(msg, "succeeded") && !strings.Contains(msg, "unchanged") {
			t.Errorf("Restore error %q does not convey that the rollback restored the pre-restore state", msg)
		}
		if strings.Contains(msg, "EMPTY") {
			t.Errorf("Restore error %q wrongly claims the repo is empty when rollback succeeded", msg)
		}

		// The fake must have recorded: one pre-clear export, one clear,
		// and two import attempts -- the failed checkpoint import followed
		// by the rollback re-import of the pre-clear snapshot.
		if fake.exportCalls != 1 {
			t.Errorf("ExportRepo calls = %d, want 1 (pre-clear snapshot)", fake.exportCalls)
		}
		if fake.clearCalls != 1 {
			t.Errorf("ClearRepo calls = %d, want 1", fake.clearCalls)
		}
		if len(fake.importCalls) != 2 {
			t.Fatalf("ImportRepo calls = %d, want 2 (checkpoint attempt + rollback attempt)", len(fake.importCalls))
		}
		if !bytes.Equal(fake.importCalls[0], []byte(checkpointTrig)) {
			t.Errorf("first ImportRepo call = %q, want the checkpoint trig %q", fake.importCalls[0], checkpointTrig)
		}
		if !bytes.Equal(fake.importCalls[1], []byte(preClearSnapshot)) {
			t.Errorf("second ImportRepo call = %q, want the pre-clear snapshot %q (the rollback re-import)", fake.importCalls[1], preClearSnapshot)
		}
	})

	t.Run("rollback also fails", func(t *testing.T) {
		root := t.TempDir()
		label := "demo"
		writeFixtureCheckpoint(t, root, label, checkpointTrig)

		fake := &fakeRestoreGraphClient{
			preClearSnapshot: []byte(preClearSnapshot),
			failOn:           []byte(checkpointTrig),
			failOnErr:        errors.New("shacl rejected checkpoint trig"),
			rollbackErr:      errors.New("graphdb unreachable"),
		}

		engine := checkpoint.NewEngine(fake, filepath.Join(root, "live.db"), root)
		err := engine.Restore(context.Background(), label)

		if err == nil {
			t.Fatal("Restore: expected an error, got nil")
		}

		msg := err.Error()
		if !strings.Contains(msg, "EMPTY") {
			t.Errorf("Restore error %q must explicitly state the repository is now EMPTY when rollback also fails", msg)
		}
		if !strings.Contains(msg, "manual intervention") {
			t.Errorf("Restore error %q must explicitly call for manual intervention when rollback also fails", msg)
		}

		if len(fake.importCalls) != 2 {
			t.Fatalf("ImportRepo calls = %d, want 2 (checkpoint attempt + rollback attempt)", len(fake.importCalls))
		}
	})
}
