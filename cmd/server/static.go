package main

import (
	"io/fs"
	"net/http"
	"path"
	"strings"
)

// newStaticHandler serves the embedded SvelteKit build from fsys (design D1,
// D2; spec frontend-app-shell). It is registered on newMux at the root
// pattern "/" as a catch-all, so it must itself guard against shadowing API
// routes that don't otherwise match a more specific mux pattern.
//
// Behavior:
//   - Any request whose path begins with "/api/" is explicitly 404'd (task
//     6.4): the "/" catch-all would otherwise serve the SPA for an unknown
//     /api/* path, which the frontend-app-shell spec forbids ("Unknown API
//     path is not served the SPA").
//   - A request that names an actual file in fsys is served by
//     http.FileServerFS, which sets the Content-Type from the file
//     extension.
//   - A non-matching GET is treated as SPA client-side routing (e.g. a deep
//     link to /review or /admin) and served the embedded index.html, so
//     direct navigation/reload works.
//   - A non-matching non-GET request is 404'd; the SPA fallback only makes
//     sense for a browser navigation.
func newStaticHandler(fsys fs.FS) http.Handler {
	fileServer := http.FileServerFS(fsys)

	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/api/") {
			http.NotFound(w, r)
			return
		}

		if isEmbeddedFile(fsys, r.URL.Path) {
			fileServer.ServeHTTP(w, r)
			return
		}

		if r.Method != http.MethodGet {
			http.NotFound(w, r)
			return
		}

		serveIndex(w, r, fsys)
	})
}

// isEmbeddedFile reports whether urlPath names a regular (non-directory)
// file in fsys, i.e. whether the request should be treated as a static
// asset request rather than falling through to the SPA index.
func isEmbeddedFile(fsys fs.FS, urlPath string) bool {
	clean := strings.TrimPrefix(path.Clean(urlPath), "/")
	if clean == "" || clean == "." {
		return false
	}

	info, err := fs.Stat(fsys, clean)
	if err != nil {
		return false
	}
	return !info.IsDir()
}

// serveIndex writes the embedded index.html directly (rather than via the
// file server, which would only serve it for the exact "/" path) so it also
// answers SPA deep links like /review and /admin.
func serveIndex(w http.ResponseWriter, r *http.Request, fsys fs.FS) {
	b, err := fs.ReadFile(fsys, "index.html")
	if err != nil {
		http.Error(w, "index.html not found in embedded frontend build", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	w.Write(b)
}
