# review-ui Specification

## Purpose

Define the review surface of the frontend: a status-filtered proposal queue, a proposal detail
view that renders the change as a highlighted ontology-neighborhood diff with an evidence panel,
editable placement/unit fields, approve/edit/reject controls, and a raw-triples advanced view.
This capability consumes the chunk-9 `proposal-review-api` contract unchanged and holds no direct
store access.

## Requirements

### Requirement: Proposal queue filtered by review status
The review surface SHALL list change proposals from `GET /api/proposals`, showing at least each proposal's id, kind, review status, term, and its cross-corpus support summary (`documentFrequency`, `totalOccurrences`, and a cross-corpus indicator derived from `corpusCount`/`corpora`), and SHALL let the reviewer filter the list by review status (`pending`/`approved`/`rejected`) via the `status` query parameter. The queue SHALL render exactly one row per proposal id (the API returns one entry per proposal) and MUST NOT break when a proposal is attested across multiple corpora or mining runs.

#### Scenario: Pending queue is shown
- **WHEN** the reviewer opens the queue filtered to pending
- **THEN** the list requests `GET /api/proposals?status=pending` and shows only pending proposals

#### Scenario: Unfiltered queue shows all statuses
- **WHEN** the reviewer clears the status filter
- **THEN** the list requests `GET /api/proposals` and shows proposals of every status

#### Scenario: Cross-corpus proposals render without duplicate rows
- **WHEN** a proposal is attested in more than one corpus
- **THEN** the queue shows a single row for it with a cross-corpus indicator, and the keyed list does not error on a duplicate id

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
The detail view SHALL present the proposal's evidence — sentence text, the `citedIn` document, and the start/end offsets — in an evidence panel, with document references shown as links where available, AND SHALL present the proposal's observation breakdown grouped by corpus and document (per document: the document link, its corpus, the latest occurrence count, and when it was observed) so the reviewer can see how broadly and how often the candidate is attested.

#### Scenario: Evidence sentences and citations are shown
- **WHEN** a proposal detail is rendered
- **THEN** the evidence panel lists each evidence sentence with its document citation and offsets

#### Scenario: Observation breakdown is shown grouped by corpus
- **WHEN** a proposal detail is rendered for a candidate observed across corpora
- **THEN** the detail view groups the observations by corpus and lists, per document, the latest occurrence count and observed time

### Requirement: Editable placement and unit fields drive the edit endpoint
The detail view SHALL allow the reviewer to edit the proposal's placement/unit fields and persist
the edit via `PUT /api/proposals/{id}/graph`. The edit endpoint **replaces the whole proposal
graph**, so the client SHALL send the full edited graph serialized in the request body's
`triples` field (`{"triples": "<serialized triples>"}`), never a partial patch. A successful edit
SHALL update the rendered proposal.

#### Scenario: Reviewer sets a proposal's unit
- **WHEN** the reviewer sets the `solubility` proposal's unit to mole fraction and saves
- **THEN** the client sends `PUT /api/proposals/{id}/graph` with the full edited graph as the
  `triples` string and the detail view reflects the change

#### Scenario: Empty edit body is not sent
- **WHEN** the reviewer's edit would produce no triples
- **THEN** the client does not send an empty `triples` body (which the API rejects `400`), and the
  proposal graph is left unchanged

### Requirement: Approve and reject controls
The detail view SHALL provide approve and reject controls calling
`POST /api/proposals/{id}/approve` and `POST /api/proposals/{id}/reject`. The approve request
SHALL carry a JSON body identifying the decision (`{reviewer, timestamp}`), since the API rejects
an empty approve body `400`; the reject request needs no body. On approve success the proposal
SHALL be shown as approved; on reject it SHALL be shown as rejected.

#### Scenario: Approve promotes the proposal
- **WHEN** the reviewer approves a proposal and the API returns success
- **THEN** the client sends `POST /api/proposals/{id}/approve` with a `{reviewer, timestamp}` body
  and the proposal is shown as approved and removed from the pending queue

#### Scenario: Reject marks the proposal
- **WHEN** the reviewer rejects a proposal
- **THEN** the proposal is shown as rejected

### Requirement: SHACL validation errors surfaced legibly
The UI SHALL surface a typed SHACL validation error returned by an approve or edit as a legible
message and SHALL leave the proposal in its pending state when GraphDB rejects the write. The
error is delivered as an HTTP `422` with a typed JSON body `{error, message, violations}`, where
each violation carries `focusNode`, `constraint`, `shape`, `path`, and `message`; the UI SHALL
render the violation detail rather than a raw status or stack trace.

#### Scenario: Approve rejected on validation
- **WHEN** an approve returns a `422` with a `violations` array
- **THEN** the UI shows the per-violation detail (path/constraint/message) and the proposal
  remains pending

### Requirement: Raw-triples advanced view
The detail view SHALL offer an advanced view exposing the proposal's unrendered triples for a
reviewer who wants to inspect the raw graph rather than the rendered diff.

#### Scenario: Reviewer opens the raw view
- **WHEN** the reviewer switches to the advanced raw-triples view
- **THEN** the proposal's raw triples are displayed

### Requirement: Proposal-queue row presents a legible information hierarchy
Each proposal-queue row SHALL present its fields in a legible hierarchy rather than as an undifferentiated line of values: the mined **term** SHALL be the visually dominant element; `kind` and `status` SHALL be shown as labeled/styled indicators (e.g. pills) so their meaning is clear without external context; the document frequency SHALL be humanized (e.g. "seen in N document(s)", with correct singular/plural) rather than shown as a bare number; and the proposal `id` (URN) SHALL be visually de-emphasized. All five fields (id, kind, status, term, document frequency) SHALL remain present in the row.

#### Scenario: Term is the headline of the row
- **WHEN** the queue renders a proposal for the term `solubility`
- **THEN** `solubility` is the visually dominant element of the row, with `kind` and `status` shown as distinct labeled indicators and the URN id de-emphasized

#### Scenario: Document frequency is humanized
- **WHEN** a proposal has a document frequency of 1 and another has 47
- **THEN** the rows read as "seen in 1 document" and "seen in 47 documents" respectively rather than as bare numbers

### Requirement: Review surfaces render identifiers overflow-safe
The review surfaces — the proposal queue, the ontology-neighborhood diff, the evidence panel, and the raw-triples view — SHALL render IRIs, URNs, and unit codes so that a long value is contained within its box and does not force horizontal overflow of the row, panel, or page.

#### Scenario: Long identifier in the diff does not overflow
- **WHEN** the diff or evidence panel renders a long IRI (e.g. a full QUDT unit or ontology term URI)
- **THEN** the identifier wraps/contains within its element and the panel does not scroll horizontally or push the page wider

### Requirement: Proposal queue is keyboard-navigable
The reviewer SHALL be able to move through the proposal queue and act on the selected proposal using the keyboard: keys to move selection to the previous/next proposal and keys to approve/reject the selected proposal, so the queue can be processed without a pointer.

#### Scenario: Keyboard moves selection through the queue
- **WHEN** the reviewer presses the next/previous keys with the queue focused
- **THEN** the selected proposal moves to the next/previous row and its detail is shown

#### Scenario: Keyboard triggers approve/reject
- **WHEN** the reviewer presses the approve (or reject) key with a proposal selected
- **THEN** the same action fires as the corresponding button, including its confirmation/validation behavior

### Requirement: Approve and reject outcomes surface as toast feedback
The result of an approve or reject action SHALL be surfaced to the reviewer as a non-blocking toast notification (success or failure), in addition to updating the proposal's rendered status, so the outcome of the action is unambiguous. This does not change how SHACL `422` validation detail is rendered.

#### Scenario: Successful approve shows a confirmation toast
- **WHEN** the reviewer approves a proposal and the API returns success
- **THEN** a toast confirms the approval and the proposal is shown as approved

#### Scenario: Failed action shows a failure toast
- **WHEN** an approve or reject request fails (non-validation error)
- **THEN** a toast reports the failure and the proposal remains in its prior state
