## MODIFIED Requirements

### Requirement: Two-graph staging model per proposal
A proposal SHALL be represented as two parts: a `msr:ChangeProposal` resource written to `urn:msr:staging` (carrying kind, review status, term, its `msr:hasObservation` per-document/per-corpus observations, its `msr:hasEvidence` sample sentences, and an `msr:hasProposalGraph` link) and the actual proposed triples written to a dedicated `urn:msr:proposal/{id}` named graph. Corpus support SHALL be carried as `msr:hasObservation` observation nodes (see `proposal-observation-provenance`), NOT as a stored `msr:docFrequency` scalar; document frequency is a read-time aggregate over those observations. The `ChangeProposal` resource MUST reference its proposal graph, so chunk 9 can list staging, resolve the proposal graph, and route its triples.

#### Scenario: Proposal split across staging and proposal graph
- **WHEN** a proposal for `solubility` is written
- **THEN** the `msr:ChangeProposal` resource is in `urn:msr:staging` with `msr:hasProposalGraph` pointing at `urn:msr:proposal/{id}`, and the proposed `msr:solubility` / `voc:solubility` triples are in that `urn:msr:proposal/{id}` graph

#### Scenario: Corpus support is carried as observations, not a scalar
- **WHEN** a `msr:ChangeProposal` resource is inspected
- **THEN** it carries `msr:hasObservation` nodes for the documents its term was seen in and does not carry a stored `msr:docFrequency` scalar
