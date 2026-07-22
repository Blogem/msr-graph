## 1. Per-triple evidence data model (`change-proposal-schema`)

- [ ] 1.1 Define the enumerated scaffolding-exempt triple set (owl:Class decl of the grounded term, individual `rdf:type`, `prov:*`, `msr:autoAccepted`) as a single source-of-truth predicate/shape classifier in `extraction/src/msr_extraction/`, consumed by both the staging gate and the Go mirror
- [ ] 1.2 Choose and implement the RDF-star annotation shape `<< ?s ?p ?o >> msr:hasEvidence <span-iri>` for asserted triples; add a helper in `proposals.py` that emits an asserted triple together with its evidence annotation from a resolved span
- [ ] 1.3 Keep the proposal-level `msr:hasEvidence` aggregate (`_staging_resource_block`) unchanged for the existing evidence panel; per-triple annotations are additive
- [ ] 1.4 Verify with a serialization test that the RDF-star annotation round-trips through GraphDB 11.4 and is queryable per triple

## 2. Span verification and triage (`candidate-triage`)

- [ ] 2.1 Extract the novelty-detection text-containment/normalization check into a reusable function usable by the proposal builder to verify a quote occurs in a document and resolve it to `startOffset`/`endOffset`/`citedIn`
- [ ] 2.2 Extend the triage response schema so `broaderClass` and relation `domain`/`range` may carry a `quote`; update `_SAFETY_GENRE_GUIDANCE` and the prompt to require a verbatim quote for any proposed placement/relation
- [ ] 2.3 In app-side validation (`triage.py` / `mining_types.py`), drop an asserted placement/relation whose quote is missing or fails containment, while keeping the candidate's existence proposal; count dropped assertions for calibration logging

## 3. Remove the mechanical companion-property emitter (`safety-ontology-evolution`)

- [ ] 3.1 Delete `_companion_relation_name` and the unconditional `owl:ObjectProperty` block in `proposals._class_block`
- [ ] 3.2 Update `_class_block` to assert a broader-class placement only when triage supplied a verified span; otherwise emit the class + individual with existence evidence and no placement axiom
- [ ] 3.3 Update `_proposal_graph_triples` / `build_proposal_bundle` so every emitted assertion-required triple carries its per-triple evidence annotation

## 4. Grounding gate at staging (`proposal-staging`)

- [ ] 4.1 In `build_proposal_bundle`, beside the QUDT-allowlist guard, classify each bundle triple assertion-required vs scaffolding-exempt and reject the whole bundle if any assertion-required triple lacks a span-backed evidence annotation
- [ ] 4.2 Ensure the gate never fires on scaffolding-exempt triples; return a typed rejection reason distinct from the QUDT rejection

## 5. Approval mirror gate + routing (`approval-typed-routing`)

- [ ] 5.1 In `internal/proposal` (approve path), before routing, re-check that every assertion-required triple in the proposal graph carries an evidence annotation; refuse the approval (route nothing, leave pending, typed error) if any is ungrounded
- [ ] 5.2 Ensure routing copies only the concrete asserted triples by type and never copies `msr:hasEvidence` RDF-star annotations into `urn:msr:ontology`/`urn:msr:data`
- [ ] 5.3 Update `cmd/server/proposals.go` approve handler to surface the typed grounding error

## 6. Review UI per-triple grounding (`review-ui`)

- [ ] 6.1 Extend the proposal detail API response so each asserted triple exposes its evidence span (or absence) and whether it is scaffolding-exempt
- [ ] 6.2 Render per-triple grounding in the review surface: grounded triples show their span, ungrounded assertion triples are flagged, scaffolding triples marked grounding-not-applicable

## 7. Cleanup migration of live junk

- [ ] 7.1 Write an idempotent migration (extraction CLI subcommand or SPARQL script) that DELETEs `msr:safetyFunctionedBy` as subject and object from `urn:msr:ontology` and from every pending `urn:msr:proposal/{id}` graph, leaving the three approved `msr:SafetyFunction` individuals and the class untouched
- [ ] 7.2 Optionally record a cleanup `prov:Activity`; do not roll back `owl:versionInfo`
- [ ] 7.3 (manual, live) Run the migration against the `msr` repo; verify `ASK` `msr:safetyFunctionedBy` absent from all graphs, `GET /api/proposals` still 618 rows / 0 dups, the three safety functions intact

## 8. Tests

- [ ] 8.1 Unit: `_class_block` emits no companion property; asserts broader-class only with a verified quote; emits per-triple evidence annotations (table-driven)
- [ ] 8.2 Unit: quote-containment verification accepts an in-document quote and rejects an absent/hallucinated one (reuses novelty-detection normalization)
- [ ] 8.3 Unit: staging grounding gate rejects a bundle with an ungrounded assertion triple and passes a fully grounded bundle; scaffolding triples never trip it
- [ ] 8.4 Go: approve mirror gate refuses a proposal graph with an ungrounded axiom (route nothing, pending, typed error) and routes a fully grounded proposal by type; no RDF-star annotation reaches core
- [ ] 8.5 Webapp: proposal detail distinguishes grounded, ungrounded, and scaffolding triples (vitest + review-surface test)
- [ ] 8.6 Migration test: idempotent removal of `msr:safetyFunctionedBy` leaves the SafetyFunction class + individuals intact (opt-in integration against `msr-test`)
- [ ] 8.7 Regression: the three fundamental safety functions still produce grounded `class` proposals end-to-end with a span-backed placement where the source states it
