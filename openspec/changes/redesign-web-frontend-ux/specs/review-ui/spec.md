## ADDED Requirements

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
