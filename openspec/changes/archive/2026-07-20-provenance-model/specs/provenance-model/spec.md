# provenance-model (delta)

## ADDED Requirements

### Requirement: PROV-O vocabulary in the seed ontology
The system SHALL add a self-contained PROV-O slice to `ontology/msr.ttl` (loaded into `urn:msr:ontology` by `make load-seed`) sufficient to attribute any fact to who/what/when produced it: `prov:Activity` and `prov:Agent` as usable classes, and the object/datatype properties `prov:wasGeneratedBy`, `prov:wasAssociatedWith`, `prov:startedAtTime`, and `prov:endedAtTime`, alongside the already-present `prov:wasDerivedFrom` and the `msr:Document`/`msr:Dataset` ⊑ `prov:Entity` declarations. Adding the slice SHALL bump the ontology's `owl:versionInfo` so the cached KG-schema prompt rebuilds on next use.

#### Scenario: PROV-O TBox loaded with the seed
- **WHEN** `make load-seed` runs after the PROV-O slice is added to `ontology/msr.ttl`
- **THEN** `urn:msr:ontology` contains `prov:Activity`, `prov:Agent`, and the `prov:wasGeneratedBy` / `prov:wasAssociatedWith` / `prov:startedAtTime` / `prov:endedAtTime` properties

#### Scenario: Ontology version is bumped
- **WHEN** the PROV-O slice is added
- **THEN** `owl:versionInfo` on the ontology differs from the pre-change value

### Requirement: Every pipeline-asserted instance individual carries provenance
Provenance SHALL be present on **all instance data a pipeline asserts into `urn:msr:data`**, not only on measurements and mentions. The scope is three-tiered:

- **Derived individuals** — every `msr:PropertyMeasurement`, `msr:Mention`, `msr:MoltenSalt`, `msr:Constituent`, and `msr:ChemicalCompound` a real-data writer (the NIST loader over the vendored CSVs, the extraction pipeline over real documents) emits SHALL carry both `prov:wasGeneratedBy` a run `prov:Activity` **and** `prov:wasDerivedFrom` its source `prov:Entity` (a `msr:Dataset` or `msr:Document`). (A measurement↔document `msr:citedIn` citation edge is **not** required: NIST SRD-27 carries no per-row citation, so no writer can assert one truthfully yet; it is deferred to chunk-7 citation extraction. The predicate stays TBox-declared but unused.)
- **Source entities** — `msr:Dataset` and `msr:Document` nodes are the derivation *roots*: they SHALL be identified by their real external identifier (a DOI / report number) rather than `prov:wasDerivedFrom` another source; that external identity is their provenance.
- **Schema & terminology** — the ontology TBox (`ontology/msr.ttl`) and the SKOS vocabulary (`ontology/vocab.ttl`) are **out of scope**: they are definitional, not empirical claims derived from a source, and their versioning is `owl:versionInfo` (see the version-bump requirement), not per-node PROV edges.

These edges are required, not optional. Consistent with Principle 3 (only real data), a writer SHALL NOT fabricate provenance: every `prov:wasDerivedFrom`/`prov:wasGeneratedBy` target references a real dataset, document, or run, never a synthetic placeholder.

#### Scenario: A measurement carries derivation and generation provenance
- **WHEN** any writer emits a `msr:PropertyMeasurement`
- **THEN** the individual carries `prov:wasDerivedFrom` a `Dataset`/`Document` and `prov:wasGeneratedBy` an `Activity` (no `msr:citedIn` is required)

#### Scenario: Catalog individuals also carry provenance
- **WHEN** the loader emits a `msr:MoltenSalt`, `msr:Constituent`, or `msr:ChemicalCompound`
- **THEN** each carries `prov:wasGeneratedBy` the loader-run `Activity` and `prov:wasDerivedFrom` the NIST dataset

#### Scenario: A mention carries derivation and generation provenance
- **WHEN** any writer emits a `msr:Mention`
- **THEN** the individual carries `prov:wasDerivedFrom` (its source `Document`) and `prov:wasGeneratedBy` an `Activity`

#### Scenario: Source entities are roots, schema is excluded
- **WHEN** a `msr:Dataset`/`msr:Document` node or a TBox/vocab term is written
- **THEN** the source entity carries its real external identifier (DOI / report number) rather than a `wasDerivedFrom`, and TBox/vocab terms carry no per-node PROV edges (their provenance is `owl:versionInfo`)

### Requirement: Generating activities record agent, timestamps, and ontology version
Each `prov:Activity` that generates facts SHALL carry `prov:wasAssociatedWith` a `prov:Agent` identifying the producer (`agent:loader@<version>`, `agent:extraction@<version>`, or a human reviewer), `prov:startedAtTime` and `prov:endedAtTime` from the producing process clock, and the `owl:versionInfo` of the ontology in effect for the run. The `Activity` IRI referenced by facts (via `prov:wasGeneratedBy` in `urn:msr:data`) SHALL be **deterministic per pipeline/source** (e.g. `msrd:activity-loader-nist`, `msrd:activity-extraction`) so the fact-level edge re-asserts as a set-semantics no-op; the wall-clock-timestamped `Activity` record itself is asserted in the per-run named graph (see the named-graph requirement).

#### Scenario: A loader-run activity is fully attributed
- **WHEN** the loader writes its run `Activity`
- **THEN** the `Activity` carries `prov:wasAssociatedWith agent:loader@<version>`, start/end timestamps, and the ontology `owl:versionInfo`

#### Scenario: An extraction-run activity is fully attributed
- **WHEN** the extraction pipeline writes its run `Activity`
- **THEN** the `Activity` carries `prov:wasAssociatedWith agent:extraction@<version>`, start/end timestamps, and the ontology `owl:versionInfo`

### Requirement: Per-source and per-run named graphs carry an Activity record
Each data source SHALL have a named graph `urn:msr:src:<id>` (e.g. `urn:msr:src:nist-srd27`) and each pipeline run a named graph `urn:msr:run:<pipeline>/<ts>` (e.g. `urn:msr:run:loader/<ts>`, `urn:msr:run:extraction/<ts>`) holding that source/run's PROV `Activity` (and its `Agent`/`Dataset` metadata), giving a coarse audit dimension. These graphs SHALL be written via additive SPARQL `Update` naming an explicit `GRAPH` target — never Graph Store `PUT` (`PutGraph`) — so no known-graph allowlist change is required and no graph-replace occurs. Fact-bearing individuals SHALL remain in `urn:msr:data` and reference the `Activity` via `prov:wasGeneratedBy`.

#### Scenario: A run writes its Activity into its own named graph
- **WHEN** a loader or extraction run completes a write
- **THEN** a single `prov:Activity` for that run exists in `urn:msr:run:<pipeline>/<ts>`, written via `INSERT DATA { GRAPH <urn:msr:run:...> { … } }`

#### Scenario: Everything from a run is reachable via its Activity
- **WHEN** facts are written for a run
- **THEN** each fact in `urn:msr:data` carries `prov:wasGeneratedBy` the run's `Activity` IRI, so all facts from that run are selectable by joining on the Activity

#### Scenario: Named-graph writes do not use graph-replace
- **WHEN** a source/run `Activity` is written
- **THEN** it is emitted with an additive `INSERT DATA` `GRAPH` target and no `PutGraph` / Graph Store `PUT` is issued for `urn:msr:src:*` or `urn:msr:run:*`
