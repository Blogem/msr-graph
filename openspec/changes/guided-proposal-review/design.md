## Context

The review UI (`webapp/src/lib/review/`) renders a proposal as a node/edge diff + evidence panel, with free-text placement/unit fields (`triples.ts` guesses IRI-vs-literal by regex) and small bottom-of-page approve/reject buttons. The API (`cmd/server/proposals.go`) exposes queue/detail/edit/approve/reject only — no class list, no unit list, no approval dry-run. The companion change `evidence-graded-ontology-growth` adds suggested-vs-asserted placement/unit, confidence, witness instances, and a needs-decision/confirm state to the proposal schema; this change makes the reviewer experience consume and act on them.

All five architectural decisions were resolved up front (see Decisions); this design records them and their consequences.

## Goals / Non-Goals

**Goals:**
- Replace unguided free text with typed, kind-aware pickers pre-filled from the model's suggestions.
- Make approval intent legible (impact preview) and safe (hard-block on undecided proposals).
- Render the new schema (suggested-vs-asserted, confidence, witnesses, decision state) faithfully.
- Keep routing logic single-sourced on the server.

**Non-Goals:**
- No change to approval/SHACL/graph-routing internals, auth, or the mining pipeline.
- The suggested-vs-asserted *visual treatment* is left to implementation, not fixed here.

## Decisions

### D1 — One change, shipped together (not split)
All UI work ships as this single change, landing after `evidence-graded-ontology-growth`. Rationale: most of the value (pickers, decision state, witnesses, impact preview) depends on the new schema, so splitting would ship a thin first half; one coherent review experience is worth the ordering constraint.

### D2 — Impact preview via a backend dry-run endpoint
`GET /api/proposals/{id}/preview` returns the routing breakdown (triples → vocab/ontology/data counts) and the resulting ontology version, computed by reusing `internal/proposal` routing — **not** re-derived in TypeScript. Rationale: the vocab/ontology/data partition is subtle SPARQL type-filter logic; duplicating it client-side would drift from the server's actual behavior. Alternative (client re-derivation) rejected for drift risk.

### D3 — New read endpoints feed the pickers
`GET /api/ontology/classes` (parent-class candidates) and `GET /api/units` (the vendored QUDT allowlist) back the placement and unit pickers. Rationale: the detail payload's one-hop neighborhood is too narrow to populate a picker, and the allowlist is a static file the server already reads. Alternatives (derive from neighborhood; embed allowlist in each bundle) rejected as narrow/duplicative.

### D4 — Hard-block approval on needs-decision / unconfirmed
Approve is disabled (with an explanation of what must be decided) while the proposal is `needs-decision` or carries unconfirmed suggestions. Rationale: this is a governance gate — a floating class or an off-allowlist unit should not reach the core graph on an accidental click. The reviewer must explicitly confirm or override every suggestion first.

### D5 — Confirming a suggestion reuses the whole-graph PUT
Confirming a suggested value (e.g. `msr:suggestedUnit` → asserted `msr:canonicalUnit`) is a client-computed transform persisted via the existing `PUT /api/proposals/{id}/graph`. Rationale: the transform is simple and keeps the server surface small; no dedicated confirm endpoint. The empty-graph guard already in `triples.ts` still applies.

### D6 — Derived kind computed server-side in the detail endpoint
The detail response gains a derived-kind label ("datatype property", "class", "object property", …) computed from the proposal's `rdf:type`/predicate triples, so the header states what will actually be added rather than echoing the display `kind` pill. Rationale: the routing-relevant truth is the triples; computing it once server-side avoids each client re-implementing the type inference.

### D7 — Kind-aware fields hide (not disable) irrelevant inputs
Fields that don't apply to a kind are hidden entirely (no Unit for a class; no subClassOf for a property). Rationale: hiding is less confusing than a greyed-out control for a POC review tool.

### D8 — Queue sorted by likelihood, most-likely first
The queue orders proposals so more-likely candidates surface at the top (using the confidence/decision-state and evidence signals now on the proposal). Rationale: a reviewer should meet the strongest, ready-to-confirm proposals first; needs-decision/low-confidence sink down.

### D9 — Diff legend with edit-vs-proposal granularity
The diff distinguishes three states with a legend: existing (already in the KG), added-by-proposal, and added-by-your-edit (a triple the reviewer introduced this session). Rationale: a reviewer editing placement should see which additions are theirs versus the miner's.

## Risks / Trade-offs

- **Ordering coupling to the backend change** → Mitigation: this change declares the dependency explicitly; it renders fields that only exist once `evidence-graded-ontology-growth` lands.
- **Preview endpoint could drift from real approval** if routing changes → Mitigation: the endpoint *calls the same* `internal/proposal` routing code the approve path uses, not a copy.
- **Hard-block could trap a reviewer** if decision-state is mis-set → Mitigation: the block always names the specific unresolved item; overriding a suggestion is always available as the escape hatch.
- **Class list could be large** → Mitigation: the picker is a typeahead/autocomplete, and `GET /api/ontology/classes` returns a bounded, labeled list.
- **Suggested-vs-asserted visual left open** → Mitigation: deliberately deferred to implementation; the spec fixes behavior (tentative, confidence-bearing, confirmable), not pixels.

## Open Questions

- Does `GET /api/ontology/classes` return only classes eligible as parents for the proposal's kind, or all classes with the client filtering?
- Should the impact preview also show the SHACL shapes that *would* be checked, or just the routing/version delta?
- For a promotion proposal, does confirming placement re-type the witness instances in the preview, or is that only realized at approval?
