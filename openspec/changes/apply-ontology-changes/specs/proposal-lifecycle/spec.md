# proposal-lifecycle Specification

## Purpose

Define the review-status state machine chunk 8 defers to chunk 9: how a `pending` proposal
transitions to `approved` or `rejected`, how an edit mutates the proposal graph, and the two
side effects that accompany approval — the ontology version bump (the no-push-signal mechanism
that makes an approved concept answerable) and the decision provenance record. The physical
routing of triples on approval is owned by `approval-typed-routing`; this capability owns the
status transitions, the version bump, the decision record, and the transition guards.

## ADDED Requirements

### Requirement: Approve transitions a pending proposal to approved
Approving a `pending` proposal SHALL set its `msr:reviewStatus` to `approved` (in
`urn:msr:staging`) as part of the same atomic operation that routes its triples and bumps the
version. The status flip SHALL be observable via the review API afterward.

#### Scenario: Approval flips status to approved
- **WHEN** a `pending` proposal is approved
- **THEN** its `msr:reviewStatus` is `approved`

### Requirement: Approval minor-bumps the ontology version
On a genuine `pending → approved` transition the engine SHALL minor-bump `owl:versionInfo` on
the `owl:Ontology` header inside `urn:msr:ontology` — parsing `major.minor.patch` (dropping any
pre-release suffix such as `-seed`), incrementing the minor, and resetting the patch (e.g.
`0.4.0 → 0.5.0`) — via a scoped DELETE/INSERT that replaces exactly the one version literal.
This bump is the only signal downstream consumers need: the analysis agent rebuilds its cached
KG-schema prompt on its next request when its per-request version check sees the change, and
batch jobs read the new version at their next run start.

#### Scenario: Version minor-bumps on approval
- **WHEN** a proposal is approved while `owl:versionInfo` is `0.4.0`
- **THEN** `urn:msr:ontology` afterward carries `owl:versionInfo` `0.5.0` and exactly one version literal

#### Scenario: The bump is not repeated on re-approval
- **WHEN** an already-`approved` proposal is approved again
- **THEN** the ontology version is unchanged (no second bump)

### Requirement: Approval records a decision provenance activity in staging
Every approval SHALL append a `prov:Activity` decision record (deterministic IRI
`urn:msr:run:approve/{id}`) to `urn:msr:staging`, `prov:wasAssociatedWith` a reviewer
`prov:Agent`, carrying a request-supplied `prov:startedAtTime` timestamp and a link to the
approved `msr:ChangeProposal`. It SHALL reuse the existing PROV-O vocabulary (no new TBox) and
SHALL be written to `urn:msr:staging`, not `urn:msr:provenance`, keeping the governance audit
trail out of the analysis dataset.

#### Scenario: Approval writes a reviewer-attributed activity
- **WHEN** a proposal is approved with a supplied reviewer and timestamp
- **THEN** `urn:msr:staging` contains a `prov:Activity` for that approval, `prov:wasAssociatedWith` the reviewer agent and linked to the proposal, and `urn:msr:provenance` gains nothing

### Requirement: Reject transitions to rejected without touching core or version
Rejecting a `pending` proposal SHALL set its `msr:reviewStatus` to `rejected` and SHALL NOT
copy any triple into a core graph, SHALL NOT bump `owl:versionInfo`, and SHALL leave the
proposal graph in place. The rejected proposal's triples remain only in staging.

#### Scenario: Reject leaves core and version untouched
- **WHEN** a `pending` proposal is rejected
- **THEN** its `msr:reviewStatus` is `rejected`, no triples were added to any core graph, and `owl:versionInfo` is unchanged

### Requirement: Edit replaces the proposal graph's triples
`PUT /api/proposals/{id}/graph` SHALL replace the triples in the proposal's
`urn:msr:proposal/{id}` graph with the supplied triples, leaving the `msr:ChangeProposal`
resource's status `pending`. A subsequent detail read and a subsequent approval SHALL operate on
the edited triples.

#### Scenario: Edited triples are what get promoted
- **WHEN** a reviewer edits a proposal's graph and then approves it
- **THEN** the promoted core triples reflect the edited proposal graph, not the pre-edit triples

### Requirement: Invalid status transitions are refused
The engine SHALL refuse a transition that is not valid for the proposal's current status —
approving or rejecting a proposal that is not `pending` is not a normal transition and SHALL be
either a safe idempotent no-op (for a repeated identical decision) or refused, never a partial
mutation. It SHALL NOT, for example, bump the version for a proposal that is already `approved`
(covered above) or flip an `approved` proposal to `rejected`.

#### Scenario: Rejecting an approved proposal is refused
- **WHEN** a client attempts to reject a proposal whose status is `approved`
- **THEN** the request is refused and the proposal remains `approved` with no core-graph change
