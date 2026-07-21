package checkpoint_test

// TestCheckpoint_CreateWritesThreeArtifacts pins store-checkpoint-restore
// spec.md's "Checkpoint writes all three artifacts" scenario (task 4.4):
// Create(ctx, label) writes store.trig, msr.db, and manifest.json under
// root/{label}/, and the manifest records the ontology version. Also
// exercises List() as a light coverage bonus (GET /api/checkpoints' engine
// dependency), since it is cheap once a checkpoint already exists.

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"github.com/blogem/msr-graph/internal/checkpoint"
)

func TestCheckpoint_CreateWritesThreeArtifacts(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()
	dbPath, _ := newTestSQLiteDB(t)
	root := t.TempDir()
	label := "testcp-" + uniqueSuffix()

	engine := checkpoint.NewEngine(client, dbPath, root)

	manifest, err := engine.Create(ctx, label)
	if err != nil {
		t.Fatalf("Create(%s): %v", label, err)
	}
	if manifest.Label != label {
		t.Errorf("manifest.Label = %q, want %q", manifest.Label, label)
	}
	if manifest.OntologyVersion == "" {
		t.Errorf("manifest.OntologyVersion is empty, want the recorded ontology version")
	}

	checkpointDir := filepath.Join(root, label)
	for _, name := range []string{"store.trig", "msr.db", "manifest.json"} {
		p := filepath.Join(checkpointDir, name)
		if info, err := os.Stat(p); err != nil {
			t.Errorf("expected checkpoint artifact %s to exist: %v", p, err)
		} else if info.Size() == 0 {
			t.Errorf("expected checkpoint artifact %s to be non-empty", p)
		}
	}

	manifests, err := engine.List()
	if err != nil {
		t.Fatalf("List(): %v", err)
	}
	found := false
	for _, m := range manifests {
		if m.Label == label {
			found = true
			if m.OntologyVersion != manifest.OntologyVersion {
				t.Errorf("List() manifest for %s has OntologyVersion %q, want %q", label, m.OntologyVersion, manifest.OntologyVersion)
			}
		}
	}
	if !found {
		t.Errorf("expected List() to include the just-created checkpoint %q, got %+v", label, manifests)
	}
}
