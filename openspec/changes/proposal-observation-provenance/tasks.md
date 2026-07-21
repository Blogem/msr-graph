# Tasks: proposal-observation-provenance

## 1. Ontology & corpus vocabulary (additive)

- [x] 1.1 Add the additive terms to the seed ontology: `msr:Corpus`, `msr:Observation`, `msr:hasObservation` (ChangeProposal → Observation), `msr:inDocument`, `msr:occurrenceCount`, `msr:inCorpus` (Document → Corpus), `msr:observedInRun` (Observation → Activity) — with labels; no removal of existing terms
- [x] 1.2 Define the two corpus individuals `msrd:corpus-chemistry` and `msrd:corpus-safety` (label/description) and the rule for deriving a document's corpus (chemistry = msr-archive documents; safety = the four safety sources)
- [x] 1.3 Tag existing `msr:Document`s with `msr:inCorpus` (deterministic, additive, idempotent) — reuse the shared writer; add the `inCorpus` triple to the document-writing path so new documents are tagged going forward

## 2. Miner emits observations (`novelty-detection`)

- [x] 2.1 Extend the novelty scan to record, per surviving candidate, per-document occurrence counts and the document's corpus (reuse the existing deterministic matching; keep the genre-aware paths); derive document-frequency from these observations
- [x] 2.2 Confirm/keep the per-real-document counting (no `{id}.txt` + `normalized.txt` double-count) landed in the safety calibration fix; ensure it holds for both genres
- [x] 2.3 Thread the per-run mine `prov:Activity` (chunk-12) into the emitted observations as `msr:observedInRun` + `prov:generatedAtTime`

## 3. Proposal schema + writer (`change-proposal-schema`)

- [x] 3.1 Emit `msr:hasObservation` observation nodes (deterministic IRIs keyed by proposal+document+run) in `proposals.build_proposal_bundle`/`write_proposal`; stop writing the `msr:docFrequency` scalar on the proposal resource
- [x] 3.2 Make the proposal write append-only + idempotent for observations (re-running a run does not duplicate its observations); keep `msr:hasEvidence` sample sentences unchanged
- [x] 3.3 Update the change-proposal mini-schema/validation to expect observations rather than a `docFrequency` scalar

## 4. Backfill migration (`proposal-observation-provenance`)

- [ ] 4.1 Implement a deterministic, inference-free backfill: for each existing staged `msr:ChangeProposal`, re-scan the cached chemistry (`archive_dir` OCR) and safety corpora, match on the proposal's stored `msr:term` using the miner's matching, and write per-document/per-corpus observations — no LLM/triage call
- [ ] 4.2 Tag all scanned documents with `msr:inCorpus`; attribute the small re-scanned safety value to `corpus-safety` and reconcile the pre-existing (chemistry) value to `corpus-chemistry` for the 19 duplicated proposals
- [ ] 4.3 Remove the stale `msr:docFrequency` scalars after observations are written; make the whole backfill idempotent (keyed on a backfill run id or clear-then-rewrite)
- [ ] 4.4 Wire the backfill as a CLI subcommand (e.g. `mine backfill-observations`) that self-configures reader/sparql from `Config`; log a summary (proposals processed, observations written, documents tagged)

## 5. Review API (`proposal-review-api`)

- [x] 5.1 Rewrite the queue SPARQL to aggregate observations per proposal (`GROUP BY` + `SAMPLE`/`MAX`) so exactly one row per proposal id, computing `documentFrequency`, `totalOccurrences`, `corpusCount`, `corpora`; update the queue DTO
- [x] 5.2 Extend the detail endpoint to return the observation breakdown grouped by corpus/document (document, corpus, latest `occurrenceCount`, first/last observed) alongside the existing triples/evidence/neighborhood; update the detail DTO
- [x] 5.3 Keep the status filter + typed-error contract unchanged; ensure a proposal with multi-corpus/multi-run observations never fans out to multiple rows

## 6. Review UI (`review-ui`)

- [ ] 6.1 Queue: render one row per proposal with the support summary and a cross-corpus badge (from `corpusCount`/`corpora`); confirm the keyed list no longer errors on duplicate ids
- [ ] 6.2 Detail drawer: render the observation breakdown grouped by corpus → per document (link, latest count, observed time), alongside the existing evidence panel

## 7. Tests

- [x] 7.1 (extraction, unit) Miner emits per-document/per-corpus observations for a fixture corpus; occurrence counts and corpora are correct; document-frequency derived matches; no `docFrequency` scalar written
- [x] 7.2 (extraction, unit) Proposal writer writes append-only observation nodes with deterministic IRIs and is idempotent on re-run; `hasEvidence` retained
- [ ] 7.3 (extraction, unit) Backfill re-scan is deterministic and inference-free (stubbed/no LLM): fixture proposals gain correct observations by term; a fixture with a known DF reproduces it; a two-corpus fixture splits into two corpus observations; re-running does not duplicate
- [x] 7.4 (server, unit against fake graph) Queue returns exactly one entry per proposal id even when the fake returns multiple observation rows; summary aggregates (documentFrequency/totalOccurrences/corpusCount/corpora) are correct
- [x] 7.5 (server, unit) Detail returns the observation breakdown grouped by corpus/document
- [ ] 7.6 (frontend) Queue renders one row per proposal + cross-corpus badge on multi-corpus data (regression for the duplicate-id keyed-each crash); detail renders the observation breakdown
- [ ] 7.7 (opt-in integration, GraphDB) Backfill over a small cached fixture corpus writes observations, tags documents with `inCorpus`, and `GET /api/proposals` returns one row per proposal; second run leaves triple counts stable (idempotent)

## 8. Documentation

- [ ] 8.1 Document the observation/corpus model, the read-time aggregates, and the cross-corpus signal in the relevant README/docs section
- [ ] 8.2 Document the backfill CLI subcommand (inference-free, re-runnable) and when to run it
