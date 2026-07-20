# novelty-detection Specification

## Purpose

Define how the miner surfaces novel candidate terms: enumerate salient terms from the curated
documents' text and from the chunk-6 salt-formula misses (without re-running the chunk-6
linker), exclude anything already known to the core dataset or already linked, score each by
document frequency over the full 637-document OCR corpus against a salience threshold, and
attach curated-set evidence sentences with document citations and offsets.

## ADDED Requirements

### Requirement: Candidate terms are enumerated from the curated text and the chunk-6 misses
The miner SHALL enumerate candidate terms from two sources without re-running the chunk-6
spaCy linker: (a) a lexical term-candidate pass over the curated documents' normalized text /
segments — because chunk 6's matcher is a rules-only `spacy.blank("en")` pipeline that
recognizes only seeded labels and salt-formula-shaped spans, it never surfaces arbitrary novel
terminology such as `solubility` or `graphite`, so the miner cannot rely on the chunk-6 miss
output alone; and (b) the `status:"novel"` records of the chunk-6
`data/corpus/{report#}/mentions.jsonl` artifacts, which contribute the unresolved
salt-formula spans as instance-kind candidates. Each candidate MUST retain its surface form
and the source document + span offsets.

#### Scenario: A novel domain term is enumerated from the curated text
- **WHEN** the curated text contains a salient term (e.g. "solubility" or "graphite") that chunk 6 did not link
- **THEN** the miner enumerates it as a candidate via its own lexical term pass, even though it is absent from the chunk-6 `mentions.jsonl`

#### Scenario: An unresolved salt-formula miss becomes a candidate
- **WHEN** a chunk-6 `mentions.jsonl` record has `status:"novel"` (an unresolved salt-formula span)
- **THEN** the miner includes it as an instance-kind candidate for triage

### Requirement: Already-known and already-linked terms are excluded
Before scoring, the miner SHALL drop any candidate whose surface form (normalized) already
resolves to a known concept, altLabel, ontology class, or individual in the **core dataset**
(read through the three core `FROM` graphs — `urn:msr:ontology`, `urn:msr:data`,
`urn:msr:vocab` — via the chunk-6 `GraphReader`) or that chunk 6 already linked (a
`status:"linked"` record or `msr:Mention` triple). Staging and proposal graphs MUST NOT be
consulted for this exclusion, so a term approved in a prior evolution round (now in core) is
excluded but a still-pending proposal does not suppress re-detection.

#### Scenario: A previously-approved term is not re-proposed
- **WHEN** a candidate's term matches a concept now present in `urn:msr:vocab`
- **THEN** the candidate is excluded from the pool

#### Scenario: Staging membership does not exclude a candidate
- **WHEN** a candidate's term matches only a resource in `urn:msr:staging` (a pending proposal)
- **THEN** the candidate is NOT excluded on that basis

### Requirement: Document-frequency salience over the full corpus
The miner SHALL score each surviving candidate by its **document frequency** — the number of
the full 637 OCR sidecars (under `data/corpus/msr-archive/`, chunk 5's LFS-skip clone) whose
text contains the term, via a case-folded scan — and SHALL keep only candidates whose
frequency is at or above a configurable salience threshold. The threshold MUST be a
configuration value, not a hardcoded literal.

#### Scenario: A high-frequency term survives the threshold
- **WHEN** a candidate term appears in a number of OCR documents at or above the configured threshold
- **THEN** the candidate is retained for triage

#### Scenario: A low-frequency term is dropped
- **WHEN** a candidate term appears in fewer OCR documents than the configured threshold
- **THEN** the candidate is dropped and never triaged

### Requirement: Curated-set evidence with citations and offsets
Each retained candidate SHALL carry one or more evidence items drawn from the curated set —
each an evidence sentence text, the source `Document` (via `msr:citedIn`), and the span's
start/end offsets into that document's `normalized.txt` — so the reviewer sees the term in
context. Evidence MUST come from the curated ~12 (where offsets and `Document` nodes exist),
even though the frequency count spans all 637 documents.

#### Scenario: Evidence carries document and offsets
- **WHEN** a candidate is retained
- **THEN** it has at least one evidence item with sentence text, a `msr:citedIn` document reference, and start/end offsets
