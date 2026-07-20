# document-graph (delta)

## ADDED Requirements

### Requirement: Document nodes carry generation provenance
Each written `msr:Document` node SHALL carry `prov:wasGeneratedBy` the deterministic ingest/extraction-`Activity` IRI (`msrd:activity-extraction`), tying the document node to the run that ingested it, in addition to its manifest-sourced metadata. The generation edge SHALL be deterministic so re-asserting a document remains a set-semantics no-op (the `urn:msr:data` triple count is unchanged on re-run); the timestamped `Activity` record lives in `urn:msr:run:extraction/<ts>`.

#### Scenario: Document node references the ingest activity
- **WHEN** the ingest writes a `msr:Document` node into `urn:msr:data`
- **THEN** the node carries `prov:wasGeneratedBy msrd:activity-extraction` alongside its report number, title, and date

#### Scenario: Generation edge preserves idempotency
- **WHEN** the Document-node write runs twice consecutively
- **THEN** the `urn:msr:data` triple count after the second run equals the count after the first, because the document IRI and the referenced `msrd:activity-extraction` IRI are deterministic
