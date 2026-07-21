# frontend-app-shell Specification

## Purpose

Define the single SvelteKit application, built with the static adapter and embedded in the Go
`server` binary as one deployable, that hosts the chat, review, and admin surfaces. This
capability owns the build/embed pipeline, the server's static-asset + SPA-fallback serving added
alongside the existing `/api/*` and `/healthz` routes, and client-side routing across the three
surfaces. It does not own any backend API behavior — those are consumed from chunks 4 and 9.

## Requirements

### Requirement: Single SvelteKit app built with the static adapter
The frontend SHALL be one SvelteKit application configured with `@sveltejs/adapter-static`
producing a static build (SPA fallback to `index.html`), with no server-side rendering runtime
required in production. The build output SHALL be a self-contained directory of static assets.

#### Scenario: Static build produces embeddable assets
- **WHEN** the frontend is built
- **THEN** a static output directory containing `index.html` and hashed asset files is produced,
  requiring no Node.js runtime to serve

#### Scenario: Deep-link routing falls back to the SPA entry
- **WHEN** the build is configured
- **THEN** the static adapter is set with an `index.html` fallback so client-side routes resolve
  on direct navigation and reload

### Requirement: Frontend embedded in the server binary
The built static assets SHALL be embedded into the Go `server` binary via `//go:embed`, so the
whole solution ships as a single deployable with no separate frontend service. The server SHALL
serve the embedded assets over HTTP.

#### Scenario: Server serves embedded assets
- **WHEN** the server receives a `GET /` request
- **THEN** it responds with the embedded `index.html` from the built frontend

#### Scenario: Hashed asset is served from the embedded filesystem
- **WHEN** the server receives a request for a built asset path (e.g. a hashed JS/CSS file)
- **THEN** it serves that file from the embedded filesystem with an appropriate content type

### Requirement: Static serving is additive and never shadows API or health routes
The static/SPA-fallback handler SHALL be registered on the existing server mux as the root
catch-all so that it resolves only after the explicit `/api/*` and `/healthz` routes. Registering
it SHALL NOT alter the behavior of `POST /api/chat`, `/healthz`, or the chunk-9 `/api/proposals*`
and `/api/checkpoints*` routes. A request under `/api/` that matches no registered API route
SHALL NOT be answered with the SPA fallback.

#### Scenario: API routes still resolve to their handlers
- **WHEN** the static handler is registered and a client requests `POST /api/chat` or a
  registered `/api/proposals` route
- **THEN** the request is handled by the corresponding API handler, not the SPA fallback

#### Scenario: Health route unaffected
- **WHEN** a client requests `GET /healthz`
- **THEN** the health handler responds as before, unaffected by the static handler

#### Scenario: Unknown API path is not served the SPA
- **WHEN** a client requests an `/api/` path that matches no registered route
- **THEN** the server returns a not-found response, not the SPA `index.html`

### Requirement: SPA fallback for client-side routes
The server SHALL respond with the SPA entry `index.html` for any `GET` request to a non-`/api`,
non-`/healthz` path that does not match an embedded asset, so client-side routing renders the
requested surface.

#### Scenario: Deep link to a surface serves the app shell
- **WHEN** a client requests `GET /review` (or `/admin`) directly
- **THEN** the server responds with `index.html` and the client-side router renders that surface

### Requirement: Client-side routing across the three surfaces
The app SHALL provide client-side navigation between the chat, review, and admin surfaces within
the single application, without full-page reloads.

#### Scenario: Navigate between surfaces
- **WHEN** the user navigates from the chat surface to the review surface within the app
- **THEN** the review surface renders via client-side routing without a full-page reload

### Requirement: Build and embed pipeline wired into Docker and Make
The frontend build SHALL be wired into the Dockerfile as a stage that runs before the Go build
(so the embedded assets exist at compile time) and exposed as a Makefile target. The image build
SHALL produce the single `server` binary with the frontend embedded.

#### Scenario: Docker image build embeds the frontend
- **WHEN** the server image is built
- **THEN** the frontend is built in an earlier stage and its output is present for the Go
  `//go:embed` step, yielding one binary that serves the app

#### Scenario: Make target builds the frontend
- **WHEN** the frontend build Make target is run
- **THEN** the static build output is produced in the location the Go embed directive reads
