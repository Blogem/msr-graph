## ADDED Requirements

### Requirement: SHACL validation enforced at commit time
The `msr` GraphDB repository SHALL be configured with native SHACL validation (RDF4J `ShaclSail`) enabled, so that every transaction is validated against the installed shapes graph on commit. A transaction whose resulting data violates any installed shape MUST be rejected atomically — none of its triples are persisted — and a valid transaction MUST commit unchanged. Validation MUST operate with inference disabled (architecture decision D2 is preserved).

#### Scenario: Violating write is rejected atomically
- **WHEN** a SPARQL update or graph-store write would leave a fact-bearing individual in violation of an installed shape
- **THEN** the commit is rejected, none of the transaction's triples are persisted, and the store is unchanged from before the write

#### Scenario: Valid write commits unchanged
- **WHEN** a write whose data satisfies every installed shape is committed
- **THEN** the transaction succeeds and all its triples are queryable afterward

#### Scenario: Inference remains disabled
- **WHEN** the SHACL-enabled `msr` repository is inspected
- **THEN** it has no inference ruleset (ruleset "empty") and no triples are materialized by a reasoner

### Requirement: Shape catalogue installed in the reserved shapes graph
The shape catalogue SHALL be authored as a versioned Turtle artifact in the repository and loaded into the RDF4J reserved shapes graph (`http://rdf4j.org/schema/rdf4j#SHACLShapeGraph`). Installing or updating shapes MUST be performed as a graph update, and the bootstrap MUST install the catalogue so a freshly provisioned stack enforces the shapes without a manual step.

#### Scenario: Bootstrap installs the shapes
- **WHEN** the stack is brought up against a fresh GraphDB data volume
- **THEN** the shape catalogue is present in the reserved shapes graph and validation is active for subsequent writes

#### Scenario: Shapes are a versioned artifact
- **WHEN** the shape catalogue is changed
- **THEN** the change is a diff to the committed Turtle artifact, and re-loading it replaces the shapes graph contents without recreating the repository

### Requirement: Measurement provenance and completeness shape
The catalogue SHALL include a shape targeting `msr:PropertyMeasurement` that requires (minCount 1 each) `prov:wasDerivedFrom`, `msr:dataLocator`, `msr:citedIn`, `msr:forProperty`, `msr:ofSalt`, `msr:hasUnit`, and `msr:equationForm`. A measurement missing any of these MUST cause its transaction to be rejected.

#### Scenario: Measurement missing citation is rejected
- **WHEN** a `msr:PropertyMeasurement` is written without `msr:citedIn` (or any other required property)
- **THEN** the commit is rejected with a report naming the failing constraint and focus node

#### Scenario: Complete measurement is accepted
- **WHEN** a `msr:PropertyMeasurement` carrying all required properties is written
- **THEN** the commit succeeds

### Requirement: Mention provenance shape
The catalogue SHALL include a shape targeting `msr:Mention` that requires (minCount 1 each) `msr:inDocument`, `msr:startOffset`, `msr:endOffset`, and `msr:surfaceForm`. A mention missing any of these MUST cause its transaction to be rejected.

#### Scenario: Mention without source document is rejected
- **WHEN** a `msr:Mention` is written without `msr:inDocument`
- **THEN** the commit is rejected with a validation report

#### Scenario: Complete mention is accepted
- **WHEN** a `msr:Mention` carrying `msr:inDocument`, `msr:startOffset`, `msr:endOffset`, and `msr:surfaceForm` is written
- **THEN** the commit succeeds

### Requirement: Unit allowlist data-quality shape
The catalogue SHALL constrain a measurement's `msr:hasUnit` to the QUDT allowlist. The allowed set MUST be derived from `ontology/qudt-units.json` (the single source of truth) rather than hand-maintained in the shape, so the shape and the loader agree on the allowlist.

#### Scenario: Non-allowlist unit is rejected
- **WHEN** a measurement is written with a `msr:hasUnit` IRI not present in the QUDT allowlist
- **THEN** the commit is rejected with a validation report

#### Scenario: Allowlisted unit is accepted
- **WHEN** a measurement is written with a `msr:hasUnit` IRI present in the allowlist
- **THEN** the commit succeeds

### Requirement: Valid-temperature-range data-quality shape
The catalogue SHALL enforce that when a measurement carries a valid-temperature range, both bounds are present and `validTempMin ≤ validTempMax`. An inverted or half-populated range MUST cause its transaction to be rejected.

#### Scenario: Inverted range is rejected
- **WHEN** a measurement is written with `validTempMin` greater than `validTempMax`
- **THEN** the commit is rejected with a validation report

#### Scenario: Well-ordered range is accepted
- **WHEN** a measurement is written with `validTempMin ≤ validTempMax`
- **THEN** the commit succeeds

### Requirement: linksTo target-kind data-quality shape
The catalogue SHALL constrain `msr:linksTo` so it may only reference an existing target of the expected kind (concept / class / individual). A `linksTo` pointing at a missing or wrong-kind target MUST cause its transaction to be rejected.

#### Scenario: Dangling or wrong-kind link is rejected
- **WHEN** a triple asserts `msr:linksTo` to an IRI that is not an existing target of the expected kind
- **THEN** the commit is rejected with a validation report

#### Scenario: Well-formed link is accepted
- **WHEN** a triple asserts `msr:linksTo` to an existing target of the expected kind
- **THEN** the commit succeeds

### Requirement: Validation reports are legible to writers
When a commit is rejected, the graph write path SHALL surface a validation error that identifies the failing shape/constraint and the focus node(s), rather than an opaque transport error. Callers (`cmd/loader`, extraction writers) MUST be able to distinguish a validation rejection from other write failures.

#### Scenario: Rejection carries actionable detail
- **WHEN** a write is rejected by SHACL
- **THEN** the error returned to the caller names the violated constraint and the offending focus node, and is classifiable as a validation failure (not a generic 5xx)

### Requirement: Bulk-load validation strategy
Batch writes (NIST loader, extraction writers) SHALL be validated **per transaction (incrementally)**: each write transaction is validated on commit, so a batch containing any invalid record surfaces the violation and MUST NOT leave partially-valid data silently committed. The repository's transactional-validation limit MUST be configured above the size of the POC's batch writes so real loads stay on the transactional-validation path; load-then-validate is retained only as a documented fallback should a future ingest exceed that limit.

#### Scenario: Invalid record in a batch does not silently persist
- **WHEN** a batch load includes at least one record violating a shape
- **THEN** the load surfaces the violation and does not leave the batch's invalid data committed as if it were valid

#### Scenario: Valid batch loads on the transactional path
- **WHEN** a batch of fully valid records within the transactional-validation limit is loaded
- **THEN** all records are committed and validation runs per transaction (not deferred to a whole-repository pass)
