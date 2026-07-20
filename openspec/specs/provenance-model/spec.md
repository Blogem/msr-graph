# provenance-model Specification

## Purpose

Define a PROV-O-based provenance model for the knowledge graph: a self-contained PROV-O slice in the seed ontology, mandatory generation/derivation provenance on every pipeline-asserted instance individual, two `prov:Activity` IRIs per pipeline (a stable untimestamped per-pipeline activity in `urn:msr:data` referenced by every fact, and a timestamped per-run activity in the single append-only `urn:msr:provenance` graph), and per-run generation-lineage edges holding that run activity plus one generation edge per asserted fact via additive updates into `urn:msr:provenance`. The model lets any fact be attributed to who/what/when produced it without fabricating provenance.

## Requirements

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
Provenance SHALL use **two** `prov:Activity` IRIs per pipeline:

- A **stable per-pipeline** IRI (`msrd:activity-loader-nist`, `msrd:activity-extraction`) referenced by every fact via `prov:wasGeneratedBy` in `urn:msr:data`. This IRI SHALL be typed `a prov:Activity` and attributed `prov:wasAssociatedWith` a `prov:Agent` (`agent:<pipeline>@<version>`) with the ontology `owl:versionInfo`, all asserted in `urn:msr:data` **without timestamps**, so the fact-level edge and the activity typing re-assert as a set-semantics no-op.
- A **per-run** IRI (`urn:msr:run:<pipeline>/<ts>`) asserted in `urn:msr:provenance`, typed `a prov:Activity` and carrying `prov:wasAssociatedWith` the `prov:Agent`, `prov:startedAtTime`/`prov:endedAtTime` from the producing process clock, and the run's `owl:versionInfo`. This node carries the wall-clock facets and is the target of the per-run generation-lineage edges.

The two share the same `prov:Agent`; no `Activity`→`Activity` edge between them is required.

#### Scenario: The stable pipeline activity is typed idempotently in the data graph
- **WHEN** a pipeline writes facts
- **THEN** `urn:msr:data` contains `msrd:activity-<pipeline> a prov:Activity ; prov:wasAssociatedWith <agent:<pipeline>@<version>>` with no timestamp literals, and re-running does not change the `urn:msr:data` triple count

#### Scenario: A per-run activity is fully attributed in the provenance graph
- **WHEN** a loader or extraction run completes
- **THEN** `urn:msr:provenance` contains `<urn:msr:run:<pipeline>/<ts>> a prov:Activity` with `prov:wasAssociatedWith agent:<pipeline>@<version>`, start/end timestamps, and the ontology `owl:versionInfo`

### Requirement: Per-run generation lineage
Every pipeline run SHALL record, for **each fact-bearing individual it asserts**, a `prov:wasGeneratedBy` edge from that individual to the run's **per-run** `prov:Activity` IRI, written into the `urn:msr:provenance` graph. The per-run activity IRI is the run identifier used as a node: `urn:msr:run:<pipeline>/<ts>` (e.g. `urn:msr:run:loader/<ts>`, `urn:msr:run:extraction/<ts>`). A run SHALL emit this edge for every fact it asserts, **including facts already present in `urn:msr:data`** (a no-op against the data graph); no read-before-write is performed. Consequently a fact asserted by N runs accumulates N per-run generation edges in `urn:msr:provenance` — that set is the fact's per-run lineage. This is distinct from, and additional to, the fact's single **stable** `prov:wasGeneratedBy msrd:activity-<pipeline>` edge in `urn:msr:data`.

#### Scenario: A run records a generation edge per asserted fact
- **WHEN** a loader or extraction run asserts fact-bearing individuals
- **THEN** `urn:msr:provenance` contains `<individual> prov:wasGeneratedBy <urn:msr:run:<pipeline>/<ts>>` for each such individual

#### Scenario: A fact asserted by multiple runs accumulates one edge per run
- **WHEN** two runs at distinct timestamps each assert the same fact (identical deterministic IRI, a no-op in `urn:msr:data` on the second run)
- **THEN** `urn:msr:provenance` contains two `prov:wasGeneratedBy` edges for that fact, one per run, while `urn:msr:data` still carries exactly one stable `prov:wasGeneratedBy msrd:activity-<pipeline>` edge

#### Scenario: Lineage is queryable both directions
- **WHEN** querying `urn:msr:provenance`
- **THEN** "which runs produced fact F" is `<F> prov:wasGeneratedBy ?run` and "what did run R assert" is `?f prov:wasGeneratedBy <R>`, both without needing a per-run graph

### Requirement: A single provenance graph holds run activities and lineage
All per-run `prov:Activity` records and all per-run generation-lineage edges SHALL live in **one** named graph, `urn:msr:provenance`. Per-run graphs `urn:msr:run:<pipeline>/<ts>` and per-source graphs `urn:msr:src:*` SHALL NOT be used as graph names (the run identifier survives only as the per-run activity *node* IRI; the source `Dataset` node is self-contained in `urn:msr:data`). `urn:msr:provenance` SHALL be written via additive SPARQL `Update` naming an explicit `GRAPH` target — never Graph Store `PUT` (`PutGraph`). It is **append-only**: a wall-clock re-run appends a new per-run activity and its generation edges (it is outside the `urn:msr:data` idempotency guarantee). Fact-bearing individuals SHALL remain in `urn:msr:data` and reference the stable `Activity` via `prov:wasGeneratedBy`.

#### Scenario: Run provenance is written into the single provenance graph
- **WHEN** a loader or extraction run completes a write
- **THEN** its per-run `prov:Activity` and its `prov:wasGeneratedBy` lineage edges are present in `urn:msr:provenance`, written via `INSERT DATA { GRAPH <urn:msr:provenance> { … } }`, and no `urn:msr:run:*` or `urn:msr:src:*` graph is created

#### Scenario: The provenance graph is append-only across runs
- **WHEN** a pipeline runs twice at distinct wall-clock timestamps
- **THEN** `urn:msr:provenance` gains a second per-run activity and a second set of generation edges (it grows), while `urn:msr:data` is unchanged

#### Scenario: Named-graph writes do not use graph-replace
- **WHEN** provenance is written
- **THEN** it is emitted with an additive `INSERT DATA` `GRAPH <urn:msr:provenance>` target and no `PutGraph` / Graph Store `PUT` is issued
