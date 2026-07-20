# core-dataset-access Specification

## Purpose

Define the `internal/graph` client contract that enforces core-dataset access: restricting core reads to the three core graphs, rejecting queries that carry their own dataset clauses, exposing an unrestricted read path, targeting explicit named graphs on writes, exporting graph IRIs as typed constants, and guarding integration tests by environment.

## Requirements

### Requirement: Core reads are restricted to the three core graphs
The `internal/graph` client's `Select(ctx, query)` SHALL evaluate every query against exactly the three core graphs (`urn:msr:ontology`, `urn:msr:data`, `urn:msr:vocab`) by sending them as **both** `default-graph-uri` **and** `named-graph-uri` SPARQL 1.1 Protocol parameters on every request. This client is the enforcement of the core-dataset contract — GraphDB has no store-side graph exclusion and its no-dataset default is union-of-all-graphs.

#### Scenario: Staging is invisible to core reads
- **WHEN** a triple is inserted into `urn:msr:staging` and the same pattern is queried via `Select`
- **THEN** the triple does not appear in the results

#### Scenario: The same triple is visible raw
- **WHEN** that staging triple is queried via `SelectRaw` (or any raw no-dataset query against the endpoint)
- **THEN** the triple appears — pinning that the exclusion lives in the client, not the store

#### Scenario: GRAPH patterns work within the core set
- **WHEN** a `Select` query uses `GRAPH ?g { … }` to locate a term known to live in `urn:msr:vocab`
- **THEN** the query returns the term with `?g` bound to `urn:msr:vocab` (the named-graph set equals the default set, so `GRAPH` patterns do not silently match nothing)

### Requirement: Queries carrying their own dataset clauses are rejected
`Select` MUST reject queries containing `FROM` or `FROM NAMED` clauses (case-insensitive token scan) with an error that names `SelectRaw` as the escape hatch for deliberately wider reads, rather than letting protocol parameters silently override the query's dataset.

#### Scenario: Smuggled FROM is a loud error
- **WHEN** `Select` is called with a query containing `FROM <urn:msr:staging>`
- **THEN** the call fails before reaching GraphDB, with an error message mentioning `SelectRaw`

#### Scenario: Case variations are caught
- **WHEN** `Select` is called with a query containing `from named <urn:msr:staging>` in lower case
- **THEN** the call is rejected the same way

### Requirement: Unrestricted read path
The client SHALL expose `SelectRaw(ctx, query)` which sends the query with no dataset restriction, for the review/staging surfaces and for tests that prove the core/raw difference.

#### Scenario: Raw read sees all graphs
- **WHEN** `SelectRaw` runs a query matching triples spread across core and staging graphs
- **THEN** results include matches from all graphs

### Requirement: Write paths target explicit named graphs
The client SHALL expose `Update(ctx, update)` for SPARQL UPDATE (writers name explicit `GRAPH` targets) and `PutGraph(ctx, graphIRI, turtle)` for Graph Store Protocol `PUT` with graph-replace semantics. `PutGraph` MUST refuse graph IRIs outside the known set exported by the package.

#### Scenario: PutGraph replaces the target graph
- **WHEN** `PutGraph` is called twice for the same graph IRI with different Turtle payloads
- **THEN** the graph contains exactly the second payload's triples afterwards

#### Scenario: Unknown graph IRI refused
- **WHEN** `PutGraph` is called with a graph IRI not in the exported constant set
- **THEN** the call fails without sending any request to GraphDB

### Requirement: Graph IRIs as typed constants
The package SHALL export the named-graph IRIs (`urn:msr:ontology`, `urn:msr:data`, `urn:msr:vocab`, `urn:msr:staging`) as typed constants so call sites never use string literals for graph names.

#### Scenario: Call sites use constants
- **WHEN** loader and test code reference named graphs
- **THEN** they reference the exported constants from `internal/graph`, not literal IRI strings

### Requirement: Provenance graph is a typed constant excluded from core reads
The graph package SHALL expose a typed constant `Provenance GraphIRI = "urn:msr:provenance"` for the append-only provenance/lineage graph. This graph SHALL NOT be a member of `CoreGraphs`, so core reads (`Select`) exclude it exactly as they exclude `urn:msr:staging`; per-run lineage is reachable only via an explicit `GRAPH <urn:msr:provenance>` clause or the unrestricted read path (`SelectRaw`). Because `urn:msr:provenance` is written via SPARQL `Update` with an explicit `GRAPH` target (not Graph Store `PUT`), it is deliberately absent from the `PutGraph` known-graph allowlist.

#### Scenario: Provenance graph is not in the core read set
- **WHEN** a core read (`Select`) evaluates a query for a fact's `prov:wasGeneratedBy`
- **THEN** only the single stable `msrd:activity-<pipeline>` edge in `urn:msr:data` is returned; the per-run lineage edges in `urn:msr:provenance` are not visible

#### Scenario: Provenance lineage is reachable via an explicit graph scope
- **WHEN** a query names `GRAPH <urn:msr:provenance>` (or uses the unrestricted `SelectRaw` path)
- **THEN** the per-run `prov:wasGeneratedBy` lineage edges are returned

### Requirement: Integration tests guarded by environment
Integration tests requiring a live GraphDB SHALL read `GRAPHDB_URL` (default `http://localhost:7200`) and check reachability once via a shared helper. With `GRAPHDB_REQUIRED` unset, an unreachable GraphDB (connection refused/timeout only) causes `t.Skip` with the reason; with `GRAPHDB_REQUIRED=1`, it causes `t.Fatal`. A GraphDB that responds but errors MUST fail the test in both modes. Pure-Go unit tests (dataset-clause rejection, request construction) MUST run unconditionally.

#### Scenario: Skip only on absence, never on breakage
- **WHEN** GraphDB responds with HTTP 500 during an integration test without `GRAPHDB_REQUIRED` set
- **THEN** the test fails rather than skips
