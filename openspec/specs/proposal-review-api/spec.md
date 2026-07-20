# proposal-review-api Specification

## Purpose

Define the stateless HTTP JSON API the review UI (chunk 10) consumes to serve the change-
proposal queue, render a proposal as a diff, edit it, and dispose of it. This capability owns
the API surface — routes, methods, request/response shapes, and error contract — and the
guarantee that every read goes through the staging-inclusive path, never the core-dataset
contract. The disposition *semantics* triggered by the approve/reject/edit endpoints are owned
by `proposal-lifecycle` and `approval-typed-routing`.

## Requirements

### Requirement: Proposal routes registered on the server
The server SHALL register the proposal routes on its HTTP mux alongside the existing
`/api/chat` and `/healthz` routes, without changing them: `GET /api/proposals`,
`GET /api/proposals/{id}`, `PUT /api/proposals/{id}/graph`, `POST /api/proposals/{id}/approve`,
and `POST /api/proposals/{id}/reject`. Each route SHALL reject a request whose HTTP method is
not the one it defines with `405 Method Not Allowed`.

#### Scenario: Wrong method is rejected
- **WHEN** a client sends `DELETE /api/proposals/{id}`
- **THEN** the server responds `405 Method Not Allowed` and does not mutate any graph

#### Scenario: Chat and health routes are unaffected
- **WHEN** the proposal routes are registered
- **THEN** `POST /api/chat` and `GET /healthz` continue to behave as before

### Requirement: Queue endpoint lists proposals filtered by review status
`GET /api/proposals` SHALL return the `msr:ChangeProposal` resources read from
`urn:msr:staging` as a JSON list, each carrying at least its id, kind, review status, term, and
document frequency. When a `status` query parameter is supplied (`pending`/`approved`/
`rejected`), the response SHALL contain only proposals with that review status; absent the
parameter, all proposals SHALL be returned.

#### Scenario: Filter to the pending queue
- **WHEN** a client requests `GET /api/proposals?status=pending`
- **THEN** the response lists only proposals whose `msr:reviewStatus` is `pending`

#### Scenario: Unfiltered list returns every proposal
- **WHEN** a client requests `GET /api/proposals` with no `status`
- **THEN** the response lists proposals of every review status

### Requirement: Detail endpoint returns triples, evidence, and affected neighborhood
`GET /api/proposals/{id}` SHALL return, for the identified proposal, its proposed triples read
from its `urn:msr:proposal/{id}` graph, its evidence (the resource's `msr:hasEvidence`
`msr:Evidence` nodes — sentence text, the reused `msr:citedIn` document, and
`msr:startOffset`/`msr:endOffset`), and a bounded one-hop **affected ontology neighborhood** —
core-graph triples about the IRIs the proposal references — so the client can render a focused
diff. The `{id}` path segment SHALL be the deterministic `{kind}-{term-slug}` (e.g.
`property-solubility`) that chunk 8 uses for the `urn:msr:proposal/{id}` graph and the
`msrd:proposal-{id}` resource. An unknown id SHALL return `404 Not Found`.

#### Scenario: Detail renders a diff-ready payload
- **WHEN** a client requests `GET /api/proposals/{id}` for an existing proposal
- **THEN** the response contains the proposal graph's triples, the evidence sentences with document citations and offsets, and the one-hop ontology neighborhood of the referenced IRIs

#### Scenario: Unknown proposal id
- **WHEN** a client requests `GET /api/proposals/{id}` for an id that has no `msr:ChangeProposal`
- **THEN** the server responds `404 Not Found`

### Requirement: Reads use the staging-inclusive path only
Every proposal read SHALL be issued through the graph client's raw (staging-inclusive) path or
an explicit `GRAPH` scope, never the core-dataset `Select`. The API SHALL NOT expose any
proposal content through a core-dataset read, keeping pending proposals invisible to the
analysis agent's dataset while visible to reviewers.

#### Scenario: Proposals are read outside the core contract
- **WHEN** the queue or detail endpoint reads staging/proposal graphs
- **THEN** it uses the staging-inclusive read path and a core-dataset `Select` still returns none of the proposal content

### Requirement: Stateless JSON API with a typed error contract
The API SHALL be stateless (no server-side session; each request self-contained) and speak
JSON. A malformed request body SHALL return `400 Bad Request`; an approve or edit that GraphDB
rejects on SHACL validation SHALL return a `4xx`/`5xx` error whose body conveys the typed
validation violation rather than a raw stack trace. The chat request path's read-only SQLite
guarantee SHALL NOT be weakened by these routes.

#### Scenario: Malformed edit body
- **WHEN** a client sends `PUT /api/proposals/{id}/graph` with a body that is not valid triples/JSON
- **THEN** the server responds `400 Bad Request` and the proposal graph is unchanged

#### Scenario: SHACL rejection surfaces as a typed error
- **WHEN** an approve promotes triples GraphDB rejects on SHACL validation
- **THEN** the response conveys the typed validation violation and the proposal stays `pending`

### Requirement: Handlers are testable against a fake graph client
The proposal handlers SHALL depend on a narrow interface (the subset of graph operations they
use) so they can be unit-tested against a fake graph client with no live GraphDB, consistent
with how the agent tools are tested.

#### Scenario: Handler unit test with a fake client
- **WHEN** the queue handler is exercised with a fake graph client returning canned staging results
- **THEN** the test asserts the JSON response without any network call to GraphDB
