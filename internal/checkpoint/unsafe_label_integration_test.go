package checkpoint_test

// TestCheckpoint_UnsafeLabelRejectedByCreateAndRestore pins
// store-checkpoint-restore spec.md's "An unsafe label is rejected"
// scenario (task 4.4, design D8): a path-traversal label is rejected by
// both Create and Restore before any file outside root is touched.

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/blogem/msr-graph/internal/checkpoint"
)

func TestCheckpoint_UnsafeLabelRejectedByCreateAndRestore(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()
	dbPath, _ := newTestSQLiteDB(t)
	root := t.TempDir()
	const unsafeLabel = "../etc"

	engine := checkpoint.NewEngine(client, dbPath, root)

	if _, err := engine.Create(ctx, unsafeLabel); !errors.Is(err, checkpoint.ErrInvalidLabel) {
		t.Fatalf("Create(%q) = %v, want errors.Is(err, checkpoint.ErrInvalidLabel)", unsafeLabel, err)
	}
	if err := engine.Restore(ctx, unsafeLabel); !errors.Is(err, checkpoint.ErrInvalidLabel) {
		t.Fatalf("Restore(%q) = %v, want errors.Is(err, checkpoint.ErrInvalidLabel)", unsafeLabel, err)
	}

	// "../etc" resolved against root would land one directory above root;
	// confirm nothing was written there.
	outside := filepath.Join(filepath.Dir(root), "etc")
	if _, err := os.Stat(outside); !os.IsNotExist(err) {
		t.Errorf("expected no file/dir at %s (outside the checkpoint root), got stat err = %v", outside, err)
	}
}
