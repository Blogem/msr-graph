# relation-extraction Specification

## Purpose

Define the DeepSeek V4 Flash relation extractor that turns chunk-6 linked-mention sentences
into candidate salt↔property↔value measurements and salt↔role / salt↔reactor edges:
sentence-scoped, schema-constrained, and validated app-side against the run's known-IRI set
so the model can only assert facts about existing entities. The client is injected and
stubbed in every test.

## ADDED Requirements

### Requirement: Extraction is scoped to sentences carrying linked mentions
The extractor SHALL run only over curated-document sentences that carry at least one chunk-6
`status:"linked"` mention (read from `data/corpus/{report#}/mentions.jsonl`), passing the
sentence text with its linked entities on top of the cached chunk-6 KG-schema prompt. A
sentence with no linked mention SHALL NOT trigger a relation-extraction call.

#### Scenario: A mention-bearing sentence is sent to the extractor
- **WHEN** a sentence in ORNL-TM-2316 contains a `linked` FLiBe salt mention and a `linked` viscosity property mention
- **THEN** the extractor issues a Flash call for that sentence with those linked entities identified on top of the cached KG-schema prompt

#### Scenario: A sentence with no linked mention is skipped
- **WHEN** a sentence carries no `status:"linked"` mention
- **THEN** no Flash relation-extraction call is made for that sentence

### Requirement: Injected Flash client, stubbed in tests
The extractor SHALL use an injected OpenAI-compatible client configured via
`DEEPSEEK_BASE_URL` and `LLM_MODEL_EXTRACT` (DeepSeek V4 Flash), reusing the chunk-6 cached
KG-schema prompt builder rather than re-deriving the schema serialization. Every test SHALL
run against a stubbed client and never contact a live model.

#### Scenario: Tests use a stubbed client
- **WHEN** the relation-extraction tests run
- **THEN** they exercise the extractor against a stubbed client and never contact a live model

#### Scenario: The cached KG-schema prompt is reused
- **WHEN** the extractor builds a Flash request
- **THEN** it uses the chunk-6 KG-schema prompt builder as the cached prefix and does not re-derive the TBox/vocab/salt-catalog serialization

### Requirement: Output is schema-constrained JSON validated to existing IRIs
Flash output SHALL be schema-constrained JSON proposing zero or more relations. The layer
MUST validate each proposed relation app-side: the salt IRI MUST be a loaded `MoltenSalt`
individual, a property IRI MUST be a seed `msr:PhysicalProperty` individual, a role IRI MUST
be a seed `msr:SaltRole` individual, and a reactor IRI MUST be a loaded
`msr:MoltenSaltReactor` individual — each checked against the run's known-IRI set (read from
the core dataset). A relation naming any referent absent from the known set SHALL be
rejected and never written; the model therefore can only assert facts about known entities.

#### Scenario: A relation over known entities is accepted
- **WHEN** Flash proposes a measurement whose salt, property, and unit all resolve to known entities
- **THEN** the relation passes validation and is admitted for writing

#### Scenario: An unknown property IRI is rejected
- **WHEN** Flash proposes a relation whose property IRI is not a seed `msr:PhysicalProperty` (e.g. a novel `solubility`)
- **THEN** the relation is rejected and nothing is written, leaving the novel term for chunk 8

#### Scenario: An unknown salt or reactor IRI is rejected
- **WHEN** Flash proposes a relation whose salt or reactor IRI is absent from the known-IRI set
- **THEN** the relation is rejected and no triple or row is written

### Requirement: All relations present in a sentence are extracted
A single mention-bearing sentence MAY assert several relations. The extractor SHALL treat
the Flash output as a list of zero or more relations and SHALL validate and write each
admissible relation independently, so a sentence packing multiple facts (e.g. a salt's role
and its reactor, or two properties of one salt) loses none of them.

#### Scenario: A sentence asserting two relations yields two
- **WHEN** a sentence states both that FLiBe is the MSRE coolant and that it was used in the MSRE
- **THEN** the extractor produces both a role relation and a reactor relation, each validated and written independently

#### Scenario: A sentence with no admissible relation writes nothing
- **WHEN** Flash returns an empty relation list for a sentence
- **THEN** nothing is written for that sentence

### Requirement: Each relation carries an extraction confidence and rationale, recorded in a trace artifact
The extractor SHALL obtain, per proposed relation, an extraction confidence and a short
rationale (the supporting span/evidence and how certain the extraction is) — distinct from
any physical measurement uncertainty. It SHALL record every proposed relation — written,
rejected, or skipped — in a per-document trace artifact
`data/corpus/{report#}/relations.jsonl` with its confidence, rationale, and disposition,
deterministically regenerated per run. A configurable confidence threshold SHALL cause
below-threshold relations to be skipped rather than written. For a written measurement the
confidence and rationale are ALSO persisted queryably on the measurement node, and for a
written role/reactor edge via an `rdf:Statement` reification of the edge (see
`text-measurement-writing` and `salt-role-reactor-edges`).

#### Scenario: A written relation is traced with confidence and rationale
- **WHEN** a relation passes validation and is written
- **THEN** `relations.jsonl` gains a record carrying its confidence, rationale, and `disposition:"written"`

#### Scenario: A below-threshold relation is skipped, not written
- **WHEN** a proposed relation's extraction confidence is below the configured threshold
- **THEN** no triple or row is written and the relation is recorded with `disposition:"skipped"`

#### Scenario: A rejected relation is traced with its reason
- **WHEN** a relation is rejected for naming an unknown IRI or an out-of-allowlist unit
- **THEN** it is recorded in `relations.jsonl` with `disposition:"rejected"` and the reject reason

### Requirement: Malformed output never produces a silent write
The extractor SHALL drop any malformed or schema-violating Flash JSON, or any relation that
fails validation, and record it in the run summary, and SHALL NOT write any partial or
unvalidated triple or row.

#### Scenario: Malformed JSON is dropped
- **WHEN** Flash returns malformed or schema-violating JSON for a sentence
- **THEN** the extractor writes nothing for that sentence and records the drop

#### Scenario: A partially valid relation is not partially written
- **WHEN** a proposed measurement has a valid salt and property but an unmappable unit
- **THEN** the whole relation is rejected and neither a triple nor a row is written
