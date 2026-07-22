## 1. Backend — read & preview endpoints

- [ ] 1.1 Add `GET /api/ontology/classes` handler returning `{iri, label}` for ontology classes via the staging-inclusive read path (`cmd/server/proposals.go` or a new file), registered in `cmd/server/handler.go`.
- [ ] 1.2 Add `GET /api/units` handler serving the vendored `ontology/qudt-units.json` allowlist as `{iri, label}`.
- [ ] 1.3 Add `GET /api/proposals/{id}/preview` handler that reuses `internal/proposal` routing to report per-graph triple counts + resulting ontology version, without mutating any graph; `404` on unknown id.
- [ ] 1.4 Register all three routes and confirm non-`GET` methods return `405`.

## 2. Backend — enriched detail response

- [ ] 2.1 Compute the derived kind ("datatype property"/"object property"/"class"/…) from the proposal's `rdf:type`/predicate triples and add it to the `GET /api/proposals/{id}` response.
- [ ] 2.2 Surface suggested-vs-asserted placement/unit with confidence, witness-instance references, and the `confirm`/`needs-decision` decision state in the detail response (fields from `evidence-graded-ontology-growth`).

## 3. Frontend — API bindings & types

- [ ] 3.1 Add `api.ts` bindings + wire types for `getOntologyClasses`, `getUnits`, `getProposalPreview`, and the enriched proposal detail (derived kind, suggested/asserted + confidence, witnesses, decision state).

## 4. Frontend — typed, kind-aware placement/unit

- [ ] 4.1 Build a parent-class picker (typeahead over `getOntologyClasses`) and a unit picker (over `getUnits`), each pre-filled with the suggested value + confidence; allow an explicit custom entry.
- [ ] 4.2 Hide fields irrelevant to the derived kind (no unit for class; no parent for property).
- [ ] 4.3 Render suggested values as tentative/confidence-bearing and distinct from asserted; wire confirm/override to the existing whole-graph `PUT` (reuse/replace the `triples.ts` serialization; drop the free-text IRI-vs-literal regex heuristic).

## 5. Frontend — approval, impact, layout

- [ ] 5.1 Move approve/reject to a prominent top-of-detail action bar.
- [ ] 5.2 Disable approve while `needs-decision`/unconfirmed, naming the unresolved item(s); enable once resolved.
- [ ] 5.3 Show the impact preview (per-graph counts + version delta from `getProposalPreview`) adjacent to the approve control.

## 6. Frontend — diff, witnesses, queue

- [ ] 6.1 Add a diff legend and distinguish existing / added-by-proposal / added-by-your-edit in `DiffView.svelte`.
- [ ] 6.2 Add the derived-kind statement to the detail header.
- [ ] 6.3 Add a promotion witness panel listing witness instances + their evidence.
- [ ] 6.4 Sort the queue by likelihood (confidence/decision-state/evidence), most-likely first, within the active status filter.

## 7. Tests

- [ ] 7.1 Backend: `classes`/`units` endpoints return expected shapes; wrong method → `405`.
- [ ] 7.2 Backend: `preview` reports routing counts + version and mutates nothing; asserts parity with the approve path's routing (same code) and `404` on unknown id.
- [ ] 7.3 Backend: detail response includes derived kind, suggested-vs-asserted + confidence, witnesses, and decision state (table-driven over kinds).
- [ ] 7.4 Frontend: pickers populate from the endpoints and pre-fill the suggestion; irrelevant fields hidden per kind.
- [ ] 7.5 Frontend: approve disabled for `needs-decision`, enabled after confirm/override; confirming a suggestion issues the whole-graph `PUT` with value moved suggested→asserted.
- [ ] 7.6 Frontend: impact preview renders counts + version; diff legend distinguishes the three states incl. an added-by-your-edit triple; witness panel renders; queue orders confident above needs-decision.
- [ ] 7.7 Run suites: `go test ./cmd/server/...` and `cd webapp && npm run test && npm run check`.

## 8. Validation & docs

- [ ] 8.1 `openspec validate guided-proposal-review --strict` passes.
- [ ] 8.2 Update review-UI docs to describe pickers, impact preview, hard-block approval, witness panel, and queue ordering.
