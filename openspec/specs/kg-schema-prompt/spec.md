# kg-schema-prompt Specification

## Purpose

Define the Go prompt builder that serializes the ontology TBox, SKOS vocabulary, and salt catalog into a canonical, byte-stable system prompt for the analysis agent. The prompt carries schema only (never instance data), is deterministically ordered so DeepSeek's prefix caching keys on a stable prefix, and is rebuilt only when the ontology version bumps, detected per chat request.

## Requirements

### Requirement: Byte-stable KG-schema system prompt
The system SHALL provide a Go prompt builder (owned by this chunk) that serializes the ontology TBox + SKOS vocabulary + salt catalog into a canonical, deterministically ordered system prompt. For a fixed graph state the builder MUST produce **byte-identical** output across invocations (all sets ordered by IRI; numbers and labels canonically formatted), so DeepSeek's prefix-based caching keys on a stable prefix.

#### Scenario: Same graph state yields byte-identical prompt
- **WHEN** the prompt builder runs twice against the same graph state
- **THEN** the two produced prompts are byte-for-byte identical

#### Scenario: Ordering is deterministic regardless of query result order
- **WHEN** the underlying query bindings are returned in a different order
- **THEN** the builder still emits the classes, properties, concepts, and salts in the same canonical (IRI-sorted) order

### Requirement: Prompt carries schema, not instance data
The prompt SHALL contain only schema-level content — the TBox, the SKOS vocabulary (pref/altLabels), and the salt catalog — and SHALL NOT embed measurements, mentions, or evidence, which the agent retrieves through visible tool calls instead.

#### Scenario: Instance measurements are absent from the prompt
- **WHEN** the built prompt is inspected
- **THEN** it includes ontology classes/properties, vocab labels, and the salt catalog, and it does not include coefficient values, measurement rows, or evidence sentences

### Requirement: Rebuild on ontology version bump, detected per chat request
The server SHALL detect the ontology version by a single `owl:versionInfo` SELECT at the start of every chat request. When the version is unchanged the cached prompt SHALL be reused; when it has changed the prompt SHALL be rebuilt. The version detected SHALL be the value reported as the "ontology version used" in provenance.

#### Scenario: Unchanged version reuses the cached prompt
- **WHEN** two chat requests arrive and the `owl:versionInfo` value is identical for both
- **THEN** the prompt is built once and reused for the second request

#### Scenario: Version bump triggers a rebuild
- **WHEN** a chat request observes an `owl:versionInfo` value different from the cached one
- **THEN** the prompt builder rebuilds the prompt from the current graph state before the turn runs
