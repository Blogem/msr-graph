## Why

Grounding in the mining → triage → proposal pipeline is enforced per candidate **term**, not per **triple**. A mined term (e.g. "confinement") carries real evidence spans, but every TBox axiom the pipeline builds *around* that term — its placement in the ontology and any companion relations — is emitted with no evidence and no gate that could reject it. This let an invented, meaningless object property (`msr:safetyFunctionedBy`, produced by a POC string heuristic in `_companion_relation_name`) ride inside the grounded `class-confinement` bundle and get approved into `urn:msr:ontology` at `owl:versionInfo 0.7.0`; the same boilerplate now sits in ~52 pending safety-class proposals. The system's "everything is grounded, everything is auditable" contract is false for the exact triples that decide the ontology's shape.

## What Changes

- **BREAKING (proposal graph shape):** every *asserted* triple in a change-proposal bundle must carry its own evidence link to a verbatim source span; evidence moves from being attached only to the `msr:ChangeProposal` resource to being attached per triple.
- **Strict span-or-reject placement.** A class's placement axiom (`rdfs:subClassOf` / broader-class) and any concept-to-concept relation (domain/range, object properties) are emitted **only** when a source span states the claim, validated by a text-containment check against the document. No justifying span → the axiom is not asserted; the class is still proposed (existence + evidence), and its placement becomes an explicit reviewer action.
- **Remove the mechanical companion-property emitter.** Delete `_companion_relation_name` and the unconditional `owl:ObjectProperty` block in `proposals._class_block`. Concept-to-concept relations come only from the evidence-required linking pass (`safety-property-linking`'s `servedByProperty`/`addressesFunction`).
- **Grounding gate at staging (and mirrored on approve).** Classify each bundle triple as *assertion-required* vs *scaffolding-exempt* (type declaration of the grounded term, individual `rdf:type`, `prov:*`), and reject any assertion-required triple lacking a span-backed evidence link before it can be staged or routed to core.
- **Review UI surfaces per-triple grounding**, so approving a grounded existence claim cannot silently drag an ungrounded axiom in with it.
- **Cleanup migration.** Remove `msr:safetyFunctionedBy` from `urn:msr:ontology` and strip it from the ~52 pending proposals.

## Capabilities

### New Capabilities
<!-- none — this tightens requirements on existing capabilities rather than introducing a new one -->

### Modified Capabilities
- `change-proposal-schema`: proposal bundles gain a per-triple evidence model; asserted triples reference their span(s) rather than the proposal carrying one undifferentiated evidence set.
- `candidate-triage`: for any placement or relation it proposes, triage must return the justifying source quote; a placement with no quote is dropped, not asserted (removes the free `broaderClass` assertion).
- `safety-ontology-evolution`: class proposals no longer auto-emit a companion object property or a guessed broader-class; placement is asserted only from a stated span.
- `proposal-staging`: adds a grounding gate that rejects assertion-required triples lacking span-backed evidence, with an enumerated scaffolding-exempt set.
- `approval-typed-routing`: the approve path mirrors the grounding gate so an ungrounded axiom cannot be routed into `urn:msr:ontology`/`urn:msr:data`.
- `review-ui`: the proposal detail shows evidence (or its absence) per triple.

## Impact

- **Extraction (Python):** `proposals.py` (`_class_block`, `_companion_relation_name`, `_proposal_graph_triples`, `_staging_resource_block`, `build_proposal_bundle`), `triage.py` (`classify`, `_SAFETY_GENRE_GUIDANCE`, response schema), `mining_types.py`; reuses the novelty-detection span-containment check.
- **Server (Go):** `cmd/server/proposals.go`, `internal/proposal` (approve/routing) for the mirrored gate.
- **Frontend:** review-surface proposal detail (per-triple evidence rendering).
- **Data / ops:** one-shot cleanup migration against the live `msr` repo (removes `msr:safetyFunctionedBy` from ontology + pending proposals). The current graph is left as-is until this change is implemented.
- **SHACL:** `deploy/graphdb/msr-shapes.ttl` — considered as an alternative enforcement point; may add a shape asserting evidence on proposed axioms (decided in design).
