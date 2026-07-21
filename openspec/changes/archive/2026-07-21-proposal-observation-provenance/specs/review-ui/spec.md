## MODIFIED Requirements

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

### Requirement: Evidence panel shows source spans and document links
The detail view SHALL present the proposal's evidence — sentence text, the `citedIn` document, and the start/end offsets — in an evidence panel, with document references shown as links where available, AND SHALL present the proposal's observation breakdown grouped by corpus and document (per document: the document link, its corpus, the latest occurrence count, and when it was observed) so the reviewer can see how broadly and how often the candidate is attested.

#### Scenario: Evidence sentences and citations are shown
- **WHEN** a proposal detail is rendered
- **THEN** the evidence panel lists each evidence sentence with its document citation and offsets

#### Scenario: Observation breakdown is shown grouped by corpus
- **WHEN** a proposal detail is rendered for a candidate observed across corpora
- **THEN** the detail view groups the observations by corpus and lists, per document, the latest occurrence count and observed time
