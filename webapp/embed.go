// Package webapp embeds the built SvelteKit static frontend (see
// openspec/changes/web-frontend, design D1) into the Go server binary so the
// whole solution ships as a single deployable with no separate frontend
// service.
//
// The build output directory (webapp/build/) is produced by the SvelteKit
// static adapter (npm run build) and mirrors internal/store's //go:embed
// precedent. The all: prefix is required (not just //go:embed build):
// SvelteKit emits an underscore-prefixed _app/ directory (e.g.
// build/_app/immutable/...), and Go's embed package excludes files and
// directories whose names begin with "_" or "." unless the pattern is
// prefixed with "all:". Without "all:", the embedded FS would silently be
// missing every hashed asset under _app/.
package webapp

import "embed"

//go:embed all:build
var Assets embed.FS
