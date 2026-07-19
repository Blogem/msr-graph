# mention-graph-writing Specification

## Purpose
TBD - created by archiving change ner-entity-linking. Update Purpose after archive.
## Requirements
### Requirement: Minimal mention vocabulary in the seed ontology
The change SHALL add a self-contained mention vocabulary to `ontology/msr.ttl` (loaded into `urn:msr:ontology` by the existing `make load-seed` graph-replace `PUT`): an `msr:Mention` class and the predicates needed to describe a linked span — a link-to-target object property, an in-document object property (range `msr:Document`), a surface-form string, and integer start/end offset properties. This is pipeline-infrastructure schema loaded up front, not a reviewable evolution candidate, so it does not pass through staging.

#### Scenario: Mention TBox loaded with the seed
- **WHEN** `make load-seed` runs after the mention vocabulary is added to `ontology/msr.ttl`
- **THEN** `urn:msr:ontology` contains the `msr:Mention` class and its predicates

### Requirement: Deterministic mention IRIs, no blank nodes
Each linked mention SHALL be written as an `msr:Mention` individual with a deterministic IRI `msrd:mention-{report#}-{start}-{end}` (offsets into the chunk-5 `normalized.txt`), carrying its target link, its document, its surface form, and its start/end offsets, with no blank nodes.

#### Scenario: A linked span mints the expected triples
- **WHEN** a span linking `LiF-BeF2` at offsets `[s,e]` in report `R` is written
- **THEN** the graph gains `msrd:mention-R-s-e a msr:Mention` linked to the target salt individual, its document, surface form, and offsets — with no blank nodes

### Requirement: Additive write to urn:msr:data, idempotent across re-runs
Mention triples SHALL be written to `urn:msr:data` via additive SPARQL `INSERT DATA { GRAPH <urn:msr:data> { … } }` over the GraphDB HTTP endpoint (reusing the chunk-5 Python SPARQL-UPDATE helper), never a graph-replace `PUT`. Because IRIs are deterministic and there are no blank nodes, re-running the pipeline MUST leave the `urn:msr:data` mention-triple count unchanged.

#### Scenario: Re-run adds no duplicate mentions
- **WHEN** the linking pipeline runs twice over the same corpus
- **THEN** the second run leaves the `urn:msr:data` mention-triple count identical to after the first

#### Scenario: Shared graph preserved
- **WHEN** mention triples are inserted into `urn:msr:data`
- **THEN** the existing seed A-Box, chunk-2 catalog, and chunk-5 `Document` triples in that graph are preserved (additive insert, not replace)

