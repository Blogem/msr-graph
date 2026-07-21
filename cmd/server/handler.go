package main

import (
	"bytes"
	"net/http"
)

// newMux builds the HTTP handler for the server. chat handles POST
// /api/chat; gr, ps, and cs back the proposal review and checkpoint APIs
// -- each declared as the narrow interface its handlers actually use
// (design D6), so a fake can stand in for *graph.Client / *proposal.Engine
// / *checkpoint.Engine in tests with no live GraphDB or filesystem. static
// serves the embedded SvelteKit frontend (openspec/changes/web-frontend,
// design D2, spec frontend-app-shell).
//
// static is NOT registered on the api mux at "/" (design D2's original
// approach). Doing so would register an unrestricted catch-all pattern
// alongside chunk 9's Go 1.22 method-scoped patterns (e.g. "POST
// /api/checkpoints/{label}/restore"): per net/http's documented precedence
// rule, ServeMux picks the single most specific *registered pattern that
// actually matches the request* (host+path+method together, not path
// alone). A method-scoped pattern simply doesn't match a request using a
// different method, so for e.g. a GET to that POST-only path, "/" would
// become the *only* pattern that matches -- silently replacing net/http's
// own built-in "known path, wrong method -> 405 + Allow header" behavior
// with whatever "/" serves, and regressing chunk 9's WrongMethod tests
// (openspec/changes/apply-ontology-changes) from 405 to a 404. Verified
// empirically against net/http (go1.26): registering "/" turns those three
// tests from pass to fail.
//
// newAPIOrStaticMux below resolves this by keeping the /api/* + /healthz
// routes on their own mux with no catch-all, and dispatching to static only
// when that mux has no pattern that applies to the request at all.
func newMux(chat http.Handler, gr graphReader, ps proposalService, cs checkpointService, static http.Handler) http.Handler {
	api := http.NewServeMux()
	api.HandleFunc("/healthz", healthzHandler)
	api.Handle("/api/chat", chat)

	// Proposal review API (openspec/changes/apply-ontology-changes,
	// spec proposal-review-api). Go 1.22+ ServeMux method-scoped patterns
	// return 405 with an Allow header automatically for a path that
	// matches but a method that doesn't -- no per-handler method check
	// needed, unlike healthzHandler/newChatHandler above which predate
	// that mux feature.
	api.HandleFunc("GET /api/proposals", newProposalQueueHandler(gr))
	api.HandleFunc("GET /api/proposals/{id}", newProposalDetailHandler(gr))
	api.HandleFunc("PUT /api/proposals/{id}/graph", newProposalEditHandler(ps))
	api.HandleFunc("POST /api/proposals/{id}/approve", newProposalApproveHandler(ps))
	api.HandleFunc("POST /api/proposals/{id}/reject", newProposalRejectHandler(ps))

	// Checkpoint API (spec store-checkpoint-restore, "Checkpoint API and
	// make wrappers").
	api.HandleFunc("GET /api/checkpoints", newCheckpointListHandler(cs))
	api.HandleFunc("POST /api/checkpoints", newCheckpointCreateHandler(cs))
	api.HandleFunc("POST /api/checkpoints/{label}/restore", newCheckpointRestoreHandler(cs))

	return newAPIOrStaticMux(api, static)
}

// newAPIOrStaticMux dispatches each request to api if api has a registered
// pattern that actually applies to it (matching host+path+method), and to
// static (the embedded SPA/static-asset handler, spec frontend-app-shell)
// otherwise. See the comment on newMux for why this can't be a plain "/"
// registration on api itself.
//
// api.Handler(r) resolves the same routing decision api.ServeHTTP would
// make, without invoking anything, and returns an empty pattern exactly
// when no registered pattern applies to the request. That covers two
// cases api can't distinguish between via Handler() alone: a genuinely
// unknown path (should fall back to static), and a known path requested
// with the wrong method (should get net/http's own 405 + Allow header).
//
// When pattern != "", the request is dispatched via api.ServeHTTP(w, r) --
// not by invoking the handler Handler() returned directly. Handler() is a
// pure lookup: it does not bind {id}/{label}-style wildcards onto r (that
// only happens inside ServeMux's own ServeHTTP dispatch), so calling the
// returned handler directly would silently serve every wildcard as empty.
// Routing through api.ServeHTTP(w, r) also keeps this a single direct
// dispatch straight onto the real ResponseWriter, so /api/chat's SSE
// streaming is unaffected (no buffering on the matched path).
//
// When pattern == "" (the ambiguous case), the request is actually run
// through api.ServeHTTP into an in-memory recorder so the status can be
// inspected before it reaches the client: a real 404 is discarded in favor
// of static, while a 405 (or anything else) is copied through unchanged,
// Allow header included. /api/chat and /healthz are never ambiguous --
// both are registered with no method restriction (mux.Handle("/api/chat",
// chat) / mux.HandleFunc("/healthz", ...), predating Go 1.22's
// method-scoped patterns), so api.Handler always resolves a non-empty
// pattern for them regardless of method, taking the direct-dispatch path
// above instead.
func newAPIOrStaticMux(api *http.ServeMux, static http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if _, pattern := api.Handler(r); pattern != "" {
			api.ServeHTTP(w, r)
			return
		}

		rec := newResponseRecorder()
		api.ServeHTTP(rec, r)
		if rec.status == http.StatusNotFound {
			static.ServeHTTP(w, r)
			return
		}

		dst := w.Header()
		for k, vv := range rec.Header() {
			dst[k] = vv
		}
		w.WriteHeader(rec.status)
		w.Write(rec.body.Bytes())
	})
}

// responseRecorder is a minimal in-memory http.ResponseWriter used by
// newAPIOrStaticMux to inspect api's response (specifically, whether it's a
// 404) before deciding whether to forward it or fall back to the static
// handler instead.
type responseRecorder struct {
	header http.Header
	body   bytes.Buffer
	status int
}

func newResponseRecorder() *responseRecorder {
	return &responseRecorder{header: make(http.Header), status: http.StatusOK}
}

func (r *responseRecorder) Header() http.Header { return r.header }

func (r *responseRecorder) Write(b []byte) (int, error) { return r.body.Write(b) }

func (r *responseRecorder) WriteHeader(status int) { r.status = status }

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
