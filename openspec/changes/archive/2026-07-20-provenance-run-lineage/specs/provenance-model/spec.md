# provenance-model (delta)

## ADDED Requirements

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

## MODIFIED Requirements

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

## REMOVED Requirements

### Requirement: Per-source and per-run named graphs carry an Activity record
**Reason**: Replaced by the single `urn:msr:provenance` graph. The per-run graph `urn:msr:run:<pipeline>/<ts>` and the per-source graph `urn:msr:src:*` are no longer created; the run identifier survives as the per-run activity node IRI inside `urn:msr:provenance`, and the `Dataset` source node is self-contained in `urn:msr:data`. See the ADDED requirements "A single provenance graph holds run activities and lineage" and "Per-run generation lineage".
**Migration**: None (POC data is disposable). Pre-existing `urn:msr:run:*` / `urn:msr:src:*` graphs are orphaned and removed on the next clean repo rebuild.
