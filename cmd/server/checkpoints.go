// Checkpoint HTTP API (openspec/changes/apply-ontology-changes, spec
// store-checkpoint-restore, "Checkpoint API and make wrappers"): the
// JSON list/create/restore endpoints backed by internal/checkpoint's
// whole-store checkpoint/restore engine. Like the proposal handlers in
// proposals.go, these stay thin (design D6) and depend on the narrow
// checkpointService interface rather than *checkpoint.Engine directly.
package main

import (
	"context"
	"encoding/json"
	"net/http"

	"github.com/blogem/msr-graph/internal/checkpoint"
)

// checkpointService is the subset of *checkpoint.Engine the checkpoint
// handlers use.
type checkpointService interface {
	Create(ctx context.Context, label string) (checkpoint.Manifest, error)
	Restore(ctx context.Context, label string) error
	List() ([]checkpoint.Manifest, error)
}

// checkpointListResponse is the GET /api/checkpoints response shape.
type checkpointListResponse struct {
	Checkpoints []checkpoint.Manifest `json:"checkpoints"`
}

// newCheckpointListHandler builds the GET /api/checkpoints handler.
func newCheckpointListHandler(cs checkpointService) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		manifests, err := cs.List()
		if err != nil {
			mapEngineError(w, err)
			return
		}
		if manifests == nil {
			// Marshal "checkpoints": [] rather than "checkpoints": null
			// when there are no checkpoints yet.
			manifests = []checkpoint.Manifest{}
		}
		writeJSON(w, http.StatusOK, checkpointListResponse{Checkpoints: manifests})
	}
}

// checkpointCreateRequest is the POST /api/checkpoints request body.
type checkpointCreateRequest struct {
	Label string `json:"label"`
}

// newCheckpointCreateHandler builds the POST /api/checkpoints handler:
// it creates a checkpoint under the request-supplied label and returns
// its manifest with 201 Created. An unsafe label (path-traversal
// characters, etc.) is rejected by checkpointService.Create
// (checkpoint.ValidateLabel) before any path is touched and mapped to
// 400 by mapEngineError.
func newCheckpointCreateHandler(cs checkpointService) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var req checkpointCreateRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeBadRequest(w, "malformed request body: "+err.Error())
			return
		}

		manifest, err := cs.Create(r.Context(), req.Label)
		if err != nil {
			mapEngineError(w, err)
			return
		}
		writeJSON(w, http.StatusCreated, manifest)
	}
}

// newCheckpointRestoreHandler builds the POST
// /api/checkpoints/{label}/restore handler: it restores the whole store
// (GraphDB repository and SQLite measurement store) from the named
// checkpoint. No request body is required.
func newCheckpointRestoreHandler(cs checkpointService) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		label := r.PathValue("label")

		if err := cs.Restore(r.Context(), label); err != nil {
			mapEngineError(w, err)
			return
		}
		writeJSON(w, http.StatusOK, statusResponse{Status: "restored"})
	}
}
