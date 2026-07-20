# proposal-staging Specification

## Purpose

Define how TBox-affecting candidates are emitted as proposals: deterministic proposal IRIs
written additively to `urn:msr:staging` and `urn:msr:proposal/{id}` (idempotent re-runs), a
QUDT-allowlist guard on any concrete asserted `qk:`/`unit:` IRI, and the invisibility of
everything in staging to the core dataset.

## Requirements

### Requirement: Deterministic proposal IRIs, no blank nodes
The `msr:ChangeProposal` resource SHALL have a deterministic IRI derived from its kind and
term slug (`msrd:proposal-{kind}-{term-slug}`) and its proposal graph SHALL be
`urn:msr:proposal/{kind}-{term-slug}`; evidence nodes SHALL have deterministic IRIs derived
from report number + offsets. No blank nodes SHALL be written.

#### Scenario: A candidate mints deterministic proposal IRIs
- **WHEN** a `property` candidate for `solubility` is emitted
- **THEN** the resource is `msrd:proposal-property-solubility`, its proposal graph is `urn:msr:proposal/property-solubility`, and no blank nodes are written

### Requirement: Additive writes, idempotent across re-runs
Proposal triples SHALL be written via additive SPARQL `INSERT DATA` into the explicit target
graphs (`urn:msr:staging` for the resource, `urn:msr:proposal/{id}` for the proposed
triples), never a graph-replace `PUT`. Because IRIs are deterministic and there are no blank
nodes, re-running the miner over the same corpus MUST leave the `urn:msr:staging` and
`urn:msr:proposal/{id}` triple counts unchanged.

#### Scenario: Re-run adds no duplicate proposals
- **WHEN** the miner runs twice over the same corpus
- **THEN** the second run leaves the staging and proposal-graph triple counts identical to after the first

### Requirement: QUDT-allowlist guard on asserted unit and quantity-kind IRIs
A concrete `unit:` or `qk:` IRI asserted in a proposal graph MUST be present in the vendored
`ontology/qudt-units.json` allowlist (`allowedUnits` / `allowedQuantityKinds`); otherwise the
entire proposal SHALL be rejected — dropped from the run and not written. A proposal that
asserts no concrete `unit:`/`qk:` IRI (e.g. a property whose unit is left as a reviewer
decision) SHALL NOT be rejected by this guard. This guard — not SHACL — is what protects proposal
graphs: the landed `shacl-validation` unit shape constrains only a `msr:PropertyMeasurement`'s
`msr:hasUnit`, and the miner writes no measurements, so a proposed property's unit is not
otherwise validated. Both the guard and the SHACL unit shape derive from the same
`ontology/qudt-units.json`, so they cannot drift.

#### Scenario: An out-of-allowlist unit rejects the proposal
- **WHEN** a proposal would assert a `unit:` IRI absent from the allowlist
- **THEN** the proposal is rejected and nothing is written for it

#### Scenario: A unit-less property proposal is emitted
- **WHEN** a `property` proposal leaves `canonicalUnit` and `quantityKind` unset (unit ambiguous)
- **THEN** the allowlist guard does not fire and the proposal is written with the unit left as a reviewer decision

### Requirement: Proposals are invisible to the core dataset
Everything a proposal writes to `urn:msr:staging` and `urn:msr:proposal/{id}` MUST NOT appear
in a read through the core-dataset contract (the three core `FROM` graphs), so the analysis
agent and every normal query never see pending candidates; the same triples MUST be visible
in a raw query that names the staging/proposal graphs.

#### Scenario: A mined proposal is hidden from core, visible in staging
- **WHEN** a proposal is written and then queried
- **THEN** it does not appear via the core-dataset client but does appear in a raw query against `urn:msr:staging` / `urn:msr:proposal/{id}`
