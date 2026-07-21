## MODIFIED Requirements

### Requirement: Document frequency bounds cost; it is not a novelty rank
The miner SHALL compute document frequency over the corpus being mined (per real document — counting each source document once, never double-counting a document's raw `{id}.txt` and its derived `normalized.txt`) only as a **coarse cost bound**, never as a novelty ranking (document frequency does not distinguish novel concepts from common/known terms on this corpus). Document frequency SHALL be derived from the miner's per-document observations (see `proposal-observation-provenance`), not stored as a standalone scalar. The miner SHALL drop candidates below a configurable low document-frequency floor (to remove rare OCR one-offs) and SHALL enforce a configurable **maximum-candidate ceiling**: if more candidates survive shaping, exclusion, and the floor than the ceiling, the miner keeps the top-`max` by document frequency with a deterministic tie-break — purely as a runaway guard — and MUST log the number cut so the truncation is never silent. Both the floor and the ceiling MUST be configuration values, not hardcoded literals, and the floor MAY be genre-specific. The miner SHALL NOT compute or rank by a keyness / weirdness / relative-frequency novelty score.

#### Scenario: A rare OCR one-off is dropped by the floor
- **WHEN** a candidate appears in fewer corpus documents than the configured document-frequency floor
- **THEN** the candidate is dropped before triage

#### Scenario: The candidate set is bounded by the ceiling
- **WHEN** more candidates survive shaping/exclusion/floor than the configured maximum-candidate ceiling
- **THEN** the miner keeps at most that many (top by document frequency, deterministic tie-break) and logs the number cut

#### Scenario: Ordering is not treated as a novelty ranking
- **WHEN** candidates are passed to triage
- **THEN** they are not ranked or prioritized by a novelty score; precision is deferred to the triage reject verdict and human review

#### Scenario: Document frequency counts each document once
- **WHEN** a corpus stores both a document's raw text and its normalized text
- **THEN** the miner counts that document once toward document frequency, not twice

## ADDED Requirements

### Requirement: The miner emits per-document, per-corpus observations for surviving candidates
For each candidate that survives shaping, exclusion, and the floor, the miner SHALL emit per-document observations — the documents (and their corpora) the term was seen in and how often per document — conforming to the observation model in `proposal-observation-provenance`, stamped with the current mine run. These observations, not a collapsed scalar, are the persisted corpus-support record for the resulting proposal.

#### Scenario: Surviving candidate carries observations
- **WHEN** a candidate survives to become a proposal
- **THEN** the miner writes one observation per document it was seen in, each recording the occurrence count, the document, the document's corpus, and the mine run
