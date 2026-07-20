## Context

Chunk 10 is the P6 milestone (M6): the single user-facing app that serves **both** demos —
grounded analysis with a visible trace, and the ontology-evolution review/reset loop — over the
already-built backends. It consumes two fixed contracts and adds no backend behavior:

- **chunk-4 `chat-api`** — stateless `POST /api/chat`; the request carries the full conversation
  OpenAI-style; the response is an SSE stream of typed trace events (`text`, `tool_call`,
  `tool_result`, `script_run`, `provenance`, `answer`, `done`). Traces are ephemeral.
- **chunk-9 `proposal-review-api` + `store-checkpoint-restore`** — `GET /api/proposals[?status=]`,
  `GET /api/proposals/{id}`, `PUT /api/proposals/{id}/graph`, `POST /api/proposals/{id}/approve`,
  `POST /api/proposals/{id}/reject`, `GET|POST /api/checkpoints`,
  `POST /api/checkpoints/{label}/restore`.

Current state: `webapp/` holds only a `.gitkeep`; `cmd/server/handler.go`'s `newMux` registers
`/healthz` and `/api/chat` and comments that "review/checkpoint APIs and the embedded frontend
are added by later tasks." Chunk 9 (`apply-ontology-changes`) is **in flight in a parallel
worktree** and will add the `/api/proposals*` and `/api/checkpoints*` routes to that same
`newMux`. ARCHITECTURE.md fixes the stack: Go + SvelteKit, single embedded frontend, SSE via
`fetch` streaming (native `EventSource` can't POST), per-turn expandable trace timeline, and a
rendered visual ontology diff for review.

Constraints from the cross-cutting contracts: one deployable (`server` binary with the frontend
embedded); the app has **no direct store access** — everything goes through the two HTTP APIs;
tests use vitest (repo UI standard) and run against mocked SSE/API without a live backend.

## Goals / Non-Goals

**Goals:**
- One SvelteKit app (static adapter) embedded in the Go `server` binary — one deployable.
- Chat surface that renders every chunk-4 trace event type, including script source and
  provenance chips, and marks each answer grounded/ungrounded.
- Review surface that renders a proposal as a highlighted ontology-neighborhood diff with an
  evidence panel, editable placement/unit fields, approve/edit/reject, and a raw-triples view.
- Admin surface for checkpoint list/create/restore enabling an end-to-end demo reset.
- Build/embed pipeline wired into Dockerfile + Makefile; additive changes to the shared
  `newMux` that don't disturb chunk 9's routes.

**Non-Goals:**
- No backend API changes; no new endpoints. (If a gap in the chunk-4/9 contract is found, it's
  raised as an open question, not patched here.)
- No trace persistence, no server-side sessions, no auth (single-user POC, matches statelessness).
- No direct GraphDB/SQLite access from the browser.
- No production hardening (rate limiting, multi-user, i18n) — this is a demo surface.
- Not re-specifying the SSE event schema or proposal payloads — those are owned by chunks 4/9.

## Decisions

### D1 — SvelteKit with `adapter-static`, embedded via Go `//go:embed`
Build the SPA with `@sveltejs/adapter-static` (`fallback: index.html` for SPA routing), output
to `webapp/build/`, and embed that directory into the Go binary with `//go:embed`. The server
serves assets from the embedded FS and falls back to `index.html` for non-`/api`, non-`/healthz`
paths so client-side routing works on deep links/reload.
- *Why*: ARCHITECTURE fixes "static build embedded in the server → one deployable." Static
  adapter needs no Node runtime in production; a single Go binary is the whole deploy.
- *Alternatives*: `adapter-node` (rejected — adds a second runtime/service, breaks "one
  deployable"); serving `webapp/build` from disk (rejected — embed keeps the binary
  self-contained and matches `internal/store`'s existing `//go:embed` precedent).

### D2 — Static handler registered last as the catch-all; `/api` never shadowed
Add the embedded-frontend handler to `newMux` as the root (`/`) catch-all, registered so it
resolves only after the explicit `/api/*` and `/healthz` routes. Requests under `/api/` that
match no registered API route return the mux's normal 404, not the SPA fallback.
- *Why*: chunk 9 adds `/api/proposals*` and `/api/checkpoints*` to the same `newMux`
  concurrently; a root catch-all that defers to more specific patterns is purely additive and
  cannot break their routes. Go's `http.ServeMux` longest-pattern-wins semantics make this safe.
- *Coordination*: the only shared file is `cmd/server/handler.go`. Keep the static-handler
  addition to a distinct block; expect a trivial merge with chunk 9. Guard with a test that
  `/api/chat` and a representative `/api/proposals` path still route to their handlers, not the
  SPA fallback.

### D3 — SSE consumed via `fetch` + `ReadableStream`, parsed into a typed event union
A single `streamChat(messages, onEvent)` client issues `fetch('/api/chat', {method:'POST'})`,
reads `response.body.getReader()`, decodes chunks, and splits on the SSE framing (`\n\n`,
`data:` lines) into a discriminated-union `TraceEvent` type mirroring chunk-4's schema
(`text | tool_call | tool_result | script_run | provenance | answer | done`). Unknown event
types are surfaced as a raw fallback rather than dropped (forward-compat with chunk-7/9 growth).
- *Why*: native `EventSource` can't POST; the contract requires the full conversation in the
  body. A hand-rolled parser over `fetch` streaming is the standard workaround and keeps the
  event typing in one place, testable against a mocked `ReadableStream`.
- *Alternatives*: `@microsoft/fetch-event-source` (rejected — an extra dep for ~40 lines we can
  own and test); WebSocket (rejected — backend speaks SSE).

### D4 — Trace timeline renders a component per event type, appended in stream order
The chat view keeps `messages` client-side (statelessness: the full array is re-sent each turn).
Each assistant turn owns an expandable timeline; events are appended as they arrive and rendered
by a per-type component: `tool_call` (name + args), `tool_result` (bindings/rows, truncated with
expand), `script_run` (source + stdout/stderr + exit code + sandbox id), `provenance` (chips
linking NIST DOI / ORNL report + ontology version), `answer` (grounded/ungrounded badge +
aggregated provenance chain). `text` events stream into the answer bubble.
- *Why*: directly satisfies chunk-4's "every trace event type appears" acceptance and the
  "script source and provenance chips inspectable" M6 criterion; per-type components keep each
  independently vitest-able against fixture events.

### D5 — Review diff rendered from the detail payload's neighborhood + proposal triples
`GET /api/proposals/{id}` returns proposed triples, evidence (sentence + `citedIn` + offsets),
and a one-hop affected ontology neighborhood. The diff view overlays proposed triples on the
neighborhood and highlights added nodes/edges (e.g. new `solubility` property, new `Moderator`
class + `moderatedBy` edge). Editable placement/unit fields drive `PUT …/graph`; approve/reject
call their endpoints; a raw-triples advanced view shows the unrendered graph. SHACL rejections on
approve/edit (typed error from chunk 9) surface as a legible message, leaving the proposal
`pending`.
- *Why*: matches chunk-9's detail contract and the M6 acceptance (reviewer sees `solubility` as a
  visual diff, sets its unit, approves; `graphite` shows the new class + relation).
- *Alternatives*: a full graph-visualization lib (rejected for the POC — a focused
  node/edge-list diff with highlighting is enough and far cheaper to test; can be revisited).

### D6 — Small dependency surface, vitest for tests
SvelteKit + Vite + TypeScript + `adapter-static`; vitest + `@testing-library/svelte` for
component tests (repo UI standard). No component/UI framework beyond Svelte; minimal hand-rolled
styling. API access through one typed client module (`lib/api.ts`) so every fetch is mockable.
- *Why*: keeps the dependency/build surface small for a demo, honors the repo testing standard,
  and isolates all network calls behind one mockable module.

## Risks / Trade-offs

- **Shared `newMux` conflict with in-flight chunk 9** → keep the static-handler change to one
  additive block at the root pattern, register it as catch-all, and pin routing with a test;
  rebase on chunk 9 before merge (its branch is `worktree-apply-ontology-changes`).
- **SPA fallback swallowing `/api/*` typos as HTML** → the fallback triggers only for non-`/api`,
  non-`/healthz` paths; `/api/*` misses return JSON/404 from the mux. Covered by a routing test.
- **SSE parser edge cases** (chunked event boundaries, partial `data:` lines, keep-alives) →
  buffer across reads and split only on complete `\n\n` frames; test with a fixture stream that
  splits an event across chunk boundaries.
- **Contract drift** if chunk 7/9 add event types or fields → the parser keeps a raw fallback for
  unknown event types and the client tolerates extra JSON fields, so new data renders (degraded)
  rather than crashing.
- **Embed requires build-before-compile** → the Dockerfile multi-stage (node build → Go build)
  and a Makefile target enforce ordering; a committed placeholder keeps `go build` working when
  the frontend hasn't been built locally (documented in tasks).
- **Backends not yet merged** → all component tests run against mocked SSE/API; live end-to-end
  verification (the density question, the `solubility`/`graphite` review, demo reset) is gated on
  chunks 4 and 9 being merged and is called out as a manual acceptance step.

## Open Questions

- **Embed placeholder strategy**: commit a minimal placeholder `webapp/build/index.html` (so
  `//go:embed` and `go build` succeed pre-build) vs. generate it in the Makefile before `go
  build`. Leaning toward a committed placeholder overwritten by the real build, matching how the
  Docker multi-stage always rebuilds it. Resolve during implementation.
- **Dev proxy**: whether to add a Vite dev-server proxy to a locally running Go server for
  interactive development, or rely solely on mocked data + the embedded build. Not required for
  acceptance; decide if live iteration is needed.
