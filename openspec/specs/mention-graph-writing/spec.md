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
Mention triples SHALL be written to `urn:msr:data` via additive SPARQL `INSERT DATA { GRAPH <urn:msr:data> { … } }` over the GraphDB HTTP endpoint (reusing the chunk-5 Python SPARQL-UPDATE helper), never a graph-replace `PUT`. Because mention IRIs are deterministic, there are no blank nodes, and each mention's `prov:wasGeneratedBy` references a **deterministic** extraction-`Activity` IRI, re-running the pipeline MUST leave the `urn:msr:data` mention-triple count unchanged. The per-run **audit** record — the timestamped per-run `prov:Activity` node `urn:msr:run:extraction/<ts>` and its per-mention `prov:wasGeneratedBy` generation edges, all in the single `urn:msr:provenance` graph (see the generation-provenance requirement) — is explicitly outside this `urn:msr:data` idempotency guarantee: each wall-clock run appends a new per-run activity and its generation edges to the append-only `urn:msr:provenance` graph.

#### Scenario: Re-run adds no duplicate mentions
- **WHEN** the linking pipeline runs twice over the same corpus
- **THEN** the second run leaves the `urn:msr:data` mention-triple count identical to after the first

#### Scenario: Shared graph preserved
- **WHEN** mention triples are inserted into `urn:msr:data`
- **THEN** the existing real-data-writer triples in that graph — the loader's catalog salts/measurements/`Dataset` node and the chunk-5 `Document` triples — are preserved (additive insert, not replace). There is no seed A-Box (removed by the prerequisite `ground-demo-in-real-docs`).

### Requirement: Mentions carry generation provenance
Each written `msr:Mention` SHALL carry `prov:wasGeneratedBy` the deterministic **stable** extraction-`Activity` IRI (`msrd:activity-extraction`) in `urn:msr:data`, in addition to its existing `msr:inDocument` (its `prov:wasDerivedFrom` source `Document`). The extraction run SHALL write, into `urn:msr:provenance`, a **per-run** `Activity` node `<urn:msr:run:extraction/<ts>>` (typed `a prov:Activity`, attributed `prov:wasAssociatedWith agent:extraction@<version>`, with `prov:startedAtTime`/`prov:endedAtTime` and the ontology `owl:versionInfo`) and, for **each** written mention IRI, one `<mention> prov:wasGeneratedBy <urn:msr:run:extraction/<ts>>` generation edge. All `urn:msr:provenance` writes SHALL use additive `INSERT DATA` with an explicit `GRAPH <urn:msr:provenance>` target (not a graph-replace `PUT`), and SHALL NOT create a `urn:msr:run:*` named graph. The timestamp SHALL be generated once per invocation and shared by the run, so all of a run's mentions reference one per-run activity node.

#### Scenario: A written mention references the stable activity and the per-run activity
- **WHEN** the linking pipeline writes a `msr:Mention`
- **THEN** the mention carries `prov:wasGeneratedBy msrd:activity-extraction` in `urn:msr:data` (with its `msr:inDocument` document as derivation source), and `urn:msr:provenance` carries `<mention> prov:wasGeneratedBy <urn:msr:run:extraction/<ts>>`

#### Scenario: One per-run activity node per invocation
- **WHEN** a single linking-pipeline invocation writes many mentions
- **THEN** exactly one per-run `prov:Activity` node `<urn:msr:run:extraction/<ts>>` exists in `urn:msr:provenance` (attributed to `agent:extraction@<version>` with timestamps and ontology version) and every mention from that run has a generation edge to it, while every mention references `msrd:activity-extraction` in `urn:msr:data`

#### Scenario: Generation edge preserves fact-store idempotency
- **WHEN** the linking pipeline runs twice over the same corpus
- **THEN** the `urn:msr:data` mention-triple count is unchanged, because the mention IRIs and the referenced `msrd:activity-extraction` IRI are deterministic; `urn:msr:provenance` gains a second per-run activity and a second set of generation edges

