package main

import (
	"encoding/json"
	"net/http"
	"strconv"

	"github.com/blogem/msr-graph/internal/agent"
)

// chatRequest is the decoded shape of a POST /api/chat body: the full
// conversation so far, OpenAI-style. The server holds no session state, so
// every request must carry the complete conversation (spec "Stateless
// POST /api/chat endpoint").
type chatRequest struct {
	Messages []agent.Message `json:"messages"`
}

// validate reports whether req is a well-formed chat request: messages must
// be present and non-empty, and every message must carry both a role and
// content (spec "Malformed request body is rejected"). It returns a
// human-readable reason on failure.
func (req chatRequest) validate() (string, bool) {
	if len(req.Messages) == 0 {
		return "messages must be a non-empty array", false
	}
	for i, m := range req.Messages {
		if m.Role == "" {
			return "message at index " + strconv.Itoa(i) + " is missing role", false
		}
		if m.Content == "" {
			return "message at index " + strconv.Itoa(i) + " is missing content", false
		}
	}
	return "", true
}

// newChatHandler builds the POST /api/chat handler. It decodes the
// stateless OpenAI-style request body, rejects malformed bodies with 400
// before starting any turn, and otherwise streams the agent's trace events
// as SSE, ending every stream with a terminating "done" event. It never
// persists anything: prompts.Get and ag.Run only read from the injected
// dependencies (spec "Traces are ephemeral").
func newChatHandler(ag *agent.Agent, prompts *agent.PromptCache) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			w.Header().Set("Allow", http.MethodPost)
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var req chatRequest
		dec := json.NewDecoder(r.Body)
		if err := dec.Decode(&req); err != nil {
			http.Error(w, "malformed request body: "+err.Error(), http.StatusBadRequest)
			return
		}
		if reason, ok := req.validate(); !ok {
			http.Error(w, "malformed request body: "+reason, http.StatusBadRequest)
			return
		}

		sseHeaders(w)
		w.WriteHeader(http.StatusOK)
		emit := newSSEEmitter(w)

		prompt, version, err := prompts.Get(r.Context())
		if err != nil {
			emit(agent.Event{Type: agent.EventError, Error: "failed to load system prompt: " + err.Error()})
			emit(agent.Event{Type: agent.EventDone})
			return
		}

		runReq := agent.RunRequest{
			SystemPrompt:    prompt,
			Messages:        req.Messages,
			OntologyVersion: version,
		}

		// Run already emits an EventError followed by an EventDone on failure
		// (see internal/agent/loop.go), so the error return value need not be
		// handled again here.
		_ = ag.Run(r.Context(), runReq, emit)
	})
}
