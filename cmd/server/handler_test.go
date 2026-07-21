package main

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestHealthz(t *testing.T) {
	tests := []struct {
		name       string
		method     string
		path       string
		wantStatus int
		wantBody   string
	}{
		{
			name:       "GET returns 200 ok",
			method:     http.MethodGet,
			path:       "/healthz",
			wantStatus: http.StatusOK,
			wantBody:   "ok",
		},
		{
			name:       "POST is not allowed",
			method:     http.MethodPost,
			path:       "/healthz",
			wantStatus: http.StatusMethodNotAllowed,
		},
		{
			name:       "unknown path is not found",
			method:     http.MethodGet,
			path:       "/does-not-exist",
			wantStatus: http.StatusNotFound,
		},
	}

	// newMux gained proposal/checkpoint dependencies in
	// openspec/changes/apply-ontology-changes (chunk 9, task 5.3) and a
	// static-frontend dependency in openspec/changes/web-frontend (chunk
	// 10, task 6.3); the fakes/stub here are unused by any request this
	// test issues, so their zero values (and a plain 404 for static) are
	// enough to keep /healthz's own behavior unaffected. static_test.go
	// (task 8.6) covers the static handler's own routing.
	mux := newMux(http.NotFoundHandler(), &fakeProposalReader{}, &fakeProposalService{}, &fakeCheckpointService{}, http.NotFoundHandler())

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(tt.method, tt.path, nil)
			rec := httptest.NewRecorder()

			mux.ServeHTTP(rec, req)

			if rec.Code != tt.wantStatus {
				t.Errorf("status = %d, want %d", rec.Code, tt.wantStatus)
			}

			if tt.wantBody != "" {
				if got := rec.Body.String(); got != tt.wantBody {
					t.Errorf("body = %q, want %q", got, tt.wantBody)
				}
			}
		})
	}
}
