package main

import (
	"encoding/json"
	"log"
	"net/http"

	"github.com/blogem/msr-graph/internal/agent"
)

// sseHeaders sets the response headers required for a Server-Sent Events
// stream: no buffering/caching, and a long-lived connection.
func sseHeaders(w http.ResponseWriter) {
	h := w.Header()
	h.Set("Content-Type", "text/event-stream")
	h.Set("Cache-Control", "no-cache")
	h.Set("Connection", "keep-alive")
}

// newSSEEmitter returns an agent.Emitter that JSON-marshals each agent.Event
// and writes it as one SSE frame (`event: <type>\ndata: <json>\n\n`),
// flushing after every frame so the client sees events as they happen
// rather than buffered until the response closes.
//
// If w does not implement http.Flusher, events are still written (so the
// full body is available once the handler returns, e.g. under
// httptest.ResponseRecorder) but are never flushed mid-stream.
func newSSEEmitter(w http.ResponseWriter) agent.Emitter {
	flusher, _ := w.(http.Flusher)

	return func(e agent.Event) {
		b, err := json.Marshal(e)
		if err != nil {
			// An event that fails to marshal is a programming error in this
			// package, not a client-facing failure; log and drop it rather
			// than abort the whole stream.
			log.Printf("chat: failed to marshal event %q: %v", e.Type, err)
			return
		}

		if _, err := w.Write([]byte("event: " + string(e.Type) + "\n")); err != nil {
			return
		}
		if _, err := w.Write([]byte("data: ")); err != nil {
			return
		}
		if _, err := w.Write(b); err != nil {
			return
		}
		if _, err := w.Write([]byte("\n\n")); err != nil {
			return
		}

		if flusher != nil {
			flusher.Flush()
		}
	}
}
