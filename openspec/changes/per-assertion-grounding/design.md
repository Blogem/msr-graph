## Context

The mining → triage → proposal pipeline grounds the mined **candidate term** (real document-frequency + evidence spans with offsets) but not the TBox axioms built around it. `proposals._class_block` unconditionally mints a companion `owl:ObjectProperty` via `_companion_relation_name` (a POC string heuristic scoped to `Moderator → moderatedBy`); applied to `SafetyFunction` it produced `msr:safetyFunctionedBy` — range `SafetyFunction`, no domain, no evidence. The triage-chosen `broaderClass` is likewise asserted with no justifying span. Evidence attaches only to the `msr:ChangeProposal` resource (`_staging_resource_block`, `msr:hasEvidence`); the axioms in `_proposal_graph_triples` carry none. No gate rejects an ungrounded axiom: the QUDT guard only inspects unit/quantity-kind slots, `safe_type_ref` is a syntactic injection check, SHACL shapes target instances/edges not `owl:ObjectProperty` declarations, and the Go approve path routes any `owl:ObjectProperty`/`rdfs:range` triple to `urn:msr:ontology` by RDF type. Result: `msr:safetyFunctionedBy` is live in `urn:msr:ontology` at `owl:versionInfo 0.7.0`, and ~52 pending safety-class proposals carry the same boilerplate.

The span infrastructure to fix this already exists: the miner captures `startOffset`/`endOffset`/`citedIn` per evidence sentence, and `novelty-detection` validates candidate evidence by text-containment against the document.

## Goals / Non-Goals

**Goals:**
- Every asserted (non-scaffolding) triple in a proposal bundle is backed by a verbatim source span, verified by containment against the source document.
- Placement (`rdfs:subClassOf`/broader-class) and concept-to-concept relations are asserted only when a span states them (strict span-or-reject); otherwise the class is proposed without that axiom and placement is a reviewer action.
- The mechanical companion-property emitter is removed entirely.
- A grounding gate at staging, mirrored at approval, makes an ungrounded axiom impossible to stage or promote.
- The reviewer can see grounding per triple.
- The live `msr:safetyFunctionedBy` junk is removed from the ontology and from pending proposals.

**Non-Goals:**
- Grounding placements the documents only *imply* (never state verbatim). Strict span-or-reject deliberately drops these; they become manual reviewer placements. (This is the user-chosen trade-off.)
- Re-running the safety mine or re-approving the three fundamental safety functions (already accepted in `ingest-iaea-safety`; only the junk companion property is removed).
- Changing approval-typed-routing's routing-by-type mechanics — grounded triples route exactly as today; only a grounding precondition is added.
- General English morphology / auto-naming of relations — relations come from the evidence-required linking pass, not from generation.

## Decisions

### D1 — Per-triple evidence via RDF-star reification, resolvable in the proposal graph
Attach evidence to the asserted triple, not the proposal resource. **Chosen: RDF-star** (`<< ?s ?p ?o >> msr:hasEvidence ?ev`) because GraphDB 11.4 supports it natively and it keeps the asserted triple as a first-class triple that still routes by type on approval, with the annotation as a separable layer that is *not* copied to core. *Alternative — RDF standard reification* (`rdf:Statement`/`rdf:subject`…): more verbose, pollutes the proposal graph with statement nodes, and the routing filters would need to learn to skip them. *Alternative — a side "evidence-of" node keyed by a triple hash*: brittle and non-standard. The proposal-level `msr:hasEvidence` (aggregate) is retained for the existing evidence panel; per-triple annotations are additive.

### D2 — Reuse the novelty-detection containment check for quote verification
Triage returns, per asserted placement/relation, a `quote` field. The proposal builder verifies the quote occurs in the candidate's source document text using the same normalization/containment logic `novelty-detection` already applies to candidate evidence, and resolves it to `startOffset`/`endOffset`/`citedIn`. A quote that does not occur is treated as no quote → the axiom is dropped. This keeps "grounded" meaning one thing across the codebase.

### D3 — Triage schema gains per-assertion quotes; unjustified placements are dropped, not rejected
Extend the triage JSON schema so `broaderClass` (and relation domain/range) may be accompanied by a `quote`. App-side validation (existing "Model output is validated app-side" requirement) drops an assertion lacking a verifiable quote but keeps the candidate's existence proposal. This preserves discovery: we still surface the new class; we just don't fabricate where it sits. *Alternative — reject the whole candidate when placement is unjustified*: rejected, because it would throw away legitimately-discovered classes for the common case where the doc names the concept but not its taxonomy.

### D4 — Remove `_companion_relation_name` and the `_class_block` ObjectProperty block outright
No feature flag. The companion property was never grounded and never correct; `moderatedBy` was the same hack. Concept-to-concept relations are produced only by the `safety-property-linking` extraction pass, which is already spec'd to assert `servedByProperty`/`addressesFunction` only from a stated span. The `change-proposal-schema` and `approval-typed-routing` example scenarios that referenced the auto-generated `moderatedBy` are updated.

### D5 — Grounding gate lives in `build_proposal_bundle`, mirrored in the Go approve path
The Python gate (in `build_proposal_bundle`, beside the QUDT guard) is the primary defense and rejects at authoring time. The Go mirror (in `internal/proposal` before routing) is defense-in-depth for **legacy** proposals staged before this change (e.g. the ~52 pending ones), so approval refuses them even though Python never re-runs on them. Both classify triples by the same enumerated assertion-required vs scaffolding-exempt rule. *Alternative — SHACL-only enforcement*: rejected as sole mechanism because SHACL shapes are structural (targetClass/targetSubjectsOf) and cannot express "this axiom must have an evidence annotation" without awkward RDF-star shapes; a SHACL shape MAY be added as a third layer but is not the primary gate.

### D6 — Enumerated scaffolding-exempt set
Exactly: the `owl:Class` type declaration of the grounded term; the candidate individual's `rdf:type`; `prov:wasDerivedFrom`/`wasGeneratedBy`/`generatedAtTime` and other `prov:*` edges; `msr:autoAccepted`. Everything else asserted (`rdfs:subClassOf`, broader-class, `owl:ObjectProperty`/`owl:DatatypeProperty` declarations, `rdfs:domain`/`rdfs:range`, SKOS placement) is assertion-required. The set is defined once in `change-proposal-schema` and consumed by both gates.

## Risks / Trade-offs

- **Fewer auto-proposed placements** → Strict grounding means many classes arrive without a broader-class axiom, increasing manual reviewer placement. Mitigation: this is the accepted trade-off; the review UI makes placement a first-class edit (existing "Editable placement" requirement), so the reviewer path already exists.
- **RDF-star annotations must not leak into core on approval** → routing copies asserted triples by type; the `<< >>` annotations must be excluded from the copy. Mitigation: routing filters already select concrete `?s ?p ?o`; add an explicit test that no `msr:hasEvidence` annotation reaches `urn:msr:ontology`/`urn:msr:data`.
- **Quote containment false-negatives** (OCR artifacts, whitespace) → a real placement quote may fail containment and be dropped. Mitigation: reuse the *same* normalization novelty-detection uses (it already tolerates the corpus OCR), and log dropped assertions so calibration is visible.
- **Legacy pending proposals** (~52) carry the ungrounded companion → they would fail the new approve gate. Mitigation: the cleanup migration strips the companion triples from them so they remain approvable for their grounded content.

## Migration Plan

1. Ship the code (gate + companion-property removal + per-triple evidence) behind no flag; new mines produce grounded bundles.
2. One-shot cleanup against the live `msr` repo, idempotent:
   - `DELETE` `msr:safetyFunctionedBy ?p ?o` (and `?s ?p msr:safetyFunctionedBy`) from `urn:msr:ontology`.
   - For each pending `urn:msr:proposal/{id}` graph, `DELETE` the `msr:safetyFunctionedBy` companion triples.
   - Do **not** touch the three approved `msr:SafetyFunction` individuals or the class.
   - `owl:versionInfo` is not rolled back (0.7.0 stays; the bump history is immutable provenance); optionally record a cleanup `prov:Activity`.
3. Verify: `ASK` `msr:safetyFunctionedBy` absent from all graphs; `GET /api/proposals` still 618 rows, 0 dups; the three safety functions intact.

**Rollback:** the cleanup only deletes the invented property; if needed the code change is revertable and the deleted triples are reconstructable from the archived proposal graphs (retained as audit records per approval-typed-routing).

## Open Questions

- Should the Go approve-path mirror gate hard-fail legacy ungrounded proposals, or auto-strip known-scaffolding-adjacent junk (like the companion property) the way the migration does? Current lean: hard-fail + rely on the migration to clean pending proposals, so the gate stays a pure check.
- Does the review UI need a bulk "these N triples are ungrounded" affordance for legacy proposals, or is per-triple marking enough? Lean: per-triple marking is enough for the ~52 one-off; revisit if ungrounded legacy volume grows.
