## Why

The ontology-mining pipeline decides class-hood one-shot from a **single witness**: a `class`-kind candidate (e.g. "graphite") eagerly mints a brand-new `owl:Class` (e.g. `Moderator`) that lands as a **flat, parentless island** — no `rdfs:subClassOf`, plus one half-typed companion relation. This contradicts the seed ontology's own house style, which models specifics as **instances** (`msr:density a msr:PhysicalProperty`, `msr:FuelSalt a msr:SaltRole`) and reserves classes for categories, with a taxonomy spine of just four `subClassOf` edges. At the same time, the model's suggested placement/unit are **suppressed** (the triage prompt says "do not guess" a unit when unsure) or **silently dropped** (an off-allowlist unit discards the whole proposal), so the human reviewer inherits blank free-text fields with no signal — even though `docFrequency` (an evidence-volume signal) is already computed and sitting unused for this purpose.

The result is premature, disconnected classes and reviewers guessing in the dark. Class-hood should be **earned by accumulated evidence**, and the model's suggestions should **travel into the proposal** for the human to adjudicate.

## What Changes

- **Instances-first entry**: a novel term enters as an **instance** — typed by an existing class when one fits, otherwise parked as unclassified — instead of triggering eager class minting.
- **Evidence-graded promotion**: a recurring type is promoted to a **class** only when accumulated cross-run evidence (witness-instance count / recurrence / `docFrequency`) crosses a configurable threshold. At promotion, the accumulated witnesses **become** the new class's instances and its grounding evidence.
- **Instance-vs-subclass decision**: promotion distinguishes *instance-of-a-new-class* (graphite → a new `Moderator`) from *subclass-of-an-existing-class* ("emergency cooling" → `⊑ SafetyFunction`), as an evidence-shaped decision rather than a one-shot guess.
- **Connect, don't float**: a promoted class attaches into the ontology — `rdfs:subClassOf` an existing parent where one fits, and/or a fully `domain`+`range`-typed relation — instead of a parentless island with a half-typed relation.
- **Carry suggestions, don't suppress or drop**: the model's suggested placement and unit travel into the proposal with a **confidence signal** (a distinct *suggested* value vs an *asserted* one). An off-allowlist unit becomes a **flagged proposal** for the reviewer to adjudicate, not a silent discard.

## Capabilities

### New Capabilities
<!-- none — this refines existing mining/proposal capabilities -->

### Modified Capabilities
- `novelty-detection`: accumulate per-term evidence across mine runs and expose an evidence-volume signal (beyond the existing salience floor) usable as a promotion threshold.
- `candidate-triage`: replace the one-shot class-vs-instance judgment with an evidence-gated instance-first / promotion decision that also distinguishes instance-of-new-class from subclass-of-existing-class; carry suggested placement/unit with confidence; flag (not drop) off-allowlist unit suggestions.
- `change-proposal-schema`: a proposal references its witness instances, carries suggested-vs-asserted placement/unit predicates, records a promotion/needs-decision state, and (for promotions) asserts a connecting `subClassOf`/relation rather than a floating class.
- `instance-auto-accept`: adjust the instances-first entry path so an unclassified or new-type instance is retained as a promotion witness rather than dropped.

## Impact

- **Code**: `extraction/src/msr_extraction/` — `novelty.py` (cross-run accumulation + promotion signal), `triage.py` (evidence-gated decision, suggestions-with-confidence, off-allowlist flagging), `proposals.py` (suggested-vs-asserted emission, witness references, connecting edges, flag instead of `return None`), `mine_runner.py` (instances-first orchestration + promotion step), `auto_accept.py` (witness retention).
- **Ontology/schema**: new predicates in the `msr:` vocabulary for suggested-vs-asserted placement/unit, witness linkage, and proposal state (`ontology/msr.ttl`); SHACL shapes updated accordingly.
- **Cross-run state**: mining gains a notion of accumulated evidence spanning runs, which today is stateless/idempotent per candidate — this is the largest conceptual shift.
- **Deferred (explicit follow-up, NOT in this change)**: all `review-ui` changes — typed placement/unit pickers, kind-aware fields (hide unit for non-property kinds), a prominent approve action, a pre-approval routing/impact summary, and "needs-decision" vs "confirm" queue states. The UI consumes this change's new data model, so it is specced separately once this schema stabilizes.
- **Out of scope**: general morphology for companion-relation naming; deep multi-level taxonomy construction; changes to the approval / SHACL / graph-routing machinery itself.
