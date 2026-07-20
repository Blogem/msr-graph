# llm-disambiguation Specification

## Purpose
TBD - created by archiving change ner-entity-linking. Update Purpose after archive.
## Requirements
### Requirement: Flash disambiguates only spans unresolved by lexical layers
The pipeline SHALL send to DeepSeek V4 Flash only the spans left unresolved after expanded exact matching, the formula normalizer, and the bounded fuzzy fallback. The call SHALL provide the span's sentence context on top of the cached KG-schema prompt, and SHALL use an injected OpenAI-compatible client configured via `DEEPSEEK_BASE_URL` and `LLM_MODEL_EXTRACT`.

#### Scenario: Resolved spans skip the model
- **WHEN** a span is already linked by exact matching or the formula normalizer
- **THEN** no Flash call is made for that span

#### Scenario: Client is injected and stubbed in tests
- **WHEN** the disambiguation layer runs under test
- **THEN** it uses a stubbed client and never contacts a live model

### Requirement: Output is schema-constrained and validated to existing IRIs
Flash output SHALL be schema-constrained JSON that either links the span to an IRI or declares it novel. The layer MUST validate any returned link IRI against the run's known-IRI set (the set that seeded the matcher) and MUST reject an IRI not in that set — a rejected link falls through to novel. The model therefore can only map to known entities and can never introduce a new IRI as a link.

#### Scenario: Valid IRI is accepted
- **WHEN** Flash returns a link to an IRI present in the known-IRI set
- **THEN** the span is linked to that IRI

#### Scenario: Unknown IRI is rejected
- **WHEN** Flash returns a link to an IRI absent from the known-IRI set
- **THEN** the link is rejected and the span is recorded as novel, not linked

### Requirement: Novel and malformed responses never produce a silent link
When Flash declares the span novel, or returns malformed/schema-violating JSON, the layer SHALL record the span as unresolved/novel (for the chunk-8 miss output) and SHALL NOT emit a link.

#### Scenario: Novel declaration recorded, not linked
- **WHEN** Flash declares a span novel
- **THEN** the span is recorded as novel and no mention link is written

#### Scenario: Malformed output treated as unresolved
- **WHEN** Flash returns malformed or schema-violating JSON
- **THEN** the span is treated as unresolved/novel rather than linked

### Requirement: Disambiguation outcomes are memoized per surface form within a run
The pipeline SHALL cache each layer-5 disambiguation outcome keyed on the mention surface form for the duration of a single `link` run, and SHALL reuse the cached outcome for any later span with an identical surface form instead of issuing another model call. The cache SHALL be in-memory and scoped to a single run — it MUST NOT be persisted across runs. Because layer-5 candidate spans are formula-shaped, the surface form determines identity and the sentence context of the first occurrence is representative for later identical surfaces. Every reused outcome remains subject to the known-IRI validation, so memoization can never produce a link to an IRI absent from the run's known-IRI set.

#### Scenario: Repeated surface reuses the cached outcome
- **WHEN** the same unresolved surface form reaches layer 5 more than once in a run
- **THEN** the model is called only for the first occurrence and later occurrences reuse the cached outcome

#### Scenario: Distinct surfaces each call once
- **WHEN** two different unresolved surface forms reach layer 5 in a run
- **THEN** each surface produces its own model call and neither reuses the other's outcome

#### Scenario: A novel outcome is cached too
- **WHEN** a surface is resolved as novel on its first occurrence
- **THEN** later identical surfaces reuse the novel outcome without another model call

#### Scenario: Cache does not persist across runs
- **WHEN** a new `link` run starts
- **THEN** the disambiguation cache begins empty and no outcome is carried over from a previous run

### Requirement: Distinct unresolved surfaces are resolved concurrently
The pipeline SHALL resolve the distinct unresolved layer-5 surface forms of a
run concurrently, using a bounded worker pool whose size is configurable
(default 24), rather than issuing every layer-5 model call strictly
sequentially. Concurrency MUST NOT change which spans reach layer 5, the
per-surface memoization semantics, or the known-IRI validation of each
outcome: each distinct surface SHALL still be sent to the model exactly once
per run, and the linked/novel result applied to a span SHALL be identical to
that produced by a sequential run.

#### Scenario: Each distinct surface is resolved once despite concurrency
- **WHEN** several distinct unresolved surfaces reach layer 5 in a run
- **THEN** each distinct surface is sent to the model exactly once, and repeated occurrences of a surface issue no additional model call

#### Scenario: Concurrent resolution is transparent to output
- **WHEN** a surface resolves to a link under concurrent resolution
- **THEN** the resulting mention record links to the same IRI it would under sequential resolution, still subject to the known-IRI validation

#### Scenario: More than one call runs at a time
- **WHEN** multiple distinct unresolved surfaces are pending resolution
- **THEN** the worker pool issues more than one model call concurrently rather than one at a time

### Requirement: Transient model errors are retried, not silently dropped
Disambiguation SHALL retry transient model failures — HTTP 429 rate-limit, 5xx, request timeouts, and connection errors — with backoff before giving up, so that raising the concurrency does not cause a rate-limit blip to be silently recorded as `novel` (an unlinked span). Only a non-transient failure or an exhausted retry budget SHALL fall through to the existing novel/unresolved handling. The disambiguation client SHALL reuse a single pooled connection across concurrent calls rather than opening a fresh client per call.

#### Scenario: A rate-limited call is retried before being resolved
- **WHEN** a disambiguation call is rejected with a transient 429/5xx/timeout error and a retry then succeeds
- **THEN** the span is resolved by the retried call, not recorded as novel

#### Scenario: Concurrent calls share one pooled client
- **WHEN** many disambiguation calls run concurrently in a run
- **THEN** they are issued through a single shared, connection-pooled client rather than a new client constructed per call

