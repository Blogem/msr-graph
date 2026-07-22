## 1. Schema & ontology vocabulary

- [ ] 1.1 Add `msr:` vocabulary to `ontology/msr.ttl` for: suggested-vs-asserted placement/unit (`msr:suggestedUnit`, a suggested-parent predicate), a confidence datatype property, witness linkage (proposal → witness individuals), and a proposal decision-state property (confirm | needs-decision).
- [ ] 1.2 Update SHACL shapes so a *suggested* value is not treated as an asserted axiom, and a needs-decision proposal is valid to stage; ensure `msr:canonicalUnit`/`rdfs:subClassOf` assertions still validate as before.
- [ ] 1.3 Decide and document the witness graph name (`urn:msr:witness`) and its deterministic-IRI scheme (mirroring `mentions.py`/`auto_accept.py`).

## 2. Cross-run evidence accumulation (novelty-detection)

- [ ] 2.1 Implement per-term witness accumulation into the witness graph: record each new-type instance witness with its provenance/evidence, keyed by deterministic IRI (idempotent set-semantics).
- [ ] 2.2 Expose an accumulated-evidence query (witness count + document coverage per implied type) as the promotion signal, distinct from the existing salience floor/ceiling.
- [ ] 2.3 Add the configurable promotion threshold to `config.py` (no hardcoded literal); log promotion eligibility decisions in the run summary.

## 3. Instances-first entry & witness retention (instance-auto-accept, mine_runner)

- [ ] 3.1 In `mine_runner.py`, change the entry path so a `class`-signal candidate is emitted instance-first (typed by an existing class where one fits, else parked as an unclassified witness) instead of minting a class.
- [ ] 3.2 Retain a new-type instance (whose only type is not yet in the core schema) as a promotion witness rather than dropping it; keep its `prov:wasGeneratedBy`/`prov:wasDerivedFrom` edges.
- [ ] 3.3 Ensure witnesses are never written to `urn:msr:data` (their type does not exist yet) and do not force class minting.

## 4. Promotion step (candidate-triage, mine_runner)

- [ ] 4.1 Add a promotion step in `mine_runner.py` that queries accumulated witnesses, applies the threshold, and issues a class/subclass proposal for eligible types.
- [ ] 4.2 Implement the instance-vs-subclass decision (LLM judgment with accumulated witnesses as context) and record it + rationale as a reviewer-verifiable claim.
- [ ] 4.3 Emit the connecting edge on a promotion proposal: `rdfs:subClassOf` an existing parent where one fits, or a fully domain+range-typed relation; mark needs-decision when neither is determinable (never a bare parentless class).
- [ ] 4.4 Reference the promoting witnesses from the `ChangeProposal` so the promotion is auditable and de-dupable.

## 5. Suggestions carried into proposals (candidate-triage, proposals)

- [ ] 5.1 Update the triage prompt/response handling so placement/unit are returned with a confidence signal and an uncertain unit is a low-confidence *suggestion*, not omitted.
- [ ] 5.2 In `proposals.py`, emit suggested placement/unit under the suggested-* predicates (distinct from asserted), carrying confidence.
- [ ] 5.3 Replace the off-allowlist `build_proposal_bundle()` `return None` with: create the proposal, record the off-allowlist unit as a suggestion, and set needs-decision — never a silent drop.
- [ ] 5.4 Set the proposal decision-state (confirm vs needs-decision) from placement/unit confidence and allowlist status.

## 6. Tests

- [ ] 6.1 `novelty` — promotion threshold: below-threshold type yields no promotion; at/above yields eligibility; accumulation is idempotent across two runs (counts identical).
- [ ] 6.2 `triage` — instance-first: a single-witness class signal is emitted as an instance/witness and mints no class; a promoted type mints a class only at threshold.
- [ ] 6.3 `triage` — instance-vs-subclass decision: a specific-thing term promotes to instance-of-new-class; a kind-of term promotes to `rdfs:subClassOf` an existing class.
- [ ] 6.4 `proposals` — suggested-vs-asserted emission: a low-confidence unit lands under `msr:suggestedUnit` with confidence and no `msr:canonicalUnit`; a high-confidence allowlisted unit asserts `canonicalUnit`.
- [ ] 6.5 `proposals` — off-allowlist flagging: an off-allowlist unit produces a created, needs-decision proposal carrying the suggestion (assert a proposal IS written; regression against the old drop).
- [ ] 6.6 `proposals`/`mine_runner` — connecting edge: a promotion proposal asserts a parent or fully-typed relation; an undeterminable placement yields needs-decision, never a parentless class.
- [ ] 6.7 `instance-auto-accept` — witness retention: a new-type instance is retained as a witness (not dropped) and nothing is written to `urn:msr:data` for it.
- [ ] 6.8 Run the extraction suite: `cd extraction && uv run --extra test python -m pytest`.

## 7. Validation & docs

- [ ] 7.1 `openspec validate evidence-graded-ontology-growth --strict` passes.
- [ ] 7.2 Update mining/proposal docs (and any run-summary output) to describe instances-first, promotion, and suggested-vs-asserted placement/unit.
- [ ] 7.3 Record the deferred `review-ui` follow-up (typed pickers, kind-aware fields, prominent approve, pre-approval summary, needs-decision vs confirm queue states) as a note for the next change.
