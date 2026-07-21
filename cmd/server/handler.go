package main

import "net/http"

// newMux builds the HTTP handler for the server. chat handles POST
// /api/chat; gr, ps, and cs back the proposal review and checkpoint APIs
// -- each declared as the narrow interface its handlers actually use
// (design D6), so a fake can stand in for *graph.Client / *proposal.Engine
// / *checkpoint.Engine in tests with no live GraphDB or filesystem. Routes
// for the embedded frontend are added by a later task.
func newMux(chat http.Handler, gr graphReader, ps proposalService, cs checkpointService) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", healthzHandler)
	mux.Handle("/api/chat", chat)

	// Proposal review API (openspec/changes/apply-ontology-changes,
	// spec proposal-review-api). Go 1.22+ ServeMux method-scoped patterns
	// return 405 with an Allow header automatically for a path that
	// matches but a method that doesn't -- no per-handler method check
	// needed, unlike healthzHandler/newChatHandler above which predate
	// that mux feature.
	mux.HandleFunc("GET /api/proposals", newProposalQueueHandler(gr))
	mux.HandleFunc("GET /api/proposals/{id}", newProposalDetailHandler(gr))
	mux.HandleFunc("PUT /api/proposals/{id}/graph", newProposalEditHandler(ps))
	mux.HandleFunc("POST /api/proposals/{id}/approve", newProposalApproveHandler(ps))
	mux.HandleFunc("POST /api/proposals/{id}/reject", newProposalRejectHandler(ps))

	// Checkpoint API (spec store-checkpoint-restore, "Checkpoint API and
	// make wrappers").
	mux.HandleFunc("GET /api/checkpoints", newCheckpointListHandler(cs))
	mux.HandleFunc("POST /api/checkpoints", newCheckpointCreateHandler(cs))
	mux.HandleFunc("POST /api/checkpoints/{label}/restore", newCheckpointRestoreHandler(cs))

	return mux
}

// healthzHandler reports service liveness. It responds only to GET; other
// methods are rejected with 405.
func healthzHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		w.Header().Set("Allow", http.MethodGet)
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	w.Write([]byte("ok"))
}
