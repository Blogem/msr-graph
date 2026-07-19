# Spec: nist-structured-loading

## ADDED Requirements

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
- **WHEN** a row carries a `Data type` code outside the documented set (`P1`, `P2`, `P3`, `+E`, `DP`)
- **THEN** the loader fails loudly with an error naming the offending code and does not silently skip the row

### Requirement: Coefficient rows written to the measurement store
The loader SHALL write one `measurement_value` row per kept NIST measurement with `source='nist'`, `doc_id` unset, `salt` in canonical form, the property name, the mapped `equation_form`, `t_min`/`t_max` from the validity range, `uncertainty` from the source column, coefficients `c0..c4` from `Data 1..5`, and `locator` in the contract form `nist-srd27/{property}#{canonical-salt}`. Numeric coefficients live only in SQLite; the graph does not carry them.

#### Scenario: FLiBe density coefficients land in SQLite
- **WHEN** the FLiBe density row (`LiF-BeF2, 34.0-66.0, P1`) is ingested
- **THEN** `measurement_value` holds a row with locator `nist-srd27/density#BeF2-LiF|66.0-34.0`, `source='nist'`, `c0=2.413`, and `c1=-4.88e-4`

#### Scenario: Coefficients are not emitted as triples
- **WHEN** a NIST measurement is loaded
- **THEN** its numeric coefficients appear only in `measurement_value` and no coefficient value is written to `urn:msr:data`

### Requirement: Catalog triples emitted additively to the core data graph
The loader SHALL emit `MoltenSalt`, `Constituent`, and `PropertyMeasurement` triples (with `ofSalt`, `forProperty`, `hasUnit`, `equationForm`, `validTempMin`/`Max`, `dataLocator`, and `prov:wasDerivedFrom` the NIST dataset) into `urn:msr:data` using additive SPARQL `INSERT DATA` through `internal/graph`. The loader SHALL NOT use Graph Store `PUT` on `urn:msr:data`, so the hand-curated seed A-Box (roles, reactor and citation edges) is preserved.

#### Scenario: FLiBe density measurement is queryable via the core client
- **WHEN** the loader has run and a core-dataset SPARQL query asks for the FLiBe density `PropertyMeasurement`
- **THEN** the client returns a measurement with property density, a QUDT unit, an equation form, a validity range, and a `dataLocator` that resolves to the SQLite row

#### Scenario: Seed hand-curated edges survive the load
- **WHEN** `loader nist` runs after the seed A-Box is loaded
- **THEN** the seed's `hasRole` / `usedIn` / `citedIn` edges remain present in `urn:msr:data`

### Requirement: Idempotent re-runs across both stores
Re-running `loader nist` SHALL leave both stores unchanged: catalog triples re-assert as a set-semantics no-op via deterministic IRIs, and SQLite rows upsert on the `locator` primary key. Per-graph triple counts and row counts MUST be identical after a second run.

#### Scenario: Second run changes nothing
- **WHEN** `loader nist` is run twice against the same stores
- **THEN** the `urn:msr:data` triple count and the `measurement_value` row count are identical after the second run

#### Scenario: Re-asserting seed salts is a no-op
- **WHEN** the loader emits catalog triples for a salt already present in the seed A-Box (e.g. the FLiBe coolant salt)
- **THEN** no duplicate salt, constituent, or measurement node is created because the minted IRIs match the seed exactly

### Requirement: Ingest run summary and DATA_SCOPE verification
On completion the loader SHALL print a summary reporting, per property file, rows read / kept / excluded-as-out-of-scope / flagged-for-review, plus the distinct canonical salts loaded and the equation forms seen. `DATA_SCOPE.md` open items 1–3 (fluoride row counts per file, FLiNaK and MSRE-coolant FLiBe presence, equation forms verified) SHALL be recorded from this real parse.

#### Scenario: Summary reports per-file counts
- **WHEN** `loader nist` completes
- **THEN** it prints per-property-file counts of rows read, kept, excluded, and flagged, and the distinct canonical salts loaded

#### Scenario: Anchor salts are present
- **WHEN** the load completes
- **THEN** the FLiBe MSRE-coolant salt (`LiF-BeF2` ~66-34 mol%) and FLiNaK (`LiF-NaF-KF`) are present among the loaded salts
