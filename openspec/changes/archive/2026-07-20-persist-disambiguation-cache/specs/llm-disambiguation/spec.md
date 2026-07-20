# llm-disambiguation Specification (delta)

## ADDED Requirements

### Requirement: Disambiguation outcomes persist across runs, keyed by the known-IRI set
The pipeline SHALL persist a run's layer-5 disambiguation outcomes
(`surface → (status, target_iri)`, including `novel` outcomes) to a store
tagged with a hash of the run's known-IRI set, and on a later run SHALL seed
the in-memory cache from that store **only when** the stored hash matches the
current known-IRI set — so surfaces already decided are not sent to the model
again. When the hash does not match (the linkable-entity set changed), the
persisted outcomes SHALL be ignored and the surfaces re-resolved. A missing,
unreadable, or malformed store SHALL be treated as empty and never fail the
run. The persistence layer MUST NOT change linking results for a given
known-IRI set: a seeded outcome SHALL equal what the model would have
returned, and seeded links remain subject to the known-IRI validation. A
refresh switch SHALL force re-resolution despite a matching store.

#### Scenario: Second run over an unchanged graph makes no model calls
- **WHEN** a link run has persisted its outcomes and a second run executes with the same known-IRI set and the same corpus
- **THEN** the second run seeds every layer-5 surface from the store and issues no disambiguation model calls, producing the same mentions

#### Scenario: Changed linkable-entity set invalidates the cache
- **WHEN** the known-IRI set differs from the one the store was written with
- **THEN** the store is ignored, the surfaces are re-resolved, and the store is rewritten with the new hash

#### Scenario: A missing or corrupt store is harmless
- **WHEN** the store is absent, unreadable, or malformed
- **THEN** the run proceeds as if no cache existed and resolves surfaces normally

#### Scenario: Refresh forces re-resolution
- **WHEN** the refresh switch is set and a matching store exists
- **THEN** the run ignores the stored outcomes, re-resolves via the model, and writes the fresh outcomes back
