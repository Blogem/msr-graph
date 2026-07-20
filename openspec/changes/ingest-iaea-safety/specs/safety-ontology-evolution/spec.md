## ADDED Requirements

### Requirement: Safety branch grown via the evolution loop, never seeded
The system SHALL introduce the `Safety` ontology branch — `msr:SafetyFunction`, `msr:Requirement`, `msr:Confinement`, `msr:DefenceInDepth`, `msr:DesignBasis` — **only** as change proposals mined from the safety genre (chunk 8) and promoted to `urn:msr:ontology` by the approval engine (chunk 9). No safety class SHALL be added to the seed ontology, and no safety class SHALL enter core except through an approved proposal that bumps `owl:versionInfo`.

#### Scenario: No safety class is seeded
- **WHEN** the seed ontology is loaded and before any safety proposal is approved
- **THEN** none of `msr:SafetyFunction`, `msr:Requirement`, `msr:Confinement`, `msr:DefenceInDepth`, `msr:DesignBasis` exists in `urn:msr:ontology`

#### Scenario: Approval promotes a safety class and bumps the version
- **WHEN** a mined `SafetyFunction` proposal is approved via the chunk-9 API
- **THEN** the class is routed into `urn:msr:ontology`, `owl:versionInfo` is bumped with a PROV record, and the class becomes visible to the core-dataset client

### Requirement: Multi-word safety-concept candidate mining
The system SHALL extend the novelty miner to surface multi-word (noun-phrase) candidates for the safety genre — e.g. "confinement of radioactive material", "defence in depth", "removal of residual heat" — using the same document-frequency scoring and evidence-sentence capture as single-token candidates. The three fundamental safety functions (confinement of radioactive material, control of reactivity, heat removal) MUST surface as proposals from the ingested sources.

#### Scenario: Fundamental safety functions surface as proposals
- **WHEN** the miner runs over the ingested safety genre
- **THEN** proposals corresponding to confinement of radioactive material, control of reactivity, and heat removal are present in staging, each with an evidence sentence and `msr:citedIn` a safety `Document`

#### Scenario: Multi-word candidates are extracted, not just unigrams
- **WHEN** a safety sentence contains a multi-word safety concept
- **THEN** the miner emits the noun-phrase candidate (not only its constituent unigrams) with document-frequency evidence

### Requirement: Genre-aware triage into safety class kinds
The system SHALL make the triage classifier genre-aware so safety candidates are classified into the safety class kinds (`SafetyFunction`/`Requirement`/`Confinement`/`DefenceInDepth`/`DesignBasis`), while the ChangeProposal mini-schema, staging graphs, and approval routing remain unchanged. Proposals SHALL remain invisible via the core-dataset client until approved.

#### Scenario: A safety candidate is triaged to a safety class kind
- **WHEN** triage classifies a mined safety candidate
- **THEN** the emitted `msr:ChangeProposal` carries a safety `msr:kind` and validates against the existing mini-schema, and its proposed triples sit in `urn:msr:proposal/{id}` (invisible to the core-dataset client)
