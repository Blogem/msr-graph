# text-measurement-writing Specification

## Purpose

Define how a validated text-derived measurement is written consistently to **both** stores
the chunk-4 agent reads — a `msr:PropertyMeasurement` (with `msr:citedIn` the source
`Document`) in `urn:msr:data` and a `measurement_value` row (`source='document'`) in SQLite,
sharing one deterministic locator — with the equation-form/coefficient mapping, the SQLite
runtime contract enforced from Python, and idempotency across both stores.

## ADDED Requirements

### Requirement: Map the extracted correlation to an EquationForm and coefficients
The writer SHALL map the extracted correlation to a seed `msr:EquationForm` individual and
place its coefficients into `c0..c4`: `Linear` (`c0 + c1·T`), `Polynomial2`/`Polynomial3`,
`Arrhenius` (`c0·exp(c1/T)`), or `DiscretePoint` (a single value `c0` at temperature `c1`).
The coefficient count MUST match the mapped form, and a mismatch SHALL reject the
measurement. Coefficients SHALL live only in SQLite; the graph SHALL carry the equation form,
not the numbers.

#### Scenario: An Arrhenius viscosity equation maps to coefficients
- **WHEN** the extractor yields the viscosity correlation `η = 0.084·exp(4340/T)`
- **THEN** the writer maps it to `msr:Arrhenius` with `c0=0.084` and `c1=4340`, and no coefficient value is written to `urn:msr:data`

#### Scenario: A single value at a temperature maps to a DiscretePoint
- **WHEN** the extractor yields a single measured value at one temperature
- **THEN** the writer maps it to `msr:DiscretePoint` with the value in `c0` and the temperature in `c1`, and sets `validTempMin` equal to `validTempMax`

#### Scenario: A validity range is written both-bounds-or-neither, ordered
- **WHEN** a correlation is written with no stated validity range, or with only a single stated bound
- **THEN** the writer emits neither `msr:validTempMin` nor `msr:validTempMax` (a lone bound is dropped), and whenever both are emitted `validTempMin ≤ validTempMax` — so the write satisfies the merged SHACL `ValidTemperatureRangeShape` rather than being rejected at commit

#### Scenario: A coefficient-count mismatch is rejected
- **WHEN** the extracted coefficients do not match the mapped equation form's arity
- **THEN** the measurement is rejected and nothing is written

### Requirement: One shared deterministic locator and measurement IRI
Each measurement SHALL use the locator `doc/{report#}/{property}#{slug}` where `{slug}` is
the canonical salt form, and a measurement IRI deterministically derived from that locator
(no blank nodes). The same locator SHALL key both the graph node's `msr:dataLocator` and the
SQLite row's `locator` primary key. The `doc/{report#}/…` namespace keeps a text-derived
value from colliding with a NIST row (`nist-srd27/…`) for the same salt and property.

#### Scenario: Locator and IRI are derived from the salt, property, and document
- **WHEN** a FLiBe viscosity measurement is written from ORNL-TM-2316 for the loaded salt `msrd:salt-BeF2-LiF-34.0-66.0`
- **THEN** its locator is `doc/ORNL-TM-2316/viscosity#BeF2-LiF|34.0-66.0`, its measurement IRI is deterministically derived from that locator with no blank nodes, and the same locator appears in both `msr:dataLocator` and the SQLite `locator`

#### Scenario: A text value does not collide with a NIST value
- **WHEN** both a NIST and a text-derived value exist for the same salt and property
- **THEN** they occupy distinct locators (`nist-srd27/…` vs `doc/{report#}/…`) and distinct measurement nodes/rows

### Requirement: PropertyMeasurement triples written to the core data graph with citation
The writer SHALL emit the `msr:PropertyMeasurement` with `msr:ofSalt` (the loaded salt
individual the mention resolved to), `msr:forProperty`, `msr:hasUnit` (the validated QUDT
IRI), `msr:equationForm`, `msr:validTempMin`/`Max`, `msr:dataLocator`, `prov:wasDerivedFrom`
the source `Document`, `prov:wasGeneratedBy msrd:activity-extraction` (the stable per-pipeline
activity), and **`msr:citedIn`** that `Document`, into `urn:msr:data` via additive SPARQL
`INSERT DATA` through the chunk-5 Python SPARQL-UPDATE helper — never a graph-replace `PUT`,
so the chunk-2 catalog, chunk-5 `Document` nodes, and chunk-6 mentions are preserved. (`ground-demo-in-real-docs`
removed the seed A-Box, so there is no hand-curated data to preserve — `urn:msr:data` holds
only real-writer output.) `msr:citedIn` is the citation edge both the `provenance-model` and
`analysis-agent` main specs leave TBox-declared-but-unused and explicitly defer to this chunk;
a text-derived measurement genuinely originates in its source document, so asserting it here
fulfills that deferral truthfully.

#### Scenario: A text-derived measurement is citable to its source document
- **WHEN** a FLiBe viscosity statement in ORNL-TM-2316 is written
- **THEN** the graph gains a `msr:PropertyMeasurement` with `msr:citedIn msrd:ORNL-TM-2316`, `prov:wasDerivedFrom msrd:ORNL-TM-2316`, `prov:wasGeneratedBy msrd:activity-extraction`, `msr:ofSalt` the loaded FLiBe salt, `msr:forProperty msr:viscosity`, a QUDT unit, an equation form, and the shared `msr:dataLocator`

#### Scenario: Existing graph data is preserved by the additive write
- **WHEN** text-derived measurement triples are inserted into `urn:msr:data`
- **THEN** the chunk-2 catalog triples, chunk-5 `Document` nodes, and chunk-6 mention triples remain present (the additive insert replaces nothing)

### Requirement: Written measurements carry generation provenance and per-run lineage
The extraction run SHALL reuse the pipeline provenance helper (`provenance.py`, as `link` does)
rather than introduce a second provenance path, so that every text-derived measurement carries
generation provenance — consistent with the merged `provenance-model` spec, under which every
pipeline-asserted individual carries both derivation and generation provenance. Per `extract`
invocation it SHALL: type the stable `msrd:activity-extraction`
`prov:Activity` once in `urn:msr:data` (timestamp-free, a no-op on re-run); write one per-run
`prov:Activity` node `<urn:msr:run:extraction/<ts>>` into `urn:msr:provenance` (attributed
`prov:wasAssociatedWith` the extraction agent, with start/end timestamps and ontology
`owl:versionInfo`) **before** any fact; and, for **each** written text-derived
`msr:PropertyMeasurement`, emit one `<measurement> prov:wasGeneratedBy
<urn:msr:run:extraction/<ts>>` generation edge into `urn:msr:provenance` (in addition to the
stable `prov:wasGeneratedBy msrd:activity-extraction` edge in `urn:msr:data`). All
`urn:msr:provenance` writes SHALL be additive `INSERT DATA { GRAPH <urn:msr:provenance> { … } }`
(never a graph-replace `PUT`), and the timestamp SHALL be generated once per invocation and
shared by the run.

#### Scenario: A measurement references both the stable and the per-run activity
- **WHEN** the extraction run writes a text-derived `msr:PropertyMeasurement`
- **THEN** the measurement carries `prov:wasGeneratedBy msrd:activity-extraction` in `urn:msr:data`, and `urn:msr:provenance` carries `<measurement> prov:wasGeneratedBy <urn:msr:run:extraction/<ts>>` plus the attributed per-run `prov:Activity` node

#### Scenario: The provenance graph is append-only across runs
- **WHEN** the extraction runs twice at distinct wall-clock timestamps over the same corpus
- **THEN** `urn:msr:data`'s triple count and `measurement_value`'s row count are unchanged, while `urn:msr:provenance` gains a second per-run activity node and a second set of generation edges

### Requirement: Writes conform to commit-time SHACL and rejections are surfaced legibly
The writer's `urn:msr:data` writes SHALL satisfy the installed SHACL shapes by construction,
because the `msr` GraphDB repository enforces SHACL at commit (`shacl-validation`): every
text-derived `msr:PropertyMeasurement` carries the seven properties `PropertyMeasurementShape`
requires
(`prov:wasDerivedFrom`, `prov:wasGeneratedBy`, `msr:dataLocator`, `msr:forProperty`,
`msr:ofSalt`, `msr:hasUnit`, `msr:equationForm`), an `msr:hasUnit` in the QUDT allowlist, and a
both-bounds-or-neither ordered temperature range. When a commit is nonetheless rejected by
SHACL, the Python write path (`sparql.py`) SHALL surface it as a typed validation error carrying
the RDF4J validation report — distinct from a generic transport error — so a rejected write is
debuggable (satisfying the `shacl-validation` "reports legible to writers" requirement, which
names extraction writers). Chunk 7 adds and changes no SHACL shape.

#### Scenario: A conforming measurement is accepted by SHACL
- **WHEN** a validated text-derived measurement carrying all seven required properties and an allowlisted unit is committed to the SHACL-enabled `msr` repo
- **THEN** the commit succeeds and the measurement is queryable

#### Scenario: A SHACL rejection is surfaced as a typed validation error
- **WHEN** a graph write is rejected by the repository's SHACL validation
- **THEN** the Python write path raises a typed validation error carrying the validation report (naming the failing shape/focus node), distinguishable from a generic transport failure

### Requirement: Extraction-provenance vocabulary in the seed ontology
The change SHALL add a small, self-contained extraction-provenance vocabulary to
`ontology/msr.ttl` (loaded into `urn:msr:ontology` by the existing `make load-seed`
graph-replace `PUT`): `msr:extractionConfidence` (a datatype property, range `xsd:decimal`)
and `msr:extractionRationale` (a datatype property, range `xsd:string`). The properties SHALL
be domain-agnostic so they attach either directly to a text-derived `msr:PropertyMeasurement`
or to a reified role/reactor edge (`rdf:Statement`). This is additive pipeline-infrastructure
schema loaded up front, not a reviewable evolution candidate, so it does not pass through
staging.

#### Scenario: Extraction-provenance TBox loaded with the seed
- **WHEN** `make load-seed` runs after the extraction-provenance vocabulary is added to `ontology/msr.ttl`
- **THEN** `urn:msr:ontology` contains `msr:extractionConfidence` and `msr:extractionRationale`

### Requirement: Written measurements carry queryable extraction confidence and rationale
Each written text-derived `msr:PropertyMeasurement` SHALL carry `msr:extractionConfidence`
(the extractor's 0–1 confidence) and `msr:extractionRationale` (a short rationale/evidence
string), so both are queryable through the core-dataset client alongside the measurement's
property, unit, and locator. A NIST (loaded, not extracted) measurement SHALL carry neither,
so their presence marks a measurement as text-derived. These extraction-provenance properties
are distinct from the physical `msr:uncertainty` string.

#### Scenario: A text-derived measurement exposes confidence and rationale
- **WHEN** a text-derived FLiBe viscosity measurement is written and then queried through the core-dataset client
- **THEN** the measurement carries `msr:extractionConfidence` and `msr:extractionRationale`, queryable alongside its property, unit, and locator

#### Scenario: A NIST measurement carries no extraction provenance
- **WHEN** a NIST-loaded measurement is queried
- **THEN** it carries neither `msr:extractionConfidence` nor `msr:extractionRationale`

### Requirement: measurement_value rows written from Python honoring the SQLite runtime contract
The writer SHALL insert one `measurement_value` row per measurement with `source='document'`,
`doc_id` set to the report number, `salt` in canonical form, the `property`, the mapped
`equation_form`, `t_min`/`t_max`, the source-stated physical `uncertainty` string when the
prose gives one (distinct from the extraction confidence, which lives in the
`relations.jsonl` trace), and `c0..c4`. Writes SHALL use
Python stdlib `sqlite3` through a connection helper that pins `journal_mode=DELETE` and a
non-zero `busy_timeout` on every connection, so no `-wal`/`-shm` sidecar file is ever
created next to the database (the sandboxes' read-only directory mounts depend on this).

#### Scenario: A document row lands with source and doc_id set
- **WHEN** the FLiBe viscosity measurement is written to SQLite
- **THEN** `measurement_value` holds a row with `source='document'`, `doc_id='ORNL-TM-2316'`, the canonical `salt`, `property='viscosity'`, `equation_form` Arrhenius, and `c0=0.084`, `c1=4340`

#### Scenario: No WAL sidecar files are created
- **WHEN** the Python writer opens a connection and writes rows
- **THEN** `PRAGMA journal_mode` reports `delete`, a non-zero `busy_timeout` is set, and no `-wal` or `-shm` file exists next to the database file

### Requirement: Idempotent across both stores
Re-running the extraction SHALL leave both stores unchanged: graph triples re-assert as a
set-semantics no-op via deterministic IRIs and no blank nodes, and SQLite rows upsert on the
`locator` primary key. Per-graph triple counts and `measurement_value` row counts MUST be
identical after a second run.

#### Scenario: A second run changes nothing
- **WHEN** the extraction runs twice over the same corpus and mentions
- **THEN** the `urn:msr:data` triple count and the `measurement_value` row count are identical after the second run

### Requirement: Text-derived measurements answerable by the unchanged agent
A text-derived measurement SHALL be readable through the core-dataset client exactly like a
NIST measurement (same `PropertyMeasurement` shape, resolvable `dataLocator`), so the
schema-generic chunk-4 agent can ground and answer questions about it with no agent code
change.

#### Scenario: The agent answers from a text-derived measurement without code changes
- **WHEN** a text-derived `PropertyMeasurement` and its `measurement_value` row are present that were not before
- **THEN** a core-dataset SPARQL query returns the measurement with a resolvable `dataLocator`, and the agent can answer a question using it with no change to the agent's code

### Requirement: A measurement requires a composed salt individual
The writer SHALL attach a measurement only to a specific loaded `MoltenSalt` individual. A
mention that resolved (via chunk 6) to a bare salt concept rather than a composed individual
SHALL NOT anchor a composed measurement; such a case SHALL be skipped and recorded in the
run summary rather than guessing a composition.

#### Scenario: A bare-concept salt mention does not produce a measurement
- **WHEN** a measurement statement's salt resolved only to a salt concept (no composition)
- **THEN** no measurement is written for it and the skip is recorded in the run summary
