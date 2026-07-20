# seed-graph-loading Specification

## Purpose

Define seed graph loading: loading seed files into their named graphs with graph-replace semantics, ensuring the staging graph exists, and guaranteeing idempotent seed loads.

## Requirements

### Requirement: Seed files load into their named graphs with graph-replace semantics
The system SHALL provide a `make load-seed` target that runs `cmd/loader seed` (a one-shot Compose run) which loads the **TBox and terminology only** into their named graphs via Graph Store Protocol `PUT` (replacing the target graph wholesale): `ontology/msr.ttl` → `urn:msr:ontology`, `ontology/vocab.ttl` → `urn:msr:vocab`. There is **no** hand-curated A-Box seed: `ontology/example-flibe.ttl` is removed, and `make load-seed` MUST NOT load any file into `urn:msr:data`. Loading MUST go through `internal/graph`'s write path (`PutGraph`), not ad-hoc HTTP. `urn:msr:data` is populated exclusively by the real-data writers — `cmd/loader nist` and the extraction pipeline (`ingest`/`link`).

#### Scenario: Only TBox and vocab load, no A-Box
- **WHEN** `make load-seed` completes against a healthy stack
- **THEN** `urn:msr:ontology` holds the ontology and `urn:msr:vocab` holds the SKOS terminology, and `urn:msr:data` contains no seed A-Box triples (no hand-curated salt, measurement, `skos:closeMatch`, `hasRole`, `usedIn`, or reactor)

#### Scenario: Data-graph facts come only from the real pipeline
- **WHEN** the FLiBe salt, its density measurement, and its grounding `msr:Mention` (which `msr:linksTo` the salt) are queried after a full build
- **THEN** they are present only after `loader nist` (salt + measurement) and `link` (the `msr:Mention → msr:linksTo → salt` edge — the linker emits `msr:linksTo`, never a `skos:closeMatch`) have run — never from a seed file

#### Scenario: Graph-replace removes stale triples
- **WHEN** a loaded TBox/vocab file is edited to remove a triple and `make load-seed` is re-run
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
