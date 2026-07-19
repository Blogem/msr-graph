# instance-auto-accept Specification

## Purpose

Define how instance-kind candidates bypass the review gate: a new individual typed by an
existing class is written directly to `urn:msr:data` flagged `msr:autoAccepted`, while an
individual that depends on proposed schema instead rides its proposal's bundle and reaches
`urn:msr:data` only on approval.

## ADDED Requirements

### Requirement: Instances under an existing class are auto-accepted to core data
The miner SHALL write an `instance`-kind candidate whose type and edges resolve entirely
within the current core schema directly to `urn:msr:data` with a deterministic IRI, flagged
`msr:autoAccepted true`, with provenance kept (`msr:citedIn` the source document). Such a
candidate SHALL NOT create a `ChangeProposal` and SHALL NOT be written to `urn:msr:staging` or
a proposal graph — the schema is unchanged, so there is nothing to review.

#### Scenario: A new salt under MoltenSalt is written directly to data
- **WHEN** an `instance` candidate is a new specific salt/compound typed by the existing `msr:MoltenSalt` (or another existing) class
- **THEN** it is written to `urn:msr:data` flagged `msr:autoAccepted true` with provenance, and no `ChangeProposal` is created

### Requirement: Instances depending on proposed schema ride the proposal bundle
The miner SHALL NOT auto-accept an individual that can only be typed or related by proposed
schema (a class or property that is itself a pending proposal); instead it SHALL be written
into that proposal's `urn:msr:proposal/{id}` graph, so it reaches `urn:msr:data` only when
chunk 9 approves the bundle.

#### Scenario: graphite rides the Moderator proposal
- **WHEN** the `msrd:graphite` individual depends on the proposed `msr:Moderator` class
- **THEN** `msrd:graphite` and its `msr:moderatedBy` edge are written into the graphite proposal's `urn:msr:proposal/{id}` graph, and nothing is written to `urn:msr:data` for it during mining

### Requirement: Auto-accepted individuals are idempotent
Re-running the miner MUST leave the `urn:msr:data` auto-accepted-triple count unchanged,
because auto-accepted individuals have deterministic IRIs and no blank nodes.

#### Scenario: Re-run adds no duplicate auto-accepted instances
- **WHEN** the miner runs twice over the same corpus
- **THEN** the second run leaves the count of `msr:autoAccepted` triples in `urn:msr:data` identical to after the first
