# review-ui Specification

## Purpose

Define the review surface of the frontend: a status-filtered proposal queue, a proposal detail
view that renders the change as a highlighted ontology-neighborhood diff with an evidence panel,
editable placement/unit fields, approve/edit/reject controls, and a raw-triples advanced view.
This capability consumes the chunk-9 `proposal-review-api` contract unchanged and holds no direct
store access.

## ADDED Requirements

### Requirement: Proposal queue filtered by review status
The review surface SHALL list change proposals from `GET /api/proposals`, showing at least each
proposal's id, kind, review status, term, and document frequency, and SHALL let the reviewer
filter the list by review status (`pending`/`approved`/`rejected`) via the `status` query
parameter.

#### Scenario: Pending queue is shown
- **WHEN** the reviewer opens the queue filtered to pending
- **THEN** the list requests `GET /api/proposals?status=pending` and shows only pending proposals

#### Scenario: Unfiltered queue shows all statuses
- **WHEN** the reviewer clears the status filter
- **THEN** the list requests `GET /api/proposals` and shows proposals of every status

### Requirement: Proposal detail rendered as an ontology-neighborhood diff
Selecting a proposal SHALL fetch `GET /api/proposals/{id}` and render its proposed triples
overlaid on the returned one-hop affected ontology neighborhood, highlighting the added nodes and
edges so the change reads as a visual diff.

#### Scenario: solubility proposal shows the new property as added
- **WHEN** the reviewer opens the `solubility` proposal
- **THEN** the diff highlights the new `solubility` property node against its neighborhood

#### Scenario: graphite bundle shows the new class and relation as added
- **WHEN** the reviewer opens the `graphite` proposal
- **THEN** the diff highlights the new `Moderator` class and the `moderatedBy` relation edge

#### Scenario: Unknown proposal id surfaces not-found
- **WHEN** the detail view requests a proposal id the API reports `404`
- **THEN** the UI shows a not-found state rather than an empty or broken diff

### Requirement: Evidence panel shows source spans and document links
The detail view SHALL present the proposal's evidence — sentence text, the `citedIn` document,
and the start/end offsets — in an evidence panel, with document references shown as links where
available.

#### Scenario: Evidence sentences and citations are shown
- **WHEN** a proposal detail is rendered
- **THEN** the evidence panel lists each evidence sentence with its document citation and offsets

### Requirement: Editable placement and unit fields drive the edit endpoint
The detail view SHALL allow the reviewer to edit the proposal's placement/unit fields and persist
the edit via `PUT /api/proposals/{id}/graph`. A successful edit SHALL update the rendered
proposal.

#### Scenario: Reviewer sets a proposal's unit
- **WHEN** the reviewer sets the `solubility` proposal's unit to mole fraction and saves
- **THEN** the client sends `PUT /api/proposals/{id}/graph` with the edited graph and the detail
  view reflects the change

### Requirement: Approve and reject controls
The detail view SHALL provide approve and reject controls calling
`POST /api/proposals/{id}/approve` and `POST /api/proposals/{id}/reject`. On approve success the
proposal SHALL be shown as approved; on reject it SHALL be shown as rejected.

#### Scenario: Approve promotes the proposal
- **WHEN** the reviewer approves a proposal and the API returns success
- **THEN** the proposal is shown as approved and removed from the pending queue

#### Scenario: Reject marks the proposal
- **WHEN** the reviewer rejects a proposal
- **THEN** the proposal is shown as rejected

### Requirement: SHACL validation errors surfaced legibly
The UI SHALL surface a typed SHACL validation error returned by an approve or edit as a legible
message and SHALL leave the proposal in its pending state when GraphDB rejects the write.

#### Scenario: Approve rejected on validation
- **WHEN** an approve returns a typed SHACL validation error
- **THEN** the UI shows the validation violation message and the proposal remains pending

### Requirement: Raw-triples advanced view
The detail view SHALL offer an advanced view exposing the proposal's unrendered triples for a
reviewer who wants to inspect the raw graph rather than the rendered diff.

#### Scenario: Reviewer opens the raw view
- **WHEN** the reviewer switches to the advanced raw-triples view
- **THEN** the proposal's raw triples are displayed
