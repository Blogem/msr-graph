# Design: proposal-observation-provenance

## Context

The chunk-8 miner (`novelty-detection`) walks each corpus document-by-document, records the documents and sentences a candidate term appears in, then collapses that to a single `msr:docFrequency` integer written onto the `msr:ChangeProposal` (`change-proposal-schema`) via additive `INSERT DATA` (`proposals.py`). Two consequences surfaced during the safety-genre ingest:

1. **Correctness/rendering bug.** Proposal IRIs are deterministic on `term + kind`, so re-mining a term that already has a proposal (e.g. `moderator`, present in both the chemistry and safety corpora) writes to the _same_ resource; the additive writer appends a second `docFrequency` rather than replacing it. 19 proposals now carry two values (`moderator` = `269, 2`). `GET /api/proposals` (`proposal-review-api`) selects `?docFrequency` with no aggregation → one row per value → duplicate `id` → the Svelte keyed `{#each … (p.id)}` review queue throws and freezes.
2. **Lost signal.** The per-document and per-corpus detail the miner already computes is discarded. Cross-corpus recurrence — a term appearing in both the ORNL chemistry corpus and the IAEA safety corpus — is a strong "this is a real domain concept" signal for the reviewer, and it is exactly what the collapsed scalar throws away.

Both corpora are cached in this repo: the chemistry OCR sidecars under `data/corpus/msr-archive` (`config.archive_dir`, ~637 `*.txt`) and the safety corpus under `data/safety` (4 documents). The expensive/nondeterministic step (Flash/DeepSeek triage) is already persisted in the existing proposals' `kind`/`term`; only the deterministic scan needs redoing to rebuild the detail.

Binding contracts inherited unchanged: deterministic IRIs + additive writes (chunk 5 D6); per-run `prov:Activity` in `urn:msr:provenance` (chunk 12); proposals invisible to the core-dataset client until approved (chunk 8/9); triage kind set and approval routing (`candidate-triage`, `approval-typed-routing`) untouched.

## Goals / Non-Goals

**Goals:**

- Model corpus support as append-only, per-(proposal × document × run) **observations** carrying `inDocument`, `occurrenceCount`, `inCorpus`, `observedInRun`, `generatedAtTime` — never a stored aggregate.
- Model `msr:Corpus` as a first-class resource and tag each `msr:Document msr:inCorpus <corpus>`.
- Derive `documentFrequency`, `totalOccurrences`, `corpusCount`, `corpora[]` at read time; guarantee one API row per proposal (fixing the crash by construction).
- Surface cross-corpus breadth to the reviewer (summary badge + per-corpus/per-document detail drawer).
- Provide a **deterministic, inference-free** backfill that rebuilds observations for existing staged proposals from the cached corpora, splitting the 19 duplicate proposals into correct per-corpus observations.

**Non-Goals:**

- No re-triage / no LLM in the backfill or the observation write path.
- No automated use of cross-corpus breadth in triage, auto-accept, or mining ceiling ranking yet — surface only; scoring is a deliberate later decision (avoid over-fitting before we have real data).
- Do not delete the existing sampled `msr:hasEvidence` sentences — they remain the reviewer-facing quote sample; observations are the complete count/provenance layer alongside them.
- No change to the triage kind set, the approval routing, or the proposal identity scheme (`term + kind`).

## Decisions

### D1 — Append-only observations, show-latest-per-document

Each mining run appends one `msr:Observation` per (proposal, document) it sees, stamped with `msr:observedInRun` (the run's `prov:Activity`) and `prov:generatedAtTime`. The review surface renders the _latest_ observation per (proposal, document) (max `generatedAtTime`). **Why append-only over upsert:** it yields a real audit trail ("SRS-123 reported count 2 on 2026-07-21; the June chemistry run reported 269"), mirrors the chunk-12 pattern where per-run activities accrue rather than overwrite, and avoids the upsert hazard of clobbering an already-decided proposal's state. Alternative considered — overwrite-in-place per (proposal, document) — is simpler to query but destroys history and re-introduces a mutable-scalar failure mode.

### D2 — `msr:Corpus` as a first-class resource

Introduce `msrd:corpus-chemistry` / `msrd:corpus-safety` and `msr:Document msr:inCorpus <corpus>`. **Why over a genre string literal on the document:** a resource lets observations group and aggregate by corpus cleanly in SPARQL, carries a label/description for the UI, and extends to future corpora without schema churn. Genre already exists as a pipeline concept (chemistry vs safety); this materializes it in the graph.

### D3 — Aggregates are derived at read time, never stored

`documentFrequency` = `COUNT(DISTINCT ?document)` over latest observations; `totalOccurrences` = `SUM` of latest per-document `occurrenceCount`; `corpusCount`/`corpora` = distinct `inCorpus`. Computed in the `proposal-review-api` SPARQL with `GROUP BY ?proposal` (and `SAMPLE`/`MAX` for scalar columns) so the endpoint returns exactly one row per proposal. **This is the root-cause fix:** with no stored aggregate there is nothing to duplicate, and the DF floor/ceiling in the miner operate on the freshly computed document-frequency. Alternative — keep a stored scalar but make the writer a replace-not-append upsert — was rejected: it keeps a redundant, drift-prone denormalization and still risks the reviewStatus-clobber problem on re-mine.

### D4 — Deterministic, term-keyed backfill over cached corpora

The backfill reuses the miner's _exact_ deterministic matching (the same casefold/lemma/noun-chunk path `score_document_frequency`/`enumerate_spacy_terms` use) so reconstructed counts reproduce the original `docFrequency` values, then writes observations for each existing proposal keyed on its stored `term`. It scans both cached corpora (`archive_dir` OCR + safety) and never calls triage. **Why term-keyed re-scan over deriving from stored `hasEvidence`:** stored evidence is a small sample (e.g. `moderator` has 22 evidence sentences across 4 documents but truly occurs in 269 chemistry documents), so evidence-derived counts would massively undercount; the re-scan is accurate and, because both corpora are cached, requires no re-acquire. The 19 duplicate proposals split by construction: the safety re-scan attributes the small value to `corpus-safety`, the chemistry re-scan the large value to `corpus-chemistry`.

### D5 — `occurrenceCount` is per-document term frequency

`occurrenceCount` records how many times the term occurs within each document (term frequency), not mere presence — this is the "how often, per document" the reviewer asked for. `documentFrequency` (presence across documents) remains derivable as the count of documents with an observation, preserving the existing DF-floor semantics. **Trade-off:** TF requires the scan to count matches per document rather than short-circuit on first hit; the cost is negligible on the cached corpora.

### D6 — Observations live in staging, provenance in `urn:msr:provenance`

Observation nodes are written to `urn:msr:staging` linked from the proposal (they are proposal metadata, invisible to the core client). `msr:observedInRun` references the per-run mine `prov:Activity`, whose full record (agent, timestamps, ontology version) stays in `urn:msr:provenance` per chunk 12 — no new provenance model. On approval the observations remain attached to the (now-decided) proposal as its audit trail; approval routing is unaffected because observations are not TBox/ABox core triples.

### D7 — API response shape

Queue rows gain a compact summary (`documentFrequency`, `totalOccurrences`, `corpusCount`, `corpora[]`); the detail endpoint adds an `observations` array grouped by corpus → per document (`documentId`, latest `occurrenceCount`, `firstObserved`/`lastObserved`, `run`). The `review-ui` renders a cross-corpus badge in the queue and the grouped breakdown in the detail drawer.

## Risks / Trade-offs

- **Backfill counts must match the original miner or the numbers look wrong.** → Reuse the miner's exact matching functions (not a fresh regex); validate on a proposal with a known value (`moderator` → chemistry ≈ 269) before writing.
- **Observation volume.** ~618 proposals × documents × runs is many triples in `urn:msr:staging`. → Bounded (one per proposal/document, not per mention); staging is already non-core and periodically pruned; the append-only history is the intended audit cost.
- **Chemistry re-scan cost.** Re-scanning ~637 OCR documents runs the spaCy pass again. → Deterministic and local (no API); minutes; run once as a migration, idempotent on re-run.
- **`hasEvidence` vs observations divergence.** Two overlapping evidence layers (sampled sentences vs complete counts) could confuse. → Keep clearly separated: `hasEvidence` = display quotes, `hasObservation` = counts/provenance; document the split in the schema.
- **Idempotency of the backfill/writer.** Re-running must not re-duplicate. → Observations are keyed by (proposal, document, run); the migration either targets a single deterministic backfill run id or clears prior backfill observations before rewriting.

## Migration Plan

1. Create a checkpoint as the rollback point for step 6 (`make checkpoint LABEL=before-observation-migration`).
2. Land the schema + writer + miner + API + UI changes (specs' requirements).
3. Tag existing `msr:Document`s with `msr:inCorpus` (deterministic: chemistry archive documents → `corpus-chemistry`, the four safety documents → `corpus-safety`).
4. Run the deterministic backfill (a `mine`/`safety` CLI subcommand, no triage): re-scan both cached corpora, rebuild observations for the ~618 staged proposals, then remove the stale `msr:docFrequency` scalars.
5. Verify: `GET /api/proposals` returns one row per proposal; the 19 formerly-duplicated proposals show two corpus observations; `moderator`'s chemistry `documentFrequency` matches its historical value; the review queue renders.
6. **Rollback:** restore the pre-migration checkpoint (`store-checkpoint-restore`), or delete the observation triples and re-derive; the backfill is re-runnable and idempotent.

## Open Questions

- **Exact `occurrenceCount` unit** — count of noun-chunk/lemma matches (miner-native) vs count of linked `msr:Mention`s. Miner-native is the accurate reproduction of DF and is preferred; confirm during implementation.
- **Retiring `hasEvidence`** — long-term, observations + on-demand sentence lookup could subsume the sampled evidence sentences; out of scope here, flagged for later.
- **Corpus taxonomy** — chemistry/safety today; if a third genre lands, is `Corpus` per-genre or per-source-collection? Keep per-genre until a third case forces the question.
- **When cross-corpus breadth earns its keep in scoring** — review-queue ordering, mining ceiling sort, or an auto-accept signal — deliberately deferred to a follow-up once real cross-corpus data is observed.
