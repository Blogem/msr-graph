# instance-auto-accept Specification

## Purpose

Define how instance-kind candidates bypass the review gate: a new individual typed by an
existing class is written directly to `urn:msr:data` flagged `msr:autoAccepted` and
provenance-complete per the merged `provenance-model` contract, while an individual that depends
on proposed schema instead rides its proposal's bundle and reaches `urn:msr:data` only on
approval.

## ADDED Requirements

### Requirement: Instances under an existing class are auto-accepted to core data
The miner SHALL write an `instance`-kind candidate whose type and edges resolve entirely
within the current core schema directly to `urn:msr:data` with a deterministic IRI, flagged
`msr:autoAccepted true`, and **provenance-complete per the `provenance-model` contract**: the
individual SHALL carry `prov:wasGeneratedBy msrd:activity-mine` and `prov:wasDerivedFrom` the
source `msr:Document` it was mined from. Such a candidate SHALL NOT create a `ChangeProposal`
and SHALL NOT be written to `urn:msr:staging` or a proposal graph — the schema is unchanged, so
there is nothing to review. No `msr:citedIn` is asserted on the individual — that predicate is
deferred to chunk-7 citation extraction; the derivation root is the `prov:wasDerivedFrom`
document. Because the landed `shacl-validation` `CatalogIndividualProvenanceShape` targets
`msr:MoltenSalt`/`msr:Constituent`/`msr:ChemicalCompound` and requires both PROV edges, this
provenance is enforced at commit: an auto-accepted individual missing either edge is rejected
atomically (the whole `INSERT DATA` rolls back), so provenance-completeness is a hard gate, not a
convention.

#### Scenario: A new salt under MoltenSalt is written directly to data
- **WHEN** an `instance` candidate is a new specific salt/compound typed by the existing `msr:MoltenSalt` (or another existing) class
- **THEN** it is written to `urn:msr:data` flagged `msr:autoAccepted true` carrying `prov:wasGeneratedBy msrd:activity-mine` and `prov:wasDerivedFrom` its source `msr:Document`, and no `ChangeProposal` is created

#### Scenario: The auto-accepted write is accepted by SHACL, an under-provenanced one is rejected
- **WHEN** the provenance-complete auto-accepted `msr:MoltenSalt`/`msr:ChemicalCompound` individual is committed to the SHACL-enabled `msr` repo
- **THEN** the commit is accepted (it satisfies `CatalogIndividualProvenanceShape`); an otherwise-identical individual written without `prov:wasGeneratedBy` or `prov:wasDerivedFrom` is rejected atomically with a validation report and none of its triples persist

### Requirement: The mine run records provenance activities and per-run lineage
Following the `provenance-model` two-activity pattern, the miner SHALL type the stable
per-pipeline activity `msrd:activity-mine a prov:Activity ; prov:wasAssociatedWith
agent:mine@<version>` (with the ontology `owl:versionInfo`, no timestamps) once in
`urn:msr:data` — idempotent across re-runs — and SHALL append to the `urn:msr:provenance`
graph, via additive `INSERT DATA` naming an explicit `GRAPH` target (never Graph Store `PUT`), a
per-run activity node `urn:msr:run:mine/<ts>` (with `prov:wasAssociatedWith`,
`prov:startedAtTime`/`prov:endedAtTime`, and `owl:versionInfo`) plus one `prov:wasGeneratedBy
<urn:msr:run:mine/<ts>>` generation edge for every fact the run asserts.

#### Scenario: The stable mine activity is typed idempotently in the data graph
- **WHEN** the miner auto-accepts one or more individuals
- **THEN** `urn:msr:data` contains `msrd:activity-mine a prov:Activity ; prov:wasAssociatedWith agent:mine@<version>` with no timestamp literals, and a re-run leaves the `urn:msr:data` triple count unchanged

#### Scenario: Per-run activity and lineage land in the provenance graph
- **WHEN** a `mine` run auto-accepts facts
- **THEN** `urn:msr:provenance` contains `<urn:msr:run:mine/<ts>> a prov:Activity` with agent, start/end timestamps, and `owl:versionInfo`, plus a `prov:wasGeneratedBy` edge from each asserted fact to that run node, written with `INSERT DATA { GRAPH <urn:msr:provenance> { … } }`

#### Scenario: The provenance graph is append-only across runs
- **WHEN** the miner runs twice at distinct wall-clock timestamps
- **THEN** `urn:msr:provenance` gains a second per-run activity and a second set of generation edges, while the `msr:autoAccepted` triple count in `urn:msr:data` is unchanged

### Requirement: Instances depending on proposed schema ride the proposal bundle
The miner SHALL NOT auto-accept an individual that can only be typed or related by proposed
schema (a class or property that is itself a pending proposal); instead it SHALL be written
into that proposal's `urn:msr:proposal/{id}` graph — carrying the same
`prov:wasGeneratedBy`/`prov:wasDerivedFrom` edges as an auto-accepted individual — so it reaches
`urn:msr:data` provenance-complete only when chunk 9 approves the bundle.

#### Scenario: graphite rides the Moderator proposal
- **WHEN** the `msrd:graphite` individual depends on the proposed `msr:Moderator` class
- **THEN** `msrd:graphite` (typed by the proposed `msr:Moderator`, with its `prov:wasGeneratedBy`/`prov:wasDerivedFrom` edges) is written into the graphite proposal's `urn:msr:proposal/{id}` graph, and nothing is written to `urn:msr:data` for it during mining

### Requirement: Auto-accepted individuals are idempotent
Re-running the miner MUST leave the `urn:msr:data` auto-accepted-triple count unchanged,
because auto-accepted individuals have deterministic IRIs and no blank nodes.

#### Scenario: Re-run adds no duplicate auto-accepted instances
- **WHEN** the miner runs twice over the same corpus
- **THEN** the second run leaves the count of `msr:autoAccepted` triples in `urn:msr:data` identical to after the first
