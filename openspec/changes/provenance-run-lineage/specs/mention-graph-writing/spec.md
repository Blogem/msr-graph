# mention-graph-writing (delta)

## MODIFIED Requirements

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
