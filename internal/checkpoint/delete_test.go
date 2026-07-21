package checkpoint_test

// Unit tests for checkpoint.Engine.Delete (spec store-checkpoint-restore,
// "Delete removes a checkpoint's stored artifacts"): Delete is
// filesystem-only -- it never touches the GraphDB repository or the live
// SQLite store -- so these run with a nil GraphClient and an empty dbPath
// against a temp checkpoints root, no live GraphDB needed.

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/blogem/msr-graph/internal/checkpoint"
)

// writeFakeCheckpoint creates root/label/ with a minimal manifest.json so
// the directory looks like a real checkpoint for Delete to remove.
func writeFakeCheckpoint(t *testing.T, root, label string) string {
	t.Helper()
	dir := filepath.Join(root, label)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatalf("MkdirAll(%s): %v", dir, err)
	}
	if err := os.WriteFile(filepath.Join(dir, "manifest.json"), []byte(`{"label":"`+label+`"}`), 0o644); err != nil {
		t.Fatalf("writing manifest.json: %v", err)
	}
	return dir
}

func TestDelete_RemovesCheckpointDir(t *testing.T) {
	root := t.TempDir()
	dir := writeFakeCheckpoint(t, root, "demo")
	// A sibling checkpoint that must survive the delete of "demo".
	siblingDir := writeFakeCheckpoint(t, root, "keep")

	engine := checkpoint.NewEngine(nil, "", root)
	if err := engine.Delete(context.Background(), "demo"); err != nil {
		t.Fatalf("Delete(demo) = %v, want nil", err)
	}

	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatalf("checkpoint dir %s still exists after Delete (stat err = %v)", dir, err)
	}
	if _, err := os.Stat(siblingDir); err != nil {
		t.Fatalf("sibling checkpoint dir %s should be untouched, stat err = %v", siblingDir, err)
	}
}

func TestDelete_UnknownLabelReturnsNotFound(t *testing.T) {
	root := t.TempDir()
	engine := checkpoint.NewEngine(nil, "", root)

	err := engine.Delete(context.Background(), "does-not-exist")
	if !errors.Is(err, checkpoint.ErrNotFound) {
		t.Fatalf("Delete(unknown) = %v, want errors.Is(err, checkpoint.ErrNotFound)", err)
	}
}

func TestDelete_UnsafeLabelRejectedBeforeFilesystem(t *testing.T) {
	root := t.TempDir()
	// A file just outside the checkpoints root that a path-traversal label
	// could target; Delete must reject the label before ever touching it.
	sentinel := filepath.Join(filepath.Dir(root), "sentinel.txt")
	if err := os.WriteFile(sentinel, []byte("keep me"), 0o644); err != nil {
		t.Fatalf("writing sentinel: %v", err)
	}
	t.Cleanup(func() { _ = os.Remove(sentinel) })

	engine := checkpoint.NewEngine(nil, "", root)

	err := engine.Delete(context.Background(), "../sentinel.txt")
	if !errors.Is(err, checkpoint.ErrInvalidLabel) {
		t.Fatalf("Delete(unsafe) = %v, want errors.Is(err, checkpoint.ErrInvalidLabel)", err)
	}
	if _, err := os.Stat(sentinel); err != nil {
		t.Fatalf("sentinel file should be untouched, stat err = %v", err)
	}
}
