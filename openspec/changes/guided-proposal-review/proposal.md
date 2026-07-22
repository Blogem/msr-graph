## Why

The review UI makes the reviewer do work the system should do for them, and hides what approval will actually do. Placement and unit are **free-text boxes** with only placeholder hints — a value that doesn't look like an IRI is silently stored as a string literal and may only fail later as a SHACL 422. The same Unit/Placement fields show for **every** proposal kind even though a class has no unit and a property's placement is fixed. The Approve/Reject buttons are small and buried below the evidence and edit fields. Nothing tells the reviewer what a click will change (which graphs, which version bump), and the queue orders proposals arbitrarily. With `evidence-graded-ontology-growth` introducing suggested-vs-asserted placement/unit, confidence, witness instances, and a needs-decision state, the UI needs to *render* those so the reviewer can confirm-or-override instead of typing into the void.

## What Changes

- **Typed placement/unit pickers** replace free text: a parent-class picker sourced from the ontology and a unit picker sourced from the QUDT allowlist, pre-filled with the model's *suggested* value (and its confidence) where one exists, with confirm/override.
- **Kind-aware fields**: fields irrelevant to a proposal's kind are hidden (no Unit for a class; no subClassOf for a property).
- **Prominent, top-of-detail Approve/Reject** with an **impact/pre-approval preview** ("on approve: +N triples → ontology/data/vocab, version X→Y"), driven by a backend dry-run endpoint.
- **Hard-block approval** while a proposal is `needs-decision` (missing/low-confidence/off-allowlist placement or unit) or has unconfirmed suggestions.
- **Suggested-vs-asserted rendering**: a suggested value reads as tentative (with confidence) and distinct from a confirmed axiom; confirming persists via the existing whole-graph `PUT`.
- **Class-vs-property clarity**: the detail header states the *actual* type derived from the triples (e.g. "adds 1 datatype property"), computed by the backend and returned in the detail payload.
- **Diff legend with granularity**: distinguishes existing (in the KG) from added-by-proposal from added-by-your-edit.
- **Promotion witness panel**: for a promotion proposal, shows the witness instances (and their evidence) that justified class-hood.
- **Queue sorted by likelihood**, most-likely candidates first, with `needs-decision` surfaced.
- **New read/preview endpoints**: `GET /api/ontology/classes`, `GET /api/units`, and `GET /api/proposals/{id}/preview`; the detail endpoint is enriched with derived kind, suggested/asserted values + confidence, witnesses, and decision state.

## Capabilities

### New Capabilities
<!-- none — this refines existing review UI and API capabilities -->

### Modified Capabilities
- `proposal-review-api`: register + implement `GET /api/ontology/classes`, `GET /api/units`, and `GET /api/proposals/{id}/preview` (dry-run routing + resulting version); enrich `GET /api/proposals/{id}` with the derived kind label, suggested-vs-asserted placement/unit with confidence, witness references, and the needs-decision/confirm state.
- `review-ui`: typed kind-aware placement/unit pickers with suggested pre-fill + confidence; prominent top-of-detail approve/reject with impact preview; hard-block approval on needs-decision/unconfirmed; class-vs-property header from the derived kind; diff legend distinguishing existing / added-by-proposal / added-by-edit; promotion witness panel; queue sorted by likelihood.

## Impact

- **Depends on** `evidence-graded-ontology-growth`: this change *renders* the suggested-vs-asserted predicates, confidence, witness linkage, and needs-decision/confirm state that change introduces. It should land after that schema is in place.
- **Backend**: `cmd/server/proposals.go` (enriched detail response + derived-kind computation), new handlers for classes/units/preview, `cmd/server/handler.go` (route registration). The preview endpoint re-uses the `internal/proposal` routing logic rather than duplicating it client-side. The units endpoint serves the vendored `ontology/qudt-units.json` allowlist.
- **Frontend**: `webapp/src/lib/review/` — `ReviewSurface.svelte` (layout, prominent actions, queue sort, hard-block), `DiffView.svelte` (legend + edit-vs-proposal granularity), `triples.ts` (picker value handling replaces free-text serialization heuristics), new picker + impact-preview + witness-panel components, and `webapp/src/lib/api.ts` (new endpoint bindings).
- **Out of scope**: changes to the approval / SHACL / routing machinery itself; auth/multi-reviewer identity; the mining/proposal-generation pipeline (owned by `evidence-graded-ontology-growth`).
