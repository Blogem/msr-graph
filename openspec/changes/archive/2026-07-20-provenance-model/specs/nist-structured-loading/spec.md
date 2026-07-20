# nist-structured-loading (delta)

## MODIFIED Requirements

### Requirement: Catalog triples emitted additively to the core data graph
The loader SHALL emit `MoltenSalt`, `Constituent`, `ChemicalCompound`, and `PropertyMeasurement` triples into `urn:msr:data` using additive SPARQL `INSERT DATA` through `internal/graph`. Every `PropertyMeasurement` SHALL carry `ofSalt`, `forProperty`, `hasUnit`, `equationForm`, `validTempMin`/`Max`, `dataLocator`, `prov:wasDerivedFrom` the NIST dataset, and `prov:wasGeneratedBy` the loader-run `Activity`. Every emitted `MoltenSalt`, `Constituent`, and `ChemicalCompound` SHALL likewise carry `prov:wasGeneratedBy` the loader-run `Activity` and `prov:wasDerivedFrom msrd:nist-srd27` (all instance data the loader asserts is provenanced, not just measurements). The derivation and generation provenance are required, not optional. The loader SHALL NOT emit `msr:citedIn`: NIST SRD-27 has no per-row citation, so a truthful measurement↔document citation is deferred to chunk-7 citation extraction. The loader SHALL NOT use Graph Store `PUT` on `urn:msr:data`, so other real-data-writer output already in the graph (e.g. extraction `Document`/`Mention` triples) is preserved.

#### Scenario: FLiBe density measurement is queryable via the core client
- **WHEN** the loader has run and a core-dataset SPARQL query asks for the FLiBe density `PropertyMeasurement`
- **THEN** the client returns a measurement with property density, a QUDT unit, an equation form, a validity range, and a `dataLocator` that resolves to the SQLite row

#### Scenario: Every measurement carries required provenance
- **WHEN** the loader emits a `PropertyMeasurement`
- **THEN** the measurement carries `prov:wasDerivedFrom` the NIST dataset and `prov:wasGeneratedBy` the loader-run `Activity` (no `msr:citedIn`)

#### Scenario: Catalog individuals carry provenance
- **WHEN** the loader emits a `MoltenSalt`, `Constituent`, or `ChemicalCompound`
- **THEN** each carries `prov:wasGeneratedBy msrd:activity-loader-nist` and `prov:wasDerivedFrom msrd:nist-srd27`

#### Scenario: Existing real-data-writer triples survive the load
- **WHEN** `loader nist` runs after the extraction pipeline has written `Document`/`Mention` triples into `urn:msr:data`
- **THEN** those triples remain present (additive `INSERT DATA`, not a graph-replace `PUT`)

### Requirement: Idempotent re-runs across both stores
Re-running `loader nist` SHALL leave both fact stores unchanged: catalog and provenance triples re-assert as a set-semantics no-op via deterministic IRIs (including the deterministic `msrd:activity-loader-nist` `Activity` IRI referenced by every measurement's `prov:wasGeneratedBy`, and the self-contained `Dataset`/`Document` nodes), and SQLite rows upsert on the `locator` primary key. The `urn:msr:data` triple count and the `measurement_value` row count MUST be identical after a second run. The timestamped loader-run **audit** graph `urn:msr:run:loader/<ts>` is explicitly outside this guarantee: each wall-clock run appends a new timestamped run graph holding that run's `Activity` record.

#### Scenario: Second run leaves the fact stores unchanged
- **WHEN** `loader nist` is run twice against the same stores
- **THEN** the `urn:msr:data` triple count and the `measurement_value` row count are identical after the second run (a new timestamped `urn:msr:run:loader/<ts>` audit graph may be added)

#### Scenario: Re-asserting salts across runs is a no-op
- **WHEN** `loader nist` emits catalog triples for a salt it already emitted on a prior run (e.g. the FLiBe salt)
- **THEN** no duplicate salt, constituent, or measurement node is created because the minted IRIs are deterministic

## ADDED Requirements

### Requirement: Loader is the sole source of the NIST dataset node and DOI
The loader SHALL itself emit the `msrd:nist-srd27` `msr:Dataset` node with its DOI (`dcterms:identifier "doi:10.18434/mds2-2298"`). With the hand-curated seed already removed (by `ground-demo-in-real-docs`), the loader is the **only** source of this source node — this defines the `msrd:nist-srd27` IRI that every measurement's `prov:wasDerivedFrom` already points at, closing the interim dangling reference. The emitted `Dataset` triples are deterministic, so re-runs re-assert them as a set-semantics no-op. (The loader emits no `msr:citedIn` and no citing `msr:Document`: NIST SRD-27 has no per-row citation, so that edge is deferred to chunk-7.)

#### Scenario: DOI present after a NIST load
- **WHEN** `loader nist` runs (seed already removed)
- **THEN** `msrd:nist-srd27` is present with its DOI, so every measurement's `prov:wasDerivedFrom` resolves to a real dataset carrying a DOI

#### Scenario: Dataset node re-assertion is a no-op
- **WHEN** `loader nist` runs a second time
- **THEN** no duplicate `Dataset` node or conflicting DOI triple is created — the emitted triples are deterministic

### Requirement: Loader-run activity recorded in a named graph
Every measurement the loader emits SHALL reference the deterministic `Activity` IRI `msrd:activity-loader-nist` via `prov:wasGeneratedBy` (in `urn:msr:data`). The loader SHALL write that `Activity`'s timestamped record into the run named graph `urn:msr:run:loader/<ts>` (and associate the source graph `urn:msr:src:nist-srd27`), typed `a prov:Activity` and attributed via `prov:wasAssociatedWith agent:loader@<version>` with `prov:startedAtTime`/`prov:endedAtTime` and the ontology `owl:versionInfo`, written via additive `INSERT DATA` with an explicit `GRAPH` target (not `PutGraph`).

#### Scenario: Run activity written and referenced
- **WHEN** `loader nist` completes
- **THEN** every emitted measurement in `urn:msr:data` carries `prov:wasGeneratedBy msrd:activity-loader-nist`, and a timestamped `prov:Activity` record for the run exists in `urn:msr:run:loader/<ts>` attributed to `agent:loader@<version>` with timestamps and ontology version
