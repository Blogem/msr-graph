# Tasks: apply-ontology-changes

## 1. Graph client: repository-level ops

- [x] 1.1 Add `ExportRepo(ctx) ([]byte, error)` to `internal/graph` — `GET /repositories/{repo}/statements` with `Accept: application/x-trig`, returning all named graphs as one TriG document.
- [x] 1.2 Add `ClearRepo(ctx) error` — `DELETE /repositories/{repo}/statements` (no subject/predicate/object/context) to empty the repository.
- [x] 1.3 Add `ImportRepo(ctx, trig []byte) error` — `POST /repositories/{repo}/statements` with `Content-Type: application/x-trig`.
- [x] 1.4 Add a `ProposalGraph(id)` IRI builder (`urn:msr:proposal/{id}`, `{id}` = `{kind}-{term-slug}`) and, if a single-named-graph read is not cleanly expressible via `SelectRaw` + explicit `GRAPH`, a scoped-read helper — keeping endpoint knowledge inside the `graph` package. Note the Go client has no `Proposal` graph constant (chunk 8 was Python); proposal graphs are reached via `Update`/`SelectRaw`, never the `PutGraph` allowlist.
- [x] 1.5 Tests: unit tests for endpoint/verb/header construction with an `httptest` server; assert `ClearRepo` sends a context-less DELETE.

## 2. Approval typed-routing engine (`internal/proposal`)

- [x] 2.1 Define the engine type and the narrow graph interface it depends on (Select/SelectRaw/Update subset) so it is fakeable.
- [x] 2.2 Build the three filtered `INSERT { GRAPH <dest> } WHERE { GRAPH <proposal> } FILTER(...)` copies — vocab (skos:Concept + SKOS predicates), ontology (owl:Class/ObjectProperty/DatatypeProperty declarations, rdfs:subClassOf, rdfs:domain/range, msr:PhysicalProperty individuals with quantityKind/canonicalUnit), data (everything else).
- [x] 2.3 Concatenate the three copies + version bump + status flip + decision-provenance insert into one SPARQL UPDATE request so GraphDB commits them as a single transaction.
- [x] 2.4 Surface a GraphDB SHACL rejection as the existing typed `ValidationError` (reuse `graph.Update`'s detection), leaving the proposal `pending`.
- [x] 2.5 Tests (integration, dockerized GraphDB): approve `solubility` → triples in ontology+vocab, visible via core `Select`; approve the mixed `graphite` bundle → class+property in ontology, individual in data; SHACL-violating bundle rolls back with nothing in core; second approval adds no duplicate triples; proposal graph retained.

## 3. Proposal lifecycle: status, version bump, decision provenance

- [x] 3.1 Implement the version parser/bumper (parse major.minor.patch, drop pre-release suffix, minor++ / patch=0; current seed is `0.4.0` → `0.5.0`) and the scoped DELETE/INSERT of the single `owl:versionInfo` literal in `urn:msr:ontology`.
- [x] 3.2 Guard the bump and status flip on a genuine `pending → approved` transition (no double-bump on re-approval / restore-then-approve).
- [x] 3.3 Write the `urn:msr:run:approve/{id}` `prov:Activity` (wasAssociatedWith reviewer agent, request-supplied startedAtTime, link to the proposal) into `urn:msr:staging`, reusing the existing PROV-O TBox.
- [x] 3.4 Implement reject (status → rejected; no core copy, no version bump, proposal graph kept) and edit (replace `urn:msr:proposal/{id}` triples; status stays pending).
- [x] 3.5 Refuse invalid transitions (e.g. reject an approved proposal); no partial mutation.
- [x] 3.6 Tests: version parse/bump unit tests incl. `0.4.0`→`0.5.0` and `-seed` suffix; integration tests for reject-leaves-core-untouched, edit-persists-and-is-what-gets-promoted, no-second-bump, invalid-transition-refused, approval activity in staging (and nothing in urn:msr:provenance).

## 4. Checkpoint / restore engine (`internal/checkpoint`)

- [x] 4.1 Implement checkpoint: TriG export via `graph.ExportRepo` + SQLite `VACUUM INTO` on a dedicated (non-chat) connection + a manifest recording the ontology version, written under `data/checkpoints/{label}/`.
- [x] 4.2 Implement restore: `graph.ClearRepo` → `graph.ImportRepo(trig)` → replace the live `msr.db` with the checkpoint copy.
- [x] 4.3 Validate `{label}` against a conservative filesystem-safe charset before touching any path (reject path traversal).
- [x] 4.4 Tests (integration): checkpoint writes all three artifacts; checkpoint → approve → restore round-trip returns per-graph triple counts and SQLite content to the pre-checkpoint state and the version back; re-approval after restore reproduces the result; unsafe label rejected.

## 5. HTTP API + server wiring (`cmd/server`)

- [x] 5.1 Add JSON handlers for `GET /api/proposals` (queue, `status` filter), `GET /api/proposals/{id}` (proposal triples + evidence + one-hop ontology neighborhood), `PUT /api/proposals/{id}/graph`, `POST /api/proposals/{id}/approve`, `POST /api/proposals/{id}/reject`.
- [x] 5.2 Add JSON handlers for `GET /api/checkpoints`, `POST /api/checkpoints`, `POST /api/checkpoints/{label}/restore`.
- [x] 5.3 Register the new routes in `newMux` beside `/api/chat` and `/healthz`; enforce per-route method with 405; wire the engines in `main.go` (grant the server a writable graph client for approvals and a dedicated SQLite connection for checkpoints, without weakening the chat path's read-only SQLite).
- [x] 5.4 Map errors to the typed contract: 400 on malformed body, 404 on unknown id, and a SHACL `ValidationError` rendered as a structured error body.
- [x] 5.5 Tests: handler unit tests against a fake graph client — queue filtering, detail payload shape, 404, 405, 400, and a SHACL-rejection error body — with no live GraphDB.

## 6. Make targets & docs

- [x] 6.1 Add `make checkpoint` and `make restore` wrappers to the root `Makefile` (calling the API or the engine CLI), ordered after the pipeline targets.
- [x] 6.2 Update `docs/ARCHITECTURE.md` / relevant docs if the API field names or checkpoint layout differ from what is documented.

## 7. Validation

- [x] 7.1 `go build ./...` and `go vet ./...` pass.
- [x] 7.2 `go test ./...` passes (unit tests always; integration tests against a dockerized GraphDB per the repo's integration-test convention — do not point at the live `msr` repo).
- [x] 7.3 `openspec validate apply-ontology-changes --strict` passes.
- [ ] 7.4 Manual end-to-end with a **fixture proposal** (the miner does not yet produce good real candidates — that mechanism is still being worked on): insert a hand-written `solubility` (or `graphite`) `msr:ChangeProposal` + `urn:msr:proposal/{id}` graph into `urn:msr:staging` (same `client.Update` pattern the integration tests use), then `make checkpoint` → approve via the API (agent now answers solubility) → `make restore` reverts it → re-approve reproduces it.
- [ ] 7.5 **Deferred until the miner produces good candidates**: re-run the 7.4 flow end-to-end against real `make mine` output (real staged `solubility`/`graphite` proposals) rather than the fixture, to confirm the field shapes match what the miner actually writes.
