## MODIFIED Requirements

### Requirement: Queue endpoint lists proposals filtered by review status
`GET /api/proposals` SHALL return the `msr:ChangeProposal` resources read from `urn:msr:staging` as a JSON list with **exactly one entry per proposal id**, each carrying at least its id, kind, review status, term, and a cross-corpus support summary derived at read time from the proposal's observations: `documentFrequency`, `totalOccurrences`, `corpusCount`, and `corpora` (the list of corpora). The query SHALL aggregate observations (e.g. `GROUP BY` the proposal with `SAMPLE`/`MAX` for scalar columns) so a proposal with observations across multiple documents, corpora, or mining runs never produces more than one row. When a `status` query parameter is supplied (`pending`/`approved`/`rejected`), the response SHALL contain only proposals with that review status; absent the parameter, all proposals SHALL be returned.

#### Scenario: Filter to the pending queue
- **WHEN** a client requests `GET /api/proposals?status=pending`
- **THEN** the response lists only proposals whose `msr:reviewStatus` is `pending`

#### Scenario: Unfiltered list returns every proposal
- **WHEN** a client requests `GET /api/proposals` with no `status`
- **THEN** the response lists proposals of every review status

#### Scenario: One row per proposal despite multi-corpus/multi-run observations
- **WHEN** a proposal has observations in two corpora (and/or from multiple mining runs)
- **THEN** the queue returns exactly one entry for that proposal id, whose summary reports `corpusCount` 2 and a `corpora` list of both — not one row per observation value

### Requirement: Detail endpoint returns triples, evidence, and affected neighborhood
`GET /api/proposals/{id}` SHALL return, for the identified proposal, its proposed triples read from its `urn:msr:proposal/{id}` graph, its evidence (the resource's `msr:hasEvidence` `msr:Evidence` nodes — sentence text, the reused `msr:citedIn` document, and `msr:startOffset`/`msr:endOffset`), its **observation breakdown** grouped by corpus and document (per document: the document, its corpus, the latest `occurrenceCount`, and the first/last observed times), and a bounded one-hop **affected ontology neighborhood** — core-graph triples about the IRIs the proposal references — so the client can render a focused diff. The `{id}` path segment SHALL be the deterministic `{kind}-{term-slug}` (e.g. `property-solubility`) that chunk 8 uses for the `urn:msr:proposal/{id}` graph and the `msrd:proposal-{id}` resource. An unknown id SHALL return `404 Not Found`.

#### Scenario: Detail renders a diff-ready payload
- **WHEN** a client requests `GET /api/proposals/{id}` for an existing proposal
- **THEN** the response contains the proposal graph's triples, the evidence sentences with document citations and offsets, the observation breakdown grouped by corpus/document, and the one-hop ontology neighborhood of the referenced IRIs

#### Scenario: Observation breakdown exposes per-corpus provenance
- **WHEN** a proposal has observations in the chemistry and safety corpora
- **THEN** the detail response groups the observations by corpus and lists, per document, the latest occurrence count and observed times

#### Scenario: Unknown proposal id
- **WHEN** a client requests `GET /api/proposals/{id}` for an id that has no `msr:ChangeProposal`
- **THEN** the server responds `404 Not Found`
