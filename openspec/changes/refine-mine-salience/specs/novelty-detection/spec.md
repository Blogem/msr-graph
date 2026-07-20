# novelty-detection Specification

## MODIFIED Requirements

### Requirement: Already-known and already-linked terms are excluded
Before scoring, the miner SHALL drop any candidate whose normalized form already resolves to a
known term in the **core dataset** — matched against **all** labels the core exposes: SKOS
`prefLabel`/`altLabel`, ontology class labels, physical-property labels, salt labels, and the
role/reactor layer labels — read through the three core `FROM` graphs (`urn:msr:ontology`,
`urn:msr:data`, `urn:msr:vocab`) via the chunk-6 `GraphReader`; or that chunk 6 already linked (a
`status:"linked"` record or `msr:Mention` triple). Matching MUST be normalization-aware —
collapsing case, surrounding whitespace, and internal separators so that spelling variants of the
same term are treated as equal (e.g. `molten salt` is excluded by `MoltenSalt`) — and MUST compare
on normalized **token sequences** so a known label's full token sequence appearing in a candidate
excludes it, while a candidate that merely shares a single token with a known label is NOT excluded.
Staging and proposal graphs MUST NOT be consulted for this exclusion, so a term approved in a prior
evolution round (now in core) is excluded but a still-pending proposal does not suppress
re-detection.

#### Scenario: A previously-approved term is not re-proposed
- **WHEN** a candidate's term matches a concept now present in `urn:msr:vocab`
- **THEN** the candidate is excluded from the pool

#### Scenario: A spelling variant of a known label is excluded
- **WHEN** a candidate term is a normalization/spacing variant of a known label (e.g. `molten salt` vs the class label `MoltenSalt`)
- **THEN** the candidate is excluded, even though the raw strings differ

#### Scenario: A novel term sharing one token with a known label is not excluded
- **WHEN** a candidate multiword term contains only a single token that also appears in a known label (but not the label's full token sequence)
- **THEN** the candidate is NOT excluded on that basis

#### Scenario: Staging membership does not exclude a candidate
- **WHEN** a candidate's term matches only a resource in `urn:msr:staging` (a pending proposal)
- **THEN** the candidate is NOT excluded on that basis

### Requirement: Salience ranks domain novelty and the queue is bounded
The miner SHALL rank each surviving candidate by a **keyness (relative-frequency) score** that
contrasts the candidate's salience in the corpus against how common its constituent tokens are in a
**vendored general-English word-frequency baseline** — so a term built from tokens that are rare in
general English but recurring in the corpus (e.g. `solubility`, `graphite`) ranks above a term of
common English tokens (e.g. `high temperature`, `heat transfer`), regardless of raw corpus
frequency. Document frequency over the full 637 OCR sidecars (via the inverted n-gram-set scan)
MAY be retained as an input/floor to the score and as evidence, but MUST NOT be the sole ranking
key. The general-English baseline MUST be a vendored asset (not a runtime download / external
dependency); if it is missing or unreadable, the miner SHALL log a warning and fall back to
document-frequency ranking rather than failing. After ranking and exclusion, the miner SHALL keep
only the **top-N** candidates by score, where N is a configuration value (not a hardcoded literal),
with a deterministic tie-break, and SHALL log the counts scored / excluded / cut so the truncation
is never silent.

#### Scenario: A domain-novel term outranks a more frequent common term
- **WHEN** a domain term (rare in general English) and a common-English term both appear in many corpus documents, and the common term has the higher raw document frequency
- **THEN** the domain term receives the higher keyness score and is ranked above the common term

#### Scenario: The reviewable queue is bounded to top-N
- **WHEN** more than N candidates survive exclusion
- **THEN** only the top-N by keyness score are retained for triage, and the number cut is logged

#### Scenario: Missing baseline degrades gracefully
- **WHEN** the vendored general-English frequency baseline is missing or unreadable
- **THEN** the miner logs a warning and ranks by document frequency instead of failing
