# nist-structured-loading (delta)

## MODIFIED Requirements

### Requirement: Idempotent re-runs across both stores
Re-running `loader nist` SHALL leave both fact stores unchanged: catalog and provenance triples in `urn:msr:data` re-assert as a set-semantics no-op via deterministic IRIs (including the deterministic `msrd:activity-loader-nist` `Activity` IRI referenced by every measurement's `prov:wasGeneratedBy`, the stable `Activity` typing, and the self-contained `Dataset`/`Document` nodes), and SQLite rows upsert on the `locator` primary key. The `urn:msr:data` triple count and the `measurement_value` row count MUST be identical after a second run. The `urn:msr:provenance` graph is explicitly **outside** this guarantee: each wall-clock run appends a new per-run `Activity` (`urn:msr:run:loader/<ts>`) plus one `prov:wasGeneratedBy` generation edge for every fact the run asserts, so `urn:msr:provenance` grows on each run.

#### Scenario: Second run leaves the fact stores unchanged
- **WHEN** `loader nist` is run twice against the same stores
- **THEN** the `urn:msr:data` triple count and the `measurement_value` row count are identical after the second run (new per-run provenance is appended to `urn:msr:provenance`)

#### Scenario: Re-asserting salts across runs is a no-op in the data graph
- **WHEN** `loader nist` emits catalog triples for a salt it already emitted on a prior run (e.g. the FLiBe salt)
- **THEN** no duplicate salt, constituent, or measurement node is created in `urn:msr:data` because the minted IRIs are deterministic, while `urn:msr:provenance` gains a second per-run generation edge for that salt

### Requirement: Loader-run activity recorded in a named graph
Every fact-bearing individual the loader emits (each `msr:MoltenSalt`, `msr:Constituent`, `msr:ChemicalCompound`, and `msr:PropertyMeasurement`, plus the `Dataset` node) SHALL reference the deterministic **stable** `Activity` IRI `msrd:activity-loader-nist` via `prov:wasGeneratedBy` in `urn:msr:data`, and the loader SHALL type that stable `Activity` in `urn:msr:data` — `msrd:activity-loader-nist a prov:Activity ; prov:wasAssociatedWith <agent:loader@<version>> ; owl:versionInfo "<version>"` — with **no timestamps**, so `urn:msr:data` stays idempotent. The loader SHALL additionally write, into `urn:msr:provenance`, a **per-run** `Activity` node `<urn:msr:run:loader/<ts>>` (typed `a prov:Activity`, attributed `prov:wasAssociatedWith agent:loader@<version>`, with `prov:startedAtTime`/`prov:endedAtTime` and the ontology `owl:versionInfo`) and one `<factIRI> prov:wasGeneratedBy <urn:msr:run:loader/<ts>>` edge for **every** fact IRI it asserts. All `urn:msr:provenance` writes SHALL use additive `INSERT DATA` with an explicit `GRAPH <urn:msr:provenance>` target (not `PutGraph`). The loader SHALL NOT create a `urn:msr:src:*` or `urn:msr:run:*` named graph.

#### Scenario: Run activity and lineage written and referenced
- **WHEN** `loader nist` completes
- **THEN** every emitted fact in `urn:msr:data` carries `prov:wasGeneratedBy msrd:activity-loader-nist`, the stable `msrd:activity-loader-nist` is typed in `urn:msr:data` without timestamps, and `urn:msr:provenance` holds a per-run `<urn:msr:run:loader/<ts>>` activity (agent, timestamps, ontology version) plus one generation edge per emitted fact

#### Scenario: No per-source or per-run graph is created
- **WHEN** `loader nist` writes provenance
- **THEN** no `urn:msr:src:nist-srd27` graph and no `urn:msr:run:loader/<ts>` graph exist; the run identifier appears only as the per-run activity node IRI inside `urn:msr:provenance`, and the `Dataset` node is present only in `urn:msr:data`
