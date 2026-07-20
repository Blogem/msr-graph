## 1. Project scaffold

- [ ] 1.1 Initialize a SvelteKit + TypeScript project in `webapp/` (Vite, `@sveltejs/adapter-static` with `fallback: index.html`, build output to a directory the Go embed reads, e.g. `webapp/build/`)
- [ ] 1.2 Add vitest + `@testing-library/svelte` as dev dependencies and a `test` script
- [ ] 1.3 Update `.gitignore`/`.dockerignore` to exclude `webapp/node_modules` and the build output (keep any committed embed placeholder tracked)
- [ ] 1.4 Add the app shell layout with client-side navigation across the three surfaces (chat `/`, review `/review`, admin `/admin`)

## 2. Typed API client and SSE parser (`webapp/src/lib`)

- [ ] 2.1 Create a single `lib/api.ts` typed client wrapping the chunk-9 proposal + checkpoint endpoints (`GET /api/proposals[?status=]`, `GET /api/proposals/{id}`, `PUT /api/proposals/{id}/graph`, `POST …/approve`, `POST …/reject`, `GET|POST /api/checkpoints`, `POST /api/checkpoints/{label}/restore`), so every network call is mockable
- [ ] 2.2 Define the `TraceEvent` discriminated union mirroring the chunk-4 SSE schema (`text | tool_call | tool_result | script_run | provenance | answer | done`) plus a raw fallback for unknown types
- [ ] 2.3 Implement `streamChat(messages, onEvent)` using `fetch` + `response.body.getReader()`, buffering across chunk boundaries and splitting on complete SSE frames into `TraceEvent`s
- [ ] 2.4 Surface typed API errors (400 malformed, 404 unknown, and the chunk-9 SHACL validation error body) so callers can render legible messages

## 3. Chat surface (`chat-ui`)

- [ ] 3.1 Conversation pane holding full history client-side and POSTing it in full per turn; append the assistant reply to history after `done`
- [ ] 3.2 Per-turn expandable trace timeline appending events in stream order
- [ ] 3.3 Per-event-type components: `tool_call` (name + args), `tool_result` (bindings/rows, truncated + expand), `script_run` (source + stdout/stderr + exit code + sandbox id), streamed `text` into the answer bubble
- [ ] 3.4 `provenance` chips (dataLocator, dataset DOI, `citedIn` document link, ontology version), tolerating an empty `citedIn`
- [ ] 3.5 `answer` groundedness stamp: grounded shows the aggregated provenance chain, ungrounded is flagged unsourced
- [ ] 3.6 Raw fallback rendering for unrecognized event types (does not break the stream)

## 4. Review surface (`review-ui`)

- [ ] 4.1 Proposal queue from `GET /api/proposals` with a status filter (pending/approved/rejected), showing id, kind, status, term, docFrequency
- [ ] 4.2 Proposal detail from `GET /api/proposals/{id}`; render proposed triples overlaid on the affected ontology neighborhood as a highlighted diff (added nodes/edges); handle `404` as a not-found state
- [ ] 4.3 Evidence panel: sentence text, `citedIn` document link, start/end offsets
- [ ] 4.4 Editable placement/unit fields persisting via `PUT /api/proposals/{id}/graph`
- [ ] 4.5 Approve/reject controls calling their endpoints; reflect the resulting status and remove approved/rejected from the pending queue
- [ ] 4.6 Surface a typed SHACL validation error legibly on approve/edit, leaving the proposal pending
- [ ] 4.7 Raw-triples advanced view

## 5. Admin surface (`admin-ui`)

- [ ] 5.1 Checkpoint list from `GET /api/checkpoints`
- [ ] 5.2 Create-checkpoint form calling `POST /api/checkpoints`; refresh the list on success; surface a rejected-label error
- [ ] 5.3 Restore control calling `POST /api/checkpoints/{label}/restore` behind a confirmation

## 6. Server embed and static serving (`frontend-app-shell`)

- [ ] 6.1 Add a `//go:embed` of the built frontend directory to the server (mirroring `internal/store`'s embed precedent); commit a minimal placeholder so `go build` succeeds before a local frontend build
- [ ] 6.2 Add a static-asset + SPA-fallback handler serving embedded files, with `index.html` fallback for non-`/api`, non-`/healthz` `GET`s that match no asset
- [ ] 6.3 Register the handler on `newMux` in `cmd/server/handler.go` as the root (`/`) catch-all, resolving after `/api/*` and `/healthz`; keep the change to one additive block for a clean merge with chunk 9
- [ ] 6.4 Ensure `/api/*` paths matching no registered route return a not-found (not the SPA fallback)

## 7. Build wiring

- [ ] 7.1 Add a Makefile target that builds the frontend (`npm ci && npm run build`) into the Go embed directory
- [ ] 7.2 Add a Dockerfile node build stage before the Go build stage so embedded assets exist at compile time; produce the single `server` binary with the frontend embedded
- [ ] 7.3 Ensure the existing `make build`/image build path runs the frontend build first (ordering enforced)

## 8. Tests

- [ ] 8.1 vitest: SSE parser — parses each event type; correctly reassembles an event split across chunk boundaries; unknown event type yields the raw fallback
- [ ] 8.2 vitest: trace timeline against a mocked SSE stream — every event type renders; `script_run` source + output visible; provenance chips visible (incl. empty `citedIn`); grounded and ungrounded `answer` stamps render
- [ ] 8.3 vitest: review diff render — added nodes/edges highlighted for the `solubility` (property) and `graphite` (class + `moderatedBy`) fixtures; not-found state on `404`
- [ ] 8.4 vitest: review flows against a mocked API — queue filter, edit (unit → mole fraction) via `PUT`, approve/reject status changes, and SHACL-error surfacing leaving the proposal pending
- [ ] 8.5 vitest: admin flows against a mocked API — list, create (incl. rejected-label error), restore-with-confirmation
- [ ] 8.6 Go: `newMux` routing test — `/api/chat` and a representative `/api/proposals` path route to their handlers (not the SPA); `/healthz` unchanged; an unknown `/api/*` path is not served the SPA; `GET /` and a deep link (`/review`) serve `index.html`

## 9. Acceptance and verification

- [ ] 9.1 `cd webapp && npm run test` passes; `go test ./cmd/server/...` passes; `go build ./...` succeeds with the frontend embedded
- [ ] 9.2 Rebase on chunk 9 (`worktree-apply-ontology-changes`) and confirm all `/api/proposals*` and `/api/checkpoints*` routes plus the static handler coexist on `newMux`
- [ ] 9.3 Manual (requires chunks 4 + 9 merged and services up): the density question renders a full trace incl. script source and provenance chips; the reviewer sees the `solubility` proposal as a visual diff, sets its unit to mole fraction, and approves; the `graphite` proposal shows the new class + `moderatedBy`; restoring a pre-demo checkpoint from admin lets the evolution demo re-run end-to-end
