package main

// Routing tests for the frontend-app-shell static/SPA handler
// (openspec/changes/web-frontend, task 8.6). These pin newMux's dispatch
// between the api routes (chat/proposals/checkpoints/healthz, owned by
// chunk 4/9) and the embedded static handler (chunk 10): every explicit
// /api/* and /healthz route must keep resolving to its own handler (not the
// SPA), an unknown /api/* path must NOT be served the SPA fallback, and a
// non-API GET (including a client-side-routed deep link like /review) must
// serve the embedded index.html.
//
// Builds the mux via the real 5-arg newMux(chat, gr, ps, cs, static)
// signature (cmd/server/handler.go) and a real newStaticHandler(fs.FS)
// (cmd/server/static.go) backed by an in-memory fstest.MapFS standing in
// for the embedded webapp/build directory, so this test never touches the
// actual embedded assets. Reuses the fakeProposalReader/fakeProposalService/
// fakeCheckpointService test doubles from proposals_test.go/
// checkpoints_test.go and the chatStub from proposals_test.go.

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"testing/fstest"
)

// newTestFS builds a minimal fake embedded frontend build directory: an
// index.html (the SPA entry every fallback scenario serves) plus one hashed
// asset file, so isEmbeddedFile's "does this path name a real file" check
// has something concrete to find.
func newTestFS() fstest.MapFS {
	return fstest.MapFS{
		"index.html":            {Data: []byte("<html>spa-shell</html>")},
		"_app/immutable/app.js": {Data: []byte("console.log('app');")},
	}
}

func TestNewMux_APIRoutesNotShadowedByStatic(t *testing.T) {
	static := newStaticHandler(newTestFS())

	tests := []struct {
		name       string
		method     string
		path       string
		wantStatus int
	}{
		{
			name:       "POST /api/chat routes to the chat handler",
			method:     http.MethodPost,
			path:       "/api/chat",
			wantStatus: http.StatusOK,
		},
		{
			name:       "GET /api/proposals routes to the proposal queue handler",
			method:     http.MethodGet,
			path:       "/api/proposals",
			wantStatus: http.StatusOK,
		},
		{
			name:       "GET /healthz is unaffected by the static handler",
			method:     http.MethodGet,
			path:       "/healthz",
			wantStatus: http.StatusOK,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			stub := &chatStub{}
			mux := newMux(stub, &fakeProposalReader{}, &fakeProposalService{}, &fakeCheckpointService{}, static)

			req := httptest.NewRequest(tt.method, tt.path, nil)
			rec := httptest.NewRecorder()
			mux.ServeHTTP(rec, req)

			if rec.Code != tt.wantStatus {
				t.Errorf("status = %d, want %d (body: %q)", rec.Code, tt.wantStatus, rec.Body.String())
			}

			// None of these responses should be the SPA shell.
			if body := rec.Body.String(); body == "<html>spa-shell</html>" {
				t.Errorf("body = %q, want the API handler's response, not the SPA fallback", body)
			}
		})
	}
}

func TestNewMux_UnknownAPIPathNotServedSPA(t *testing.T) {
	static := newStaticHandler(newTestFS())
	mux := newMux(&chatStub{}, &fakeProposalReader{}, &fakeProposalService{}, &fakeCheckpointService{}, static)

	req := httptest.NewRequest(http.MethodGet, "/api/does-not-exist", nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Errorf("status = %d, want %d", rec.Code, http.StatusNotFound)
	}
	if body := rec.Body.String(); body == "<html>spa-shell</html>" {
		t.Errorf("unknown /api/* path was served the SPA fallback: body = %q", body)
	}
}

func TestNewMux_ServesSPAForRootAndDeepLinks(t *testing.T) {
	static := newStaticHandler(newTestFS())
	mux := newMux(&chatStub{}, &fakeProposalReader{}, &fakeProposalService{}, &fakeCheckpointService{}, static)

	tests := []struct {
		name string
		path string
	}{
		{name: "GET / serves the app shell", path: "/"},
		{name: "GET /review deep link serves the app shell", path: "/review"},
		{name: "GET /admin deep link serves the app shell", path: "/admin"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, tt.path, nil)
			rec := httptest.NewRecorder()
			mux.ServeHTTP(rec, req)

			if rec.Code != http.StatusOK {
				t.Errorf("status = %d, want %d", rec.Code, http.StatusOK)
			}
			if got, want := rec.Body.String(), "<html>spa-shell</html>"; got != want {
				t.Errorf("body = %q, want %q", got, want)
			}
		})
	}
}

func TestNewMux_ServesHashedAssetFromEmbeddedFS(t *testing.T) {
	static := newStaticHandler(newTestFS())
	mux := newMux(&chatStub{}, &fakeProposalReader{}, &fakeProposalService{}, &fakeCheckpointService{}, static)

	req := httptest.NewRequest(http.MethodGet, "/_app/immutable/app.js", nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("status = %d, want %d", rec.Code, http.StatusOK)
	}
	if got, want := rec.Body.String(), "console.log('app');"; got != want {
		t.Errorf("body = %q, want %q (the hashed asset, not the SPA fallback)", got, want)
	}
}
