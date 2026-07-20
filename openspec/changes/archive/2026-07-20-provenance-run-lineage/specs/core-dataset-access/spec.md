# core-dataset-access (delta)

## ADDED Requirements

### Requirement: Provenance graph is a typed constant excluded from core reads
The graph package SHALL expose a typed constant `Provenance GraphIRI = "urn:msr:provenance"` for the append-only provenance/lineage graph. This graph SHALL NOT be a member of `CoreGraphs`, so core reads (`Select`) exclude it exactly as they exclude `urn:msr:staging`; per-run lineage is reachable only via an explicit `GRAPH <urn:msr:provenance>` clause or the unrestricted read path (`SelectRaw`). Because `urn:msr:provenance` is written via SPARQL `Update` with an explicit `GRAPH` target (not Graph Store `PUT`), it is deliberately absent from the `PutGraph` known-graph allowlist.

#### Scenario: Provenance graph is not in the core read set
- **WHEN** a core read (`Select`) evaluates a query for a fact's `prov:wasGeneratedBy`
- **THEN** only the single stable `msrd:activity-<pipeline>` edge in `urn:msr:data` is returned; the per-run lineage edges in `urn:msr:provenance` are not visible

#### Scenario: Provenance lineage is reachable via an explicit graph scope
- **WHEN** a query names `GRAPH <urn:msr:provenance>` (or uses the unrestricted `SelectRaw` path)
- **THEN** the per-run `prov:wasGeneratedBy` lineage edges are returned
