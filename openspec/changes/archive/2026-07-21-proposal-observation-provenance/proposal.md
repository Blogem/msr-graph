# Proposal: proposal-observation-provenance

## Why

A mined `msr:ChangeProposal` stores its corpus support as a single materialized scalar, `msr:docFrequency`. That scalar is fragile and lossy: when the same term is re-mined from a second corpus the additive writer **appends** a second `docFrequency` value (observed during the safety-genre ingest — 19 chemistry/reactor proposals such as `moderator` gained a second value `269 + 2`), so `GET /api/proposals` emits one row per value, produces duplicate proposal ids, and crashes the Svelte keyed review queue. More importantly, collapsing to one number **discards a genuinely valuable signal the miner already computes**: which documents (and which corpora) a term was seen in, and how often. An entity seen across *different* corpora — e.g. both the ORNL chemistry corpus and the IAEA safety corpus — is materially more likely to be a real domain concept than a single-corpus artifact, and that breadth should be visible to the reviewer.

## What Changes

- **New per-observation evidence model.** Replace the stored `msr:docFrequency` scalar with append-only `msr:hasObservation` nodes — one per (proposal × document × mining run) — each recording `msr:inDocument`, `msr:occurrenceCount`, `msr:inCorpus`, `msr:observedInRun` (the per-run mine `prov:Activity`), and `prov:generatedAtTime`. Observations are append-only (full audit trail); the review surface shows the *latest* observation per document. **BREAKING** (internal): `msr:docFrequency` is no longer written as a proposal scalar — its value becomes a read-time aggregate.
- **First-class `msr:Corpus`.** Introduce corpus resources (`msrd:corpus-chemistry`, `msrd:corpus-safety`) and tag each `msr:Document msr:inCorpus <corpus>`, so observations can be grouped and cross-corpus breadth computed.
- **Read-time aggregation.** `GET /api/proposals` and the proposal-detail endpoint derive `documentFrequency`, `totalOccurrences`, `corpusCount`, and `corpora[]` from the observations (via `GROUP BY`/`SAMPLE`), guaranteeing **exactly one row per proposal** (fixing the crash) and returning both a high-level summary and per-corpus/per-document detail.
- **Reviewer-facing cross-corpus signal.** The review queue shows the summary plus a cross-corpus badge; the detail drawer shows the per-corpus/per-document provenance (which documents, which corpora, latest counts, when observed).
- **Deterministic backfill migration.** A one-shot backfill re-scans the two already-cached corpora — the chemistry `archive_dir` OCR sidecars (~637 docs under `data/corpus/msr-archive`) and the safety corpus (4 docs) — to rebuild observations for the existing staged proposals **by term**, with **no DeepSeek/LLM re-triage** (proposals already carry their triaged kind/term) and **no re-acquire** (both corpora are cached). The 19 duplicate-`docFrequency` proposals split naturally into correct per-corpus observations.

## Capabilities

### New Capabilities

- `proposal-observation-provenance`: the per-(proposal × document × run) observation model, the first-class `msr:Corpus` resource and `msr:Document msr:inCorpus` edge, the read-time aggregate definitions (documentFrequency / totalOccurrences / corpusCount / corpora), and the deterministic, inference-free backfill migration that rebuilds observations for existing proposals from the cached corpora.

### Modified Capabilities

- `novelty-detection`: the miner emits per-document (and per-corpus) observations for each surviving candidate instead of collapsing to a single `docFrequency`; the DF floor/ceiling still operate on the derived document-frequency, and a term is counted once per real document (no `{id}.txt`/`normalized.txt` double-count).
- `change-proposal-schema`: a `ChangeProposal` carries `msr:hasObservation` nodes rather than a stored `msr:docFrequency` scalar; the mini-schema is extended/validated for observations.
- `proposal-review-api`: the queue and detail endpoints aggregate observations at read time (one row per proposal) and return the summary + per-corpus/per-document detail.
- `review-ui`: the review queue and detail surfaces display the cross-corpus summary/badge and the per-corpus/per-document observation provenance.

## Impact

- **Extraction (Python)**: `novelty.py` (emit per-document/per-corpus observations), `proposals.py` (write append-only observations, drop the stored scalar), `graph_reader.py` (read existing proposal terms / corpus tags), a new backfill entry point + `safety`/`mine` CLI wiring, and the `msr:Corpus`/`inCorpus` document tagging in `documents.py`.
- **Server (Go)**: `cmd/server/proposals.go` — the queue + detail SPARQL queries aggregate observations (`GROUP BY`/`SAMPLE`) and the response DTOs gain the summary + detail fields.
- **Frontend**: the `review-ui` queue + detail components render the cross-corpus badge and observation breakdown.
- **Data / migration**: a deterministic backfill over the cached chemistry + safety corpora rewrites observations for the ~618 staged proposals and tags existing `Document`s with their corpus; no re-triage, no re-acquire, no LLM. Re-runnable and idempotent.
- **Ontology/SHACL**: additive terms (`msr:Observation`, `msr:hasObservation`, `msr:occurrenceCount`, `msr:inCorpus`, `msr:Corpus`, `msr:observedInRun`); provenance stays chunk-12-consistent (`observedInRun` → the per-run mine `Activity`). No new hard SHACL gate required beyond optional shape coverage.
- **Depends on**: archived chunk-8 (`novelty-detection`, `candidate-triage`, `change-proposal-schema`, `proposal-staging`), chunk-9 (`proposal-review-api`, `approval-typed-routing`, `proposal-lifecycle`), chunk-10 (`review-ui`), and chunk-12 (`provenance-model`). **Non-goals**: no re-triage/inference in the backfill; cross-corpus breadth is surfaced but does **not** yet feed triage/auto-accept/ranking scoring (deferred); the existing sampled `msr:hasEvidence` display sentences are retained alongside observations, not deleted.
