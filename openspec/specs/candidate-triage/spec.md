# candidate-triage Specification

## Purpose

Define how a scored candidate is classified into a change kind and given a proposed placement:
cheap context signals propose a kind, a DeepSeek V4 Flash classifier (injected, stubbed in
tests) on the reused chunk-6 KG-schema prompt confirms it and proposes placement/grounding,
and all model output is validated app-side before it becomes a proposal.

## Requirements

### Requirement: Triage into one of four change kinds, or reject
Each candidate SHALL be triaged into exactly one primary kind — `property`, `class`, `instance`,
or `relation` — OR **rejected** as not a genuine novel ontology concept. Cheap context signals
(co-occurrence with a numeric value + a recognized physical unit → `property`; compound-formula
or named-reactor surface → `instance`; material / "constructed of X" context → `class`; the
candidate co-occurring in a sentence with known entities in a predicate-like frame, e.g.
"graphite-moderated" → `relation`) SHALL propose a kind, which the classifier confirms. The
classifier SHALL also be able to **reject** a candidate that is not a real ontology concept — an
OCR fragment, an acronym, a proper noun (person/organization/place) that slipped candidate
enumeration, or generic boilerplate — since candidate enumeration is precision-limited on noisy
OCR and the classifier is the semantic filter. A rejected candidate produces no proposal and is
counted as rejected in the run summary. Signals SHALL be lexical/co-occurrence based (no
dependency parse).

#### Scenario: A value-plus-unit term triages as a property
- **WHEN** a candidate co-occurs with a numeric value and a recognized physical unit
- **THEN** it is triaged with primary kind `property`

#### Scenario: A moderator-context term triages as a class
- **WHEN** a candidate appears in a material/moderator context (e.g. "graphite-moderated")
- **THEN** it is triaged with primary kind `class`

#### Scenario: A non-concept candidate is rejected
- **WHEN** a candidate is an OCR fragment, an acronym, a proper noun (e.g. an author surname or a laboratory name), or generic boilerplate
- **THEN** the classifier rejects it, no proposal is written, and it is counted as rejected

### Requirement: Flash classifier is injected and stubbed in tests
The triage classifier SHALL call DeepSeek V4 Flash through an injected OpenAI-compatible
client — the chunk-6 `msr_extraction.disambiguation.FlashClient` (satisfying the `Completer`
protocol, `DEEPSEEK_BASE_URL` / `LLM_MODEL_EXTRACT`) — and every test SHALL run against a stub
`Completer`, never a live model. The classifier prompt prefix SHALL reuse the chunk-6
`msr_extraction.kg_prompt` builder (`KGSchemaPromptCache`, imported not re-derived); the
candidate term and its evidence reach the model only as per-call context, never baked into the
cached prefix.

#### Scenario: Tests use a stubbed classifier
- **WHEN** the triage suite runs
- **THEN** the Flash client is a stub returning fixed classifications, and no network call is made

### Requirement: Proposed placement is recorded as reviewer-verifiable claims
The classifier SHALL propose placement for the candidate — a broader class for a `class`
kind; a `quantityKind` and `canonicalUnit` for a `property` kind; domain/range for a
`relation` kind — and any external (QUDT / INIS) reference. These SHALL be recorded as
LLM-asserted claims (evidence for the reviewer), not validated against external catalogs.

#### Scenario: Placement recorded without external validation
- **WHEN** the classifier proposes a broader class and an INIS descriptor for a candidate
- **THEN** both are recorded on the candidate as claims, and no external catalog is dereferenced to confirm them

### Requirement: Model output is validated app-side
The classifier SHALL request DeepSeek JSON output mode and MUST validate the parsed object
app-side (shape check) regardless of the model honouring any schema. The parsed verdict MUST be
one of the four kinds or an explicit reject; malformed JSON, an unrecognized/missing kind, or an
explicit reject SHALL cause the candidate to be dropped (no proposal), never emitted as a
malformed proposal.

#### Scenario: Malformed classifier output drops the candidate
- **WHEN** the stubbed classifier returns JSON that fails the shape check
- **THEN** the candidate is dropped and no proposal is written for it

#### Scenario: An explicit reject verdict drops the candidate
- **WHEN** the stubbed classifier returns a well-formed reject verdict
- **THEN** the candidate is dropped, no proposal is written, and it is counted as rejected (distinct from a malformed-output drop)
