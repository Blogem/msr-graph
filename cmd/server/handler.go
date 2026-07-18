package main

import "net/http"

// newMux builds the HTTP handler for the server. Routes are added here as
// later tasks bring in the chat/review/checkpoint APIs and the embedded
// frontend.
func newMux() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", healthzHandler)
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
