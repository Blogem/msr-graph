## Context

The mining pipeline (`extraction/src/msr_extraction/`) is today **stateless and idempotent per candidate**: each mine run enumerates candidates (`novelty.py`), triages each one-shot via a Flash LLM call (`triage.py`), and emits a proposal bundle (`proposals.py`) — with no memory between runs. `docFrequency` is computed but used only as a salience floor/ceiling. The seed ontology (`ontology/msr.ttl`) is a relational ontology with a 4-edge `subClassOf` spine that models specifics as **instances** (`msr:density a msr:PhysicalProperty`).

Two structural consequences motivate this change: (1) a `class`-kind candidate mints a new `owl:Class` from a single witness, landing it as a parentless island with a range-only companion relation; (2) suggested placement/unit are suppressed (uncertain → omitted) or the whole proposal is dropped (off-allowlist unit), leaving the reviewer with unguided blanks.

The central shift is introducing **cross-run evidence accumulation** so class-hood becomes earned, not guessed — the largest architectural change, since mining is currently memoryless.

## Goals / Non-Goals

**Goals:**
- New terms enter instances-first; classes are minted only when accumulated evidence crosses a configurable threshold.
- Promotion distinguishes instance-of-new-class from subclass-of-existing-class, and connects the result into the ontology (parent or fully-typed relation).
- The model's suggested placement/unit travel into the proposal with confidence (suggested-vs-asserted), and off-allowlist units flag rather than drop.
- Evidence accumulation and all decisions remain deterministic and idempotent across re-runs.

**Non-Goals:**
- No `review-ui` changes (typed pickers, kind-aware fields, prominent approve, pre-approval summary, queue states) — a deliberate follow-up that consumes this schema.
- No change to the approval / SHACL / graph-routing machinery.
- No general relation-naming morphology; no deep multi-level taxonomy construction.

## Decisions

### D1 — Where accumulated evidence lives: a witness graph, not external state
Retain promotion witnesses as RDF in a dedicated graph (e.g. `urn:msr:witness`) rather than a side database, so accumulation reuses the existing SPARQL store, stays queryable/auditable, and inherits the deterministic-IRI idempotency pattern already used by `mentions.py`/`auto_accept.py`. **Alternative considered:** a local JSON/SQLite ledger — rejected because it splits state out of the graph the rest of the pipeline already trusts, and complicates the idempotency guarantee.

### D2 — Promotion is a distinct pipeline step, not folded into per-candidate triage
Keep triage's one-shot classification as the *signal detector*, but add a separate **promotion step** in `mine_runner.py` that queries accumulated witnesses, applies the threshold, and (for eligible types) issues the class/subclass proposal. This keeps triage stateless and testable, and isolates the cross-run logic in one place. **Alternative:** decide promotion inside `classify()` — rejected because it would require triage to carry cross-run state, breaking its stub-testability.

### D3 — Suggested vs asserted as separate predicates
Model a suggestion (`msr:suggestedUnit`, a suggested-placement predicate) as distinct from the asserted axiom (`msr:canonicalUnit`, `rdfs:subClassOf`), each carrying a confidence literal. Approval routing already routes by triple *type*, so a suggested-* predicate is naturally excluded from core-graph promotion until a reviewer confirms it — no routing change needed. **Alternative:** a single value plus a confidence annotation — rejected because an unconfirmed suggestion would then be indistinguishable from an asserted axiom to the router and to SHACL.

### D4 — Off-allowlist units flag, not drop
Replace `build_proposal_bundle()` returning `None` for an off-allowlist unit with emitting the proposal, recording the off-allowlist value as a suggested unit, and setting a needs-decision state. The QUDT allowlist stays the gate for *asserted* `canonicalUnit`, but never silently deletes a whole proposal. **Alternative:** keep dropping — rejected as it hides the exact case a human should adjudicate.

### D5 — Instance-vs-subclass is an evidence-shaped LLM judgment, recorded as a claim
The promotion step asks the classifier (with the accumulated witnesses as context) whether the type is an instance-of-new-class or subclass-of-existing, and records the answer + rationale as a reviewer-verifiable claim — never auto-committed. Connection into the ontology (`subClassOf` a parent, or a fully domain+range-typed relation) is part of this claim; if none is determinable, the proposal is marked needs-decision rather than floating a bare class.

## Risks / Trade-offs

- **Stateful mining breaks the current "pure re-run" simplicity** → Mitigation: witnesses use deterministic IRIs in `urn:msr:witness`; accumulation is set-semantics, so re-runs are still idempotent (a spec scenario asserts this).
- **Threshold tuning is corpus-sensitive** (too high → nothing promotes; too low → premature classes) → Mitigation: threshold is configuration, not hardcoded; the run summary logs promotion decisions so tuning is observable.
- **Witnesses could accumulate unbounded across runs** → Mitigation: witnesses are keyed by deterministic IRI (bounded by distinct mined individuals), and the existing salience floor still gates what enters at all.
- **LLM instance-vs-subclass judgment can be wrong** → Mitigation: it is a recorded claim, not an auto-commit; the human confirms at review, and needs-decision state surfaces low-confidence cases.
- **Two proposals for one concept** (an early instance-first witness, then a later promotion) → Mitigation: the promotion proposal references its witnesses by IRI, so the relationship is explicit and de-dupable rather than two orphan proposals.

## Open Questions

- What exactly counts toward the promotion threshold — distinct witness individuals, distinct documents, or both — and what default value fits the 637-doc corpus?
- Does a promoted subclass need its own witnesses re-typed, or do witnesses only justify a new *class* (not a subclass)?
- Should approving a promotion proposal retroactively re-type the already-written instance-first witnesses in `urn:msr:data`, and if so, is that in-scope here or a routing/approval follow-up?
