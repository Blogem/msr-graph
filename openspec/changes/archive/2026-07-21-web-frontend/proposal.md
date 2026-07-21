## Why

The grounded-analysis agent (chunk 4) and the proposal/checkpoint governance engine (chunk 9)
are both reachable only over HTTP/SSE — there is no user-facing surface that lets a person ask
the density question and watch it get answered, review an ontology-evolution proposal as a
visual diff, or reset the store for a fresh demo run. Chunk 10 is the milestone that puts
**both demos in one app** (M6): the whole POC becomes something you open in a browser rather
than something you exercise with `curl`.

## What Changes

- Add a single **SvelteKit** app (static adapter) **embedded in the `server` binary** — one
  deployable, no separate frontend service. The Go server serves the built static assets and an
  SPA fallback alongside its existing `/api/*` and `/healthz` routes, which are unchanged.
- **Chat surface**: a conversation pane that holds the full history client-side and POSTs it in
  full per turn (stateless), consumes the `POST /api/chat` SSE stream via `fetch` streaming
  (native `EventSource` can't POST), and renders a per-turn expandable **trace timeline** for
  every chunk-4 event type — `text`, `tool_call`, `tool_result`, `script_run` (source +
  stdout/stderr), `provenance` chips (NIST DOI / ORNL reports + ontology version), and the
  `answer` groundedness stamp.
- **Review surface**: a proposal queue filtered by status; a proposal detail view with a
  **rendered ontology-neighborhood diff** (new nodes/edges highlighted), an evidence panel
  (source spans + document links), editable placement/unit fields, approve/edit/reject controls,
  and a raw-triples advanced view — consuming the chunk-9 proposal API.
- **Admin surface**: checkpoint list / create / restore, so a pre-demo checkpoint can be
  restored to re-run the evolution demo end-to-end.
- Wire the frontend build (npm build → static output → Go `embed`) into the **Dockerfile**
  (multi-stage) and **Makefile**, so `make build` / the image build produces the single binary.

No backend API changes: the frontend consumes the chunk-4 chat contract and the chunk-9
proposal/checkpoint API exactly as specified, with no direct store access.

## Capabilities

### New Capabilities
- `frontend-app-shell`: the single SvelteKit app (static adapter) embedded in the Go server
  binary as one deployable — client-side routing across the three surfaces, the Go server
  serving static assets + SPA fallback without altering `/api/*` or `/healthz`, and the
  build/embed pipeline wired into the Dockerfile and Makefile.
- `chat-ui`: the chat surface — stateless full-history conversation, SSE consumed via `fetch`
  streaming, and the per-turn trace timeline rendering every chunk-4 event type incl. script
  source, provenance chips, and the groundedness stamp.
- `review-ui`: the review surface — status-filtered proposal queue, proposal detail with a
  rendered ontology-neighborhood diff, evidence panel, editable placement/unit fields,
  approve/edit/reject, and a raw-triples advanced view.
- `admin-ui`: the admin surface — checkpoint list / create / restore driving the chunk-9
  checkpoint API for demo reset.

### Modified Capabilities
<!-- None. The chat-api and proposal/checkpoint APIs are consumed as-is; their requirements do
     not change. The server mux gains static-asset serving, which is a NEW requirement owned by
     frontend-app-shell, not a change to an existing spec. -->

## Impact

- **New code**: `webapp/` SvelteKit project (currently only a `.gitkeep`) — routes, components,
  API client, SSE parser, vitest suite.
- **Shared server surface** (coordinate with chunk 9 `apply-ontology-changes`, in flight):
  `cmd/server/handler.go` (`newMux`) gains a static-asset + SPA-fallback handler and a Go
  `//go:embed` of the built frontend. Chunk 9 adds the `/api/proposals*` and `/api/checkpoints*`
  routes to the same `newMux`; both are additive — keep the static handler registered last as
  the catch-all so it never shadows an `/api/*` route.
- **Build/tooling**: `Dockerfile` (multi-stage: node build → embed → Go build), `Makefile`
  (frontend build target), `.dockerignore`/`.gitignore` (node_modules, build output).
- **Consumed contracts** (unchanged): chunk-4 `chat-api` (`POST /api/chat` SSE), chunk-9
  `proposal-review-api` + `store-checkpoint-restore`.
- **Dependencies**: chunk 4 (chat) and chunk 9 (governance API) must be merged before the app
  can exercise live endpoints; component tests run against mocked SSE/API and do not require
  either service running.
