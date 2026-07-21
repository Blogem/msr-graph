## ADDED Requirements

### Requirement: Corpus is a first-class resource and documents declare their corpus
The system SHALL model each source corpus as a first-class `msr:Corpus` resource (at minimum `msrd:corpus-chemistry` for the msr-archive OCR corpus and `msrd:corpus-safety` for the IAEA/GIF/ORNL safety corpus) and SHALL assert `msr:inCorpus` from every `msr:Document` to its corpus. Corpus resources and `inCorpus` edges use deterministic IRIs and additive writes.

#### Scenario: A document declares its corpus
- **WHEN** the safety documents and the chemistry archive documents are present in `urn:msr:data`
- **THEN** each safety `msr:Document` has `msr:inCorpus msrd:corpus-safety` and each chemistry archive `msr:Document` has `msr:inCorpus msrd:corpus-chemistry`

#### Scenario: Corpus tagging is idempotent
- **WHEN** the corpus tagging runs a second time
- **THEN** the `urn:msr:data` triple count is unchanged (deterministic IRIs, additive writes)

### Requirement: Per-document, per-run observations replace the stored document-frequency scalar
A `msr:ChangeProposal` SHALL record its corpus support as append-only `msr:Observation` nodes linked by `msr:hasObservation`, one per (proposal × document × mining run), rather than a single stored `msr:docFrequency` scalar. Each observation MUST carry `msr:inDocument` (a `msr:Document`), `msr:occurrenceCount` (an integer term frequency within that document), `msr:inCorpus` (the document's corpus), `msr:observedInRun` (the per-run mine `prov:Activity`), and `prov:generatedAtTime`. Observations SHALL be append-only — a later mining run appends new observations rather than overwriting prior ones — so the full audit history is retained; consumers derive the current view as the latest observation per (proposal, document).

#### Scenario: A proposal carries per-document observations
- **WHEN** the miner produces a candidate seen 4 times in one document and twice in another
- **THEN** the proposal has two `msr:Observation` nodes, one per document, each with the matching `msr:occurrenceCount`, `msr:inCorpus`, `msr:observedInRun`, and `prov:generatedAtTime`, and no stored `msr:docFrequency` scalar

#### Scenario: Re-observation appends rather than overwrites
- **WHEN** a later mining run observes the same term in the same document again
- **THEN** a new observation is appended (stamped with the new run and time) and the prior observation is retained; the latest-per-document view reflects the newest observation

### Requirement: Aggregates are derived at read time, one value per proposal
The system SHALL derive `documentFrequency` (distinct documents with a latest observation), `totalOccurrences` (sum of the latest per-document `occurrenceCount`), `corpusCount` (distinct `inCorpus`), and `corpora` (the list of corpora) from a proposal's observations at read time, and SHALL NOT persist these as mutable scalars on the proposal. A proposal SHALL resolve to exactly one value for each aggregate regardless of how many mining runs contributed observations.

#### Scenario: A re-mined term yields one document-frequency per corpus, not duplicates
- **WHEN** a term was mined from the chemistry corpus (269 documents) and later from the safety corpus (2 documents)
- **THEN** the proposal has observations in both corpora, `corpusCount` is 2, `corpora` lists both, and the per-corpus `documentFrequency` values are 269 and 2 — never two conflicting scalars on one property

### Requirement: Cross-corpus breadth is a surfaced reviewer signal
The system SHALL expose a proposal's cross-corpus breadth (`corpusCount` and `corpora`) to the review surface as evidence that a candidate recurs across independent corpora. Cross-corpus breadth SHALL NOT be fed into triage classification, auto-accept, or mining-ceiling ranking by this capability — it is surfaced for human judgment only.

#### Scenario: A cross-corpus proposal is distinguishable
- **WHEN** a proposal has observations in two corpora and another has observations in one
- **THEN** the review API/surface reports `corpusCount` 2 vs 1 so the reviewer can see the cross-corpus one is more broadly attested

#### Scenario: Breadth does not alter automated decisions
- **WHEN** the miner and triage run
- **THEN** a candidate's cross-corpus breadth does not change its triage kind, auto-accept eligibility, or ceiling ordering

### Requirement: Deterministic, inference-free backfill of observations for existing proposals
The system SHALL provide a backfill that rebuilds observations for already-staged `msr:ChangeProposal`s by re-scanning the cached corpora deterministically and matching on each proposal's stored `msr:term`, without invoking the LLM triage step and without re-acquiring any corpus. The backfill MUST reuse the miner's deterministic term-matching so reconstructed counts reproduce the original document frequencies, MUST tag the scanned documents with `msr:inCorpus`, and MUST be idempotent (re-running does not duplicate observations). After backfill the stale `msr:docFrequency` scalars SHALL be removed.

#### Scenario: Backfill reconstructs observations without triage
- **WHEN** the backfill runs against the cached chemistry (`archive_dir` OCR) and safety corpora
- **THEN** each existing proposal gains per-document/per-corpus observations, no DeepSeek/LLM call is made, and a proposal with a known historical document frequency (e.g. `moderator` in the chemistry corpus) reproduces that value as a derived aggregate

#### Scenario: A previously duplicated proposal is split by corpus
- **WHEN** the backfill processes a proposal that had two appended `msr:docFrequency` values from two corpora
- **THEN** the proposal ends with observations attributed to the correct corpora and no stored `msr:docFrequency` scalar remains
