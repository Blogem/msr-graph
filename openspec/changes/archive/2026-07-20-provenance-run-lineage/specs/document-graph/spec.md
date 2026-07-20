# document-graph (delta)

## MODIFIED Requirements

### Requirement: Document nodes carry generation provenance
Each written `msr:Document` node SHALL carry `prov:wasGeneratedBy` the deterministic **stable** ingest/extraction-`Activity` IRI (`msrd:activity-extraction`) in `urn:msr:data`, tying the document node to the pipeline that ingested it, in addition to its manifest-sourced metadata. The generation edge SHALL be deterministic so re-asserting a document remains a set-semantics no-op (the `urn:msr:data` triple count is unchanged on re-run). The ingest run SHALL additionally write, into `urn:msr:provenance`, one `<document> prov:wasGeneratedBy <urn:msr:run:extraction/<ts>>` per-run generation edge referencing the run's per-run `Activity` node (see mention-graph-writing / provenance-model for the per-run activity record). No `urn:msr:run:*` named graph is created.

#### Scenario: Document node references the stable activity and the per-run activity
- **WHEN** the ingest writes a `msr:Document` node into `urn:msr:data`
- **THEN** the node carries `prov:wasGeneratedBy msrd:activity-extraction` in `urn:msr:data` alongside its report number, title, and date, and `urn:msr:provenance` carries `<document> prov:wasGeneratedBy <urn:msr:run:extraction/<ts>>`

#### Scenario: Generation edge preserves idempotency
- **WHEN** the Document-node write runs twice consecutively
- **THEN** the `urn:msr:data` triple count after the second run equals the count after the first, because the document IRI and the referenced `msrd:activity-extraction` IRI are deterministic; `urn:msr:provenance` gains a second per-run generation edge for the document
