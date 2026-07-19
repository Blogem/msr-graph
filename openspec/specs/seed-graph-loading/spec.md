# seed-graph-loading Specification

## Purpose

Define seed graph loading: loading seed files into their named graphs with graph-replace semantics, ensuring the staging graph exists, and guaranteeing idempotent seed loads.

## Requirements

### Requirement: Seed files load into their named graphs with graph-replace semantics
The system SHALL provide a `make load-seed` target that runs `cmd/loader seed` (a one-shot Compose run) which loads each seed file into its named graph via Graph Store Protocol `PUT` (replacing the target graph wholesale): `ontology/msr.ttl` → `urn:msr:ontology`, `ontology/vocab.ttl` → `urn:msr:vocab`, `ontology/example-flibe.ttl` → `urn:msr:data`. Loading MUST go through `internal/graph`'s write path (`PutGraph`), not ad-hoc HTTP.

#### Scenario: Seed data queryable after load
- **WHEN** `make load-seed` completes against a healthy stack
- **THEN** a SPARQL query via the core-dataset client returns the FLiBe example measurement from the seed A-Box

#### Scenario: Graph-replace removes stale triples
- **WHEN** a seed file is edited to remove a triple and `make load-seed` is re-run
- **THEN** the removed triple is no longer present in the target named graph

### Requirement: Staging graph ensured
The seed load SHALL ensure `urn:msr:staging` exists, creating it empty if absent, and MUST NOT modify it if it already contains triples.

#### Scenario: Staging created on first load
- **WHEN** `make load-seed` runs against a repository with no staging graph
- **THEN** `urn:msr:staging` exists and is empty afterwards

#### Scenario: Existing staging content preserved
- **WHEN** `urn:msr:staging` already contains triples and `make load-seed` is re-run
- **THEN** those triples are still present afterwards

### Requirement: Seed loading is idempotent
Running the seed load twice in a row SHALL yield identical triple counts in every named graph.

#### Scenario: Double load changes nothing
- **WHEN** `make load-seed` runs twice consecutively
- **THEN** per-graph triple counts after the second run equal the counts after the first run
