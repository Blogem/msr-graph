# nist-structured-loading Specification

## Purpose

Define the `loader nist` ingest path for the vendored NIST Molten Salts DB (SRD 27): reading frozen source files, dispatching the subcommand, writing coefficient rows to the measurement store, emitting catalog triples additively into the core data graph, handling composition-isotherm measurements, guaranteeing idempotent re-runs across both stores, and reporting a run summary with DATA_SCOPE verification.

## Requirements

### Requirement: Vendored NIST SRD 27 source files
The system SHALL vendor the four NIST Molten Salts DB (SRD 27) property files — density, electrical conductivity, surface tension, and viscosity — under `data/nist/` as committed inputs, with the dataset DOI (`10.18434/mds2-2298`) recorded. The vendored copy is the frozen input; the loader reads only from `data/nist/`, never from the network.

#### Scenario: Loader reads only vendored files
- **WHEN** `loader nist` runs
- **THEN** it reads the four vendored property files from `data/nist/` and makes no network request to obtain source data

#### Scenario: Dataset provenance recorded
- **WHEN** the vendored files are added
- **THEN** the NIST SRD 27 DOI `10.18434/mds2-2298` is recorded alongside them as their provenance

### Requirement: `loader nist` ingest subcommand
The system SHALL provide a `loader nist` subcommand that ingests the vendored NIST files end-to-end: parse rows, apply the fluoride-subset filter, canonicalize salt formula and composition, write coefficient rows to SQLite, and emit catalog triples to `urn:msr:data`. The subcommand SHALL be dispatched from `cmd/loader` alongside the existing `seed` and `init-db` subcommands.

#### Scenario: Subcommand is dispatched
- **WHEN** `loader nist` is invoked
- **THEN** the loader runs the NIST ingest and exits zero on success

#### Scenario: Unknown data-type code aborts
- **WHEN** a row carries a `Data type` code outside the full documented set (`P1`, `P2`, `P3`, `P4`, `+E`, `E1`, `E2`, `DP`, `I1`, `I2`, `I3`, `I4`)
- **THEN** the loader fails loudly with an error naming the offending code and does not silently skip the row

#### Scenario: Documented isotherm and extended-Arrhenius codes are ingested, not skipped
- **WHEN** a row carries `E1` (pure BeF2 viscosity) or `I2`/`I3`/`I4` (KF-ZrF4 / NaF-ZrF4 composition isotherms)
- **THEN** the loader maps it to the matching `msr:EquationForm` individual and ingests it into both stores like any other documented code

### Requirement: Coefficient rows written to the measurement store
The loader SHALL write one `measurement_value` row per kept NIST measurement with `source='nist'`, `doc_id` unset, `salt` in canonical form, the property name, the mapped `equation_form`, `t_min`/`t_max` from the validity range, `uncertainty` from the source column, coefficients `c0..c4` from `Data 1..5`, and `locator` in the contract form `nist-srd27/{property}#{canonical-salt}`. Numeric coefficients live only in SQLite; the graph does not carry them.

#### Scenario: FLiBe density coefficients land in SQLite
- **WHEN** the FLiBe density row (`BeF2-LiF, 34.0-66.0, P1`) is ingested
- **THEN** `measurement_value` holds a row with locator `nist-srd27/density#BeF2-LiF|34.0-66.0`, `source='nist'`, `c0=2.413`, and `c1=-4.88e-4`

#### Scenario: Coefficients are not emitted as triples
- **WHEN** a NIST measurement is loaded
- **THEN** its numeric coefficients appear only in `measurement_value` and no coefficient value is written to `urn:msr:data`

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

### Requirement: Composition-isotherm measurements
The loader SHALL treat a row carrying an isotherm `Data type` code (`I1`–`I4`) as a composition-isotherm measurement rather than a temperature-dependent one: it SHALL mint a range-composition salt whose varying constituent carries `moleFractionMin`/`moleFractionMax` (per the `salt-canonicalization` range-salt rule), and it SHALL write a `PropertyMeasurement` whose `equationForm` is the matching `msr:Isotherm{n}` individual, whose `validTempMin` equals `validTempMax` (the single temperature the sweep was measured at), and which carries a `msr:compositionComponent` naming the varying compound.

#### Scenario: KF-ZrF4 isotherm row produces a range-composition salt and measurement
- **WHEN** a KF-ZrF4 row with `Composition range` `0.0-33.3 ZrF4` and `Data type` `I3` is ingested
- **THEN** the loader mints a salt whose `ZrF4` constituent has `moleFractionMin=0.0` and `moleFractionMax=0.333` and whose `KF` constituent has `moleFractionMin=0.667` and `moleFractionMax=1.0`, and writes a `PropertyMeasurement` with `equationForm msr:Isotherm3`, `validTempMin = validTempMax`, and `msr:compositionComponent` naming `ZrF4`

### Requirement: Idempotent re-runs across both stores
Re-running `loader nist` SHALL leave both fact stores unchanged: catalog and provenance triples re-assert as a set-semantics no-op via deterministic IRIs (including the deterministic `msrd:activity-loader-nist` `Activity` IRI referenced by every measurement's `prov:wasGeneratedBy`, and the self-contained `Dataset`/`Document` nodes), and SQLite rows upsert on the `locator` primary key. The `urn:msr:data` triple count and the `measurement_value` row count MUST be identical after a second run. The timestamped loader-run **audit** graph `urn:msr:run:loader/<ts>` is explicitly outside this guarantee: each wall-clock run appends a new timestamped run graph holding that run's `Activity` record.

#### Scenario: Second run leaves the fact stores unchanged
- **WHEN** `loader nist` is run twice against the same stores
- **THEN** the `urn:msr:data` triple count and the `measurement_value` row count are identical after the second run (a new timestamped `urn:msr:run:loader/<ts>` audit graph may be added)

#### Scenario: Re-asserting salts across runs is a no-op
- **WHEN** `loader nist` emits catalog triples for a salt it already emitted on a prior run (e.g. the FLiBe salt)
- **THEN** no duplicate salt, constituent, or measurement node is created because the minted IRIs are deterministic

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

### Requirement: Ingest run summary and DATA_SCOPE verification
On completion the loader SHALL print a summary reporting, per property file, rows read / kept / excluded-as-out-of-scope / flagged-for-review, plus the distinct canonical salts loaded and the equation forms seen. `DATA_SCOPE.md` open items 1–3 (fluoride row counts per file, FLiNaK and MSRE-coolant FLiBe presence, equation forms verified) SHALL be recorded from this real parse.

#### Scenario: Summary reports per-file counts
- **WHEN** `loader nist` completes
- **THEN** it prints per-property-file counts of rows read, kept, excluded, and flagged, and the distinct canonical salts loaded

#### Scenario: Anchor salts are present
- **WHEN** the load completes
- **THEN** the FLiBe MSRE-coolant salt (`BeF2-LiF` 34.0-66.0 mol%) and FLiNaK (`KF-LiF-NaF`) are present among the loaded salts
