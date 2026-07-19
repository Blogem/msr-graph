# document-graph Specification

## Purpose

Define writing one `msr:Document` node per curated document into `urn:msr:data` via additive SPARQL UPDATE, carrying manifest-sourced metadata, using deterministic report-number-keyed IRIs so that writes are idempotent and re-assertions are set-semantics no-ops.

## Requirements

### Requirement: Document nodes written to the data graph
The system SHALL write one `msr:Document` node per curated document into `urn:msr:data` via SPARQL UPDATE (`INSERT DATA` naming an explicit `GRAPH <urn:msr:data>` target) over the GraphDB HTTP endpoint. Each node MUST carry its report number (`dcterms:identifier`), title (`rdfs:label`), and date (`dcterms:date`) from the parsed manifest. Writing MUST be additive (it MUST NOT replace or clobber existing `urn:msr:data` triples such as the seed A-Box).

#### Scenario: Curated documents present in the graph
- **WHEN** the ingest completes against a seeded stack
- **THEN** the graph contains one `msr:Document` node per curated document (11 in the finalized curated set) with report number, title, and date metadata, queryable via the core-dataset client

#### Scenario: Existing data-graph triples preserved
- **WHEN** the Document nodes are written to `urn:msr:data`
- **THEN** the pre-existing seed A-Box triples in `urn:msr:data` remain present afterwards

### Requirement: Deterministic IRIs and idempotent writes
Document IRIs SHALL be deterministic and keyed by report number (`msrd:{report#}`), with no blank nodes, so that re-asserting the same document triples is a set-semantics no-op. Re-running the Document-node write MUST leave `urn:msr:data` triple counts unchanged.

#### Scenario: Re-running the write changes nothing
- **WHEN** the Document-node write runs twice consecutively
- **THEN** the `urn:msr:data` triple count after the second run equals the count after the first run

#### Scenario: Re-asserting a seed Document is a no-op
- **WHEN** the ingest writes `msrd:ORNL-TM-2316` (already typed `a msr:Document` in the seed A-Box, which deliberately carries no hand-authored label/identifier/date so the manifest is the single source of Document metadata)
- **THEN** no duplicate node is created and no conflicting or duplicate metadata triples arise — the node ends with exactly one `rdfs:label` (the manifest's), and a repeat ingest leaves `urn:msr:data` unchanged
