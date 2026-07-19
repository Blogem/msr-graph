# kg-schema-prompt Specification

## Purpose

Define the Python cached KG-schema prompt builder — a byte-stable, deterministically-ordered serialization of the ontology TBox, SKOS vocab, and salt catalog that forms the cache-friendly prompt prefix for Flash calls, rebuilt only on an ontology version bump. Owned by this change and reused by chunks 7 and 8.

## ADDED Requirements

### Requirement: Byte-stable KG-schema prompt prefix
The prompt builder SHALL serialize the ontology TBox, SKOS vocab, and salt catalog into a deterministically-ordered, byte-stable string prefix. Given identical graph state, repeated builds MUST produce a byte-identical prefix, so DeepSeek's prefix-based context cache is not invalidated between runs.

#### Scenario: Same graph state yields identical prefix
- **WHEN** the builder runs twice against the same graph state
- **THEN** the two prefixes are byte-identical

### Requirement: Rebuild gated on the ontology version
The builder SHALL read `owl:versionInfo` at run start (one cheap query) and rebuild the prefix only when the version differs from the cached value, so the cache is invalidated exactly when the schema changes (approvals, restores) and not otherwise.

#### Scenario: Version bump rebuilds the prefix
- **WHEN** `owl:versionInfo` changes between runs
- **THEN** the builder produces a new prefix reflecting the changed schema

#### Scenario: Unchanged version reuses the prefix
- **WHEN** `owl:versionInfo` is unchanged between runs
- **THEN** the builder returns the same cached prefix without rebuilding

### Requirement: Reusable by downstream extraction stages
The prompt builder SHALL live in the extraction package as an importable component so chunks 7 (relation extraction) and 8 (novelty triage) reuse it rather than re-deriving the schema serialization. Instance data (mentions, measurements, evidence) MUST NOT be baked into the prefix — it reaches the model only as per-call context.

#### Scenario: Instance data excluded from the prefix
- **WHEN** the prefix is built for a graph containing mention and measurement instances
- **THEN** the prefix contains only the TBox, vocab, and salt-catalog schema, not the mention/measurement instances
