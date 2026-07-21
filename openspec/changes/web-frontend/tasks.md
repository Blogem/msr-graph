## 1. Project scaffold

- [x] 1.1 Initialize a SvelteKit + TypeScript project in `webapp/` (Vite, `@sveltejs/adapter-static` with `fallback: index.html`, build output to a directory the Go embed reads, e.g. `webapp/build/`)
- [x] 1.2 Add vitest + `@testing-library/svelte` as dev dependencies and a `test` script
- [x] 1.3 Update `.gitignore`/`.dockerignore` to exclude `webapp/node_modules` and the build output (keep any committed embed placeholder tracked)
- [x] 1.4 Add the app shell layout with client-side navigation across the three surfaces (chat `/`, review `/review`, admin `/admin`)

## 2. Typed API client and SSE parser (`webapp/src/lib`)

- [x] 2.1 Create a single `lib/api.ts` typed client wrapping the chunk-9 proposal + checkpoint endpoints, typed to the concrete merged shapes (design D7): queue `{proposals:[{id,kind,status,term,docFrequency}]}`; detail `{id,triples[],evidence[],neighborhood[]}` (triple `{subject,predicate,object,objectType,datatype?,lang?}`, evidence `{text,citedIn,startOffset,endOffset}`); edit `PUT …/graph` body `{triples:"<full serialized graph>"}` (whole-graph replace); approve `POST …/approve` body `{reviewer,timestamp}` (empty body → 400); reject `POST …/reject` (no body); checkpoints list `{checkpoints:[{label,ontology_version}]}`, create `POST` body `{label}` → 201 manifest, restore `POST …/{label}/restore`. Every call mockable.
- [x] 2.2 Define the `TraceEvent` discriminated union mirroring the chunk-4 SSE schema (`text | tool_call | tool_result | script_run | provenance | answer | done`) plus a raw fallback for unknown types
- [x] 2.3 Implement `streamChat(messages, onEvent)` using `fetch` + `response.body.getReader()`, buffering across chunk boundaries and splitting on complete SSE frames into `TraceEvent`s
- [x] 2.4 Parse the typed error body `{error, message, violations?}`: map `400` (bad_request/invalid_label), `404` (not_found), `409` (invalid_transition), and the SHACL `422` with `violations[]` (each `{focusNode,constraint,shape,path,message}`) so callers can render legible messages

## 3. Chat surface (`chat-ui`)

- [x] 3.1 Conversation pane holding full history client-side and POSTing it in full per turn; append the assistant reply to history after `done`
- [x] 3.2 Per-turn expandable trace timeline appending events in stream order
- [x] 3.3 Per-event-type components: `tool_call` (name + args), `tool_result` (bindings/rows, truncated + expand), `script_run` (source + stdout/stderr + exit code + sandbox id), streamed `text` into the answer bubble
- [x] 3.4 `provenance` chips (dataLocator, dataset DOI, `citedIn` document link, ontology version), tolerating an empty `citedIn`
- [x] 3.5 `answer` groundedness stamp: grounded shows the aggregated provenance chain, ungrounded is flagged unsourced
- [x] 3.6 Raw fallback rendering for unrecognized event types (does not break the stream)

## 4. Review surface (`review-ui`)

- [x] 4.1 Proposal queue from `GET /api/proposals` with a status filter (pending/approved/rejected), showing id, kind, status, term, docFrequency
- [x] 4.2 Proposal detail from `GET /api/proposals/{id}`; render proposed triples overlaid on the affected ontology neighborhood as a highlighted diff (added nodes/edges); handle `404` as a not-found state
- [x] 4.3 Evidence panel: sentence text, `citedIn` document link, start/end offsets
- [x] 4.4 Editable placement/unit fields that re-serialize the **full** proposal graph and persist via `PUT /api/proposals/{id}/graph` (`{triples}` whole-graph replace); never send an empty `triples` body
- [x] 4.5 Approve (sending `{reviewer, timestamp}`) / reject controls calling their endpoints; reflect the resulting status and remove approved/rejected from the pending queue
- [x] 4.6 Surface a `422` SHACL validation error legibly on approve/edit — render the `violations[]` detail (path/constraint/message) — leaving the proposal pending
- [x] 4.7 Raw-triples advanced view

## 5. Admin surface (`admin-ui`)

- [x] 5.1 Checkpoint list from `GET /api/checkpoints`
- [x] 5.2 Create-checkpoint form calling `POST /api/checkpoints`; refresh the list on success; surface a rejected-label error
- [x] 5.3 Restore control calling `POST /api/checkpoints/{label}/restore` behind a confirmation

## 6. Server embed and static serving (`frontend-app-shell`)

- [x] 6.1 Add a `//go:embed` of the built frontend directory to the server (mirroring `internal/store`'s embed precedent); commit a minimal placeholder so `go build` succeeds before a local frontend build
- [x] 6.2 Add a static-asset + SPA-fallback handler serving embedded files, with `index.html` fallback for non-`/api`, non-`/healthz` `GET`s that match no asset
- [x] 6.3 Register the handler on the merged `newMux(chat, gr, ps, cs)` in `cmd/server/handler.go` at the root pattern (`/`) and thread it through the `main.go` call site; do not alter chunk 9's params or its Go 1.22 method-scoped `/api/*` routes (they win by specificity regardless of order)
- [x] 6.4 In the static handler, explicitly return `404` for any path beginning with `/api/` (the `/` catch-all would otherwise serve the SPA for an unknown `/api/*` path)

## 7. Build wiring

- [x] 7.1 Add a Makefile target that builds the frontend (`npm ci && npm run build`) into the Go embed directory
- [x] 7.2 Add a Dockerfile node build stage before the Go build stage so embedded assets exist at compile time; produce the single `server` binary with the frontend embedded
- [x] 7.3 Ensure the existing `make build`/image build path runs the frontend build first (ordering enforced)

## 8. Tests

- [x] 8.1 vitest: SSE parser — parses each event type; correctly reassembles an event split across chunk boundaries; unknown event type yields the raw fallback
- [x] 8.2 vitest: trace timeline against a mocked SSE stream — every event type renders; `script_run` source + output visible; provenance chips visible (incl. empty `citedIn`); grounded and ungrounded `answer` stamps render
- [x] 8.3 vitest: review diff render — added nodes/edges highlighted for the `solubility` (property) and `graphite` (class + `moderatedBy`) fixtures; not-found state on `404`
- [x] 8.4 vitest: review flows against a mocked API — queue filter, edit (unit → mole fraction) via `PUT`, approve/reject status changes, and SHACL-error surfacing leaving the proposal pending
- [x] 8.5 vitest: admin flows against a mocked API — list, create (incl. rejected-label error), restore-with-confirmation
- [x] 8.6 Go: `newMux` routing test — `/api/chat` and a representative `/api/proposals` path route to their handlers (not the SPA); `/healthz` unchanged; an unknown `/api/*` path is not served the SPA; `GET /` and a deep link (`/review`) serve `index.html`

## 9. Acceptance and verification

- [x] 9.1 `cd webapp && npm run test` passes; `go test ./cmd/server/...` passes; `go build ./...` succeeds with the frontend embedded
- [x] 9.2 Rebase on chunk 9 (`worktree-apply-ontology-changes`) and confirm all `/api/proposals*` and `/api/checkpoints*` routes plus the static handler coexist on `newMux`
- [ ] 9.3 Manual (requires chunks 4 + 9 merged and services up): the density question renders a full trace incl. script source and provenance chips; the reviewer sees the `solubility` proposal as a visual diff, sets its unit to mole fraction, and approves; the `graphite` proposal shows the new class + `moderatedBy`; restoring a pre-demo checkpoint from admin lets the evolution demo re-run end-to-end
