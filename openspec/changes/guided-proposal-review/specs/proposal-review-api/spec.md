## ADDED Requirements

### Requirement: Ontology class list endpoint
`GET /api/ontology/classes` SHALL return the ontology's classes as a JSON list, each with at least its IRI and a human-readable label, so the review UI can populate a parent-class picker. The list SHALL be read from the core graphs via the staging-inclusive read path and SHALL be bounded/labeled (not raw unbounded triples).

#### Scenario: Class list is returned for the picker
- **WHEN** a client requests `GET /api/ontology/classes`
- **THEN** the response is a JSON list of `{iri, label}` for the ontology's classes

### Requirement: Unit allowlist endpoint
`GET /api/units` SHALL return the vendored QUDT unit allowlist (`ontology/qudt-units.json`) as a JSON list of allowed unit IRIs (with labels where available), so the review UI can populate a unit picker constrained to allowlisted units. The endpoint SHALL be the single served source of the allowlist so the UI cannot drift from the SHACL-enforced set.

#### Scenario: Allowlisted units are returned for the picker
- **WHEN** a client requests `GET /api/units`
- **THEN** the response lists the allowlisted QUDT unit IRIs the reviewer may choose from

### Requirement: Approval preview endpoint
`GET /api/proposals/{id}/preview` SHALL return a dry-run of what approving the proposal would do: the count of proposed triples routed to each core graph (`urn:msr:vocab`/`urn:msr:ontology`/`urn:msr:data`) and the resulting ontology version. It SHALL compute this by reusing the same `internal/proposal` routing logic the approve path uses — never a re-derived copy — and SHALL NOT mutate any graph. An unknown id SHALL return `404 Not Found`.

#### Scenario: Preview reports routing and version delta
- **WHEN** a client requests `GET /api/proposals/{id}/preview` for an existing proposal
- **THEN** the response reports how many triples would land in each core graph and the resulting ontology version, and no graph is mutated

#### Scenario: Preview matches approval routing
- **WHEN** the previewed proposal is subsequently approved
- **THEN** the triples land in the graphs the preview reported (the preview and approve share one routing implementation)

## MODIFIED Requirements

### Requirement: Proposal routes registered on the server
The server SHALL register the proposal routes on its HTTP mux alongside the existing
`/api/chat` and `/healthz` routes, without changing them: `GET /api/proposals`,
`GET /api/proposals/{id}`, `GET /api/proposals/{id}/preview`, `PUT /api/proposals/{id}/graph`,
`POST /api/proposals/{id}/approve`, `POST /api/proposals/{id}/reject`, and the review read
endpoints `GET /api/ontology/classes` and `GET /api/units`. Each route SHALL reject a request
whose HTTP method is not the one it defines with `405 Method Not Allowed`.

#### Scenario: Wrong method is rejected
- **WHEN** a client sends `DELETE /api/proposals/{id}`
- **THEN** the server responds `405 Method Not Allowed` and does not mutate any graph

#### Scenario: Chat and health routes are unaffected
- **WHEN** the proposal routes are registered
- **THEN** `POST /api/chat` and `GET /healthz` continue to behave as before

#### Scenario: New review read routes are registered
- **WHEN** a client requests `GET /api/ontology/classes`, `GET /api/units`, or `GET /api/proposals/{id}/preview`
- **THEN** each is served by its handler, and a non-`GET` method to any of them returns `405 Method Not Allowed`

### Requirement: Detail endpoint returns triples, evidence, and affected neighborhood
`GET /api/proposals/{id}` SHALL return, for the identified proposal, its proposed triples read
from its `urn:msr:proposal/{id}` graph, its evidence (the resource's `msr:hasEvidence`
`msr:Evidence` nodes — sentence text, the reused `msr:citedIn` document, and
`msr:startOffset`/`msr:endOffset`), and a bounded one-hop **affected ontology neighborhood** —
core-graph triples about the IRIs the proposal references — so the client can render a focused
diff. The response SHALL additionally include: a **derived kind** label computed from the
proposal's `rdf:type`/predicate triples (e.g. "datatype property", "class", "object property")
describing what will actually be added, distinct from the display `msr:kind`; the proposal's
**suggested-vs-asserted** placement/unit values with their **confidence**; any **witness
instances** the proposal references (for a promotion); and the proposal's **decision state**
(`confirm` vs `needs-decision`). The `{id}` path segment SHALL be the deterministic
`{kind}-{term-slug}` (e.g. `property-solubility`). An unknown id SHALL return `404 Not Found`.

#### Scenario: Detail renders a diff-ready payload
- **WHEN** a client requests `GET /api/proposals/{id}` for an existing proposal
- **THEN** the response contains the proposal graph's triples, the evidence sentences with document citations and offsets, and the one-hop ontology neighborhood of the referenced IRIs

#### Scenario: Detail reports derived kind and decision state
- **WHEN** a client requests `GET /api/proposals/{id}` for a proposal whose triples declare a datatype property with a low-confidence suggested unit
- **THEN** the response reports the derived kind ("datatype property"), the suggested unit with its confidence distinct from any asserted unit, and a `needs-decision` state

#### Scenario: Unknown proposal id
- **WHEN** a client requests `GET /api/proposals/{id}` for an id that has no `msr:ChangeProposal`
- **THEN** the server responds `404 Not Found`
