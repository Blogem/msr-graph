# change-proposal-schema Specification

## Purpose

Define the `msr:ChangeProposal` mini-schema added to the seed ontology and the two-graph
staging data model — a `ChangeProposal` resource in `urn:msr:staging` linked to its proposed
triples in `urn:msr:proposal/{id}` — which together are the contract chunk 9's governance API
reads, renders as a diff, and routes on approval.

## ADDED Requirements

### Requirement: ChangeProposal governance vocabulary in the seed ontology
The change SHALL add a self-contained governance vocabulary to `ontology/msr.ttl` (loaded into
`urn:msr:ontology` by the existing `make load-seed` graph-replace `PUT`): an
`msr:ChangeProposal` class and the properties needed to describe a proposal — its primary
kind, its review status, the mined term, the document-frequency count, a link to its proposal
graph, and structured evidence (sentence text plus the reused `msr:citedIn` document link and
`msr:startOffset`/`msr:endOffset` from chunk 6) — plus an `msr:autoAccepted` flag for
directly-written instances. This is pipeline-infrastructure schema loaded up front, not a
reviewable evolution candidate, so it does not pass through staging.

#### Scenario: Governance TBox loaded with the seed
- **WHEN** `make load-seed` runs after the governance vocabulary is added to `ontology/msr.ttl`
- **THEN** `urn:msr:ontology` contains the `msr:ChangeProposal` class and its properties

### Requirement: Two-graph staging model per proposal
A proposal SHALL be represented as two parts: a `msr:ChangeProposal` resource written to
`urn:msr:staging` (carrying kind, review status, term, document frequency, evidence, and an
`msr:hasProposalGraph` link) and the actual proposed triples written to a dedicated
`urn:msr:proposal/{id}` named graph. The `ChangeProposal` resource MUST reference its proposal
graph, so chunk 9 can list staging, resolve the proposal graph, and route its triples.

#### Scenario: Proposal split across staging and proposal graph
- **WHEN** a proposal for `solubility` is written
- **THEN** the `msr:ChangeProposal` resource is in `urn:msr:staging` with `msr:hasProposalGraph` pointing at `urn:msr:proposal/{id}`, and the proposed `msr:solubility` / `voc:solubility` triples are in that `urn:msr:proposal/{id}` graph

### Requirement: New proposals are created with pending status
Every `msr:ChangeProposal` the miner writes SHALL have review status `pending`. The miner
SHALL NOT set `approved` or `rejected` — status transitions are chunk 9's responsibility.

#### Scenario: Mined proposal is pending
- **WHEN** the miner writes a new proposal
- **THEN** its `msr:reviewStatus` is `pending`

### Requirement: Primary kind is for display; a bundle may mix triple types
The `msr:kind` of a proposal SHALL record the primary kind for triage and display, but the
proposal graph MAY contain a mix of TBox axioms and instance triples in one bundle. The
schema MUST NOT require the proposal graph's triples to all match the primary kind, because
approval routing (chunk 9) routes each triple by what it is, ignoring `msr:kind`.

#### Scenario: A class proposal bundles a relation and an individual
- **WHEN** the `graphite` proposal is written with `msr:kind "class"`
- **THEN** its proposal graph contains the `msr:Moderator` class, the `msr:moderatedBy` property, the `msrd:graphite` individual, and the MSRE edge — a mixed bundle under one `ChangeProposal`
