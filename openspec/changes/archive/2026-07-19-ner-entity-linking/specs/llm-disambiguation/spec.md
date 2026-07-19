# llm-disambiguation Specification

## Purpose

Define the DeepSeek V4 Flash disambiguation layer for spans the lexical layers cannot settle: a schema-constrained call whose output is validated against the known-IRI set — linking only to existing entities or declaring the span novel — through an injected client that is stubbed in every test.

## ADDED Requirements

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
