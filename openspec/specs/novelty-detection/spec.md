# novelty-detection Specification

## Purpose

Define how the miner surfaces novel candidate terms: enumerate concept-shaped candidates via a
spaCy noun-chunk pass over the curated documents' text and from the chunk-6 salt-formula misses
(without re-running the chunk-6 linker), exclude anything already known to the core dataset or
already linked (normalization/token-sequence aware), bound the candidate set by document
frequency used only as a coarse cost floor plus a hard maximum-candidate ceiling (never a
novelty rank), and attach curated-set evidence sentences with document citations and offsets.
Precision is deferred to the LLM triage reject verdict and human review, not a novelty score.

## Requirements

### Requirement: Candidate terms are enumerated from the curated text and the chunk-6 misses
The miner SHALL enumerate candidate terms from two sources: (a) a **spaCy noun-chunk pass** over
the curated documents' normalized text — loading a statistical spaCy model (e.g.
`en_core_web_sm`) and taking `doc.noun_chunks`, keeping only content tokens (alphabetic,
non-stopword, length ≥ 3) that are NOT part of a named entity of a non-concept type
(`PERSON`/`ORG`/`GPE`/`LOC`/`FAC`/`NORP`/`DATE`/`TIME`/`CARDINAL`/`ORDINAL`/`MONEY`/`PERCENT`/
`QUANTITY`), lemmatizing, and forming a candidate from 1–3 surviving tokens — so candidates are
concept-shaped and proper nouns are dropped at the source; and (b) the `status:"novel"` records
of the chunk-6 `data/corpus/{report#}/mentions.jsonl` artifacts, which contribute the unresolved
salt-formula spans as instance-kind candidates. The miner SHALL NOT re-run the chunk-6 linker.
Each candidate MUST retain its surface form and the source document + span offsets. If the spaCy
model cannot be loaded, the miner SHALL log an error and fall back to the prior n-gram
term-candidate pass rather than failing.

#### Scenario: A novel domain term is enumerated as a noun chunk
- **WHEN** the curated text contains a salient noun-phrase concept (e.g. "solubility" or "graphite") that chunk 6 did not link
- **THEN** the miner enumerates it as a candidate from its spaCy noun-chunk pass, even though it is absent from the chunk-6 `mentions.jsonl`

#### Scenario: A proper noun is not enumerated as a candidate
- **WHEN** a noun chunk is (or contains) a `PERSON`/`ORG`/`GPE` entity such as an author name or a laboratory/organization name
- **THEN** those entity tokens are dropped and the proper noun is not emitted as a candidate

#### Scenario: An unresolved salt-formula miss becomes a candidate
- **WHEN** a chunk-6 `mentions.jsonl` record has `status:"novel"` (an unresolved salt-formula span)
- **THEN** the miner includes it as an instance-kind candidate for triage

### Requirement: Already-known and already-linked terms are excluded
Before triage, the miner SHALL drop any candidate whose normalized form already resolves to a
known term in the **core dataset** — matched against **all** labels the core exposes: SKOS
`prefLabel`/`altLabel`, ontology class labels, physical-property labels, salt labels, and the
role/reactor layer labels — read through the three core `FROM` graphs (`urn:msr:ontology`,
`urn:msr:data`, `urn:msr:vocab`) via the chunk-6 `GraphReader`; or that chunk 6 already linked (a
`status:"linked"` record or `msr:Mention` triple). Matching MUST be normalization-aware —
casefolding, splitting camelCase, and collapsing whitespace/separators so spelling variants of the
same term are equal (e.g. `molten salt` is excluded by `MoltenSalt`) — and MUST compare on
normalized **token sequences** so a known label's full token sequence appearing in a candidate
excludes it, while a candidate that merely shares a single token with a known label is NOT
excluded. Staging and proposal graphs MUST NOT be consulted, so a term approved in a prior
evolution round (now in core) is excluded but a still-pending proposal does not suppress
re-detection.

#### Scenario: A previously-approved term is not re-proposed
- **WHEN** a candidate's term matches a concept now present in `urn:msr:vocab`
- **THEN** the candidate is excluded from the pool

#### Scenario: A spelling variant of a known label is excluded
- **WHEN** a candidate term is a normalization/spacing/camelCase variant of a known label (e.g. `molten salt` vs the class label `MoltenSalt`)
- **THEN** the candidate is excluded, even though the raw strings differ

#### Scenario: A novel term sharing one token with a known label is not excluded
- **WHEN** a candidate multiword term contains only a single token that also appears in a known label (but not the label's full token sequence)
- **THEN** the candidate is NOT excluded on that basis

#### Scenario: Staging membership does not exclude a candidate
- **WHEN** a candidate's term matches only a resource in `urn:msr:staging` (a pending proposal)
- **THEN** the candidate is NOT excluded on that basis

### Requirement: Document frequency bounds cost; it is not a novelty rank
The miner SHALL use document frequency over the full 637 OCR sidecars (via the fast inverted
n-gram-set scan) only as a **coarse cost bound**, never as a novelty ranking (document frequency
does not distinguish novel concepts from common/known terms on this corpus). The miner SHALL drop
candidates below a configurable low document-frequency floor (to remove rare OCR one-offs) and
SHALL enforce a configurable **maximum-candidate ceiling**: if more candidates survive shaping,
exclusion, and the floor than the ceiling, the miner keeps the top-`max` by document frequency
with a deterministic tie-break — purely as a runaway guard — and MUST log the number cut so the
truncation is never silent. Both the floor and the ceiling MUST be configuration values, not
hardcoded literals. The miner SHALL NOT compute or rank by a keyness / weirdness / relative-
frequency novelty score.

#### Scenario: A rare OCR one-off is dropped by the floor
- **WHEN** a candidate appears in fewer corpus documents than the configured document-frequency floor
- **THEN** the candidate is dropped before triage

#### Scenario: The candidate set is bounded by the ceiling
- **WHEN** more candidates survive shaping/exclusion/floor than the configured maximum-candidate ceiling
- **THEN** the miner keeps at most that many (top by document frequency, deterministic tie-break) and logs the number cut

#### Scenario: Ordering is not treated as a novelty ranking
- **WHEN** candidates are passed to triage
- **THEN** they are not ranked or prioritized by a novelty score; precision is deferred to the triage reject verdict and human review

### Requirement: Curated-set evidence with citations and offsets
Each retained candidate SHALL carry one or more evidence items drawn from the curated set —
each an evidence sentence text, the source `Document` (via `msr:citedIn`), and the span's
start/end offsets into that document's `normalized.txt` — so the reviewer sees the term in
context. Evidence MUST come from the curated ~12 (where offsets and `Document` nodes exist),
even though the frequency count spans all 637 documents.

#### Scenario: Evidence carries document and offsets
- **WHEN** a candidate is retained
- **THEN** it has at least one evidence item with sentence text, a `msr:citedIn` document reference, and start/end offsets
