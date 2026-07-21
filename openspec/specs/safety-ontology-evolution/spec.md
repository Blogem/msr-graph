# safety-ontology-evolution Specification

## Purpose

Define how the `Safety` ontology branch is grown — never seeded — through the mine (chunk 8) and approve (chunk 9) evolution loop: multi-word safety-concept candidates are mined from the safety genre, triaged genre-aware within the fixed kind set, and promoted into core `urn:msr:ontology` only via approved change proposals.

## Requirements

### Requirement: Safety branch grown via the evolution loop, never seeded
The system SHALL introduce the `Safety` ontology branch — `msr:SafetyFunction`, `msr:Requirement`, `msr:Confinement`, `msr:DefenceInDepth`, `msr:DesignBasis` — **only** as change proposals mined from the safety genre (chunk 8) and promoted to `urn:msr:ontology` by the approval engine (chunk 9). No safety class SHALL be added to the seed ontology, and no safety class SHALL enter core except through an approved proposal that bumps `owl:versionInfo`.

#### Scenario: No safety class is seeded
- **WHEN** the seed ontology is loaded and before any safety proposal is approved
- **THEN** none of `msr:SafetyFunction`, `msr:Requirement`, `msr:Confinement`, `msr:DefenceInDepth`, `msr:DesignBasis` exists in `urn:msr:ontology`

#### Scenario: Approval promotes a safety class and bumps the version
- **WHEN** a mined `SafetyFunction` proposal is approved via the chunk-9 API
- **THEN** the class is routed into `urn:msr:ontology`, `owl:versionInfo` is bumped with a PROV record, and the class becomes visible to the core-dataset client

### Requirement: Multi-word safety-concept candidate mining
The system SHALL extend the built `novelty-detection` spaCy noun-chunk candidate pass for the safety genre so prepositional multi-word safety concepts survive enumeration — e.g. "confinement of radioactive material", "removal of residual heat" — rather than being lost to the existing 1–3 content-token window that drops stopwords such as _of_/_in_. The extension SHALL relax that window / preserve the noun-chunk head phrase for the safety genre while reusing unchanged the document-frequency floor/ceiling cost bound, the known/linked exclusion, and the curated-set evidence-sentence capture (`msr:citedIn` + offsets). The three fundamental safety functions (confinement of radioactive material, control of reactivity, heat removal) MUST surface as proposals from the ingested sources.

#### Scenario: Fundamental safety functions surface as proposals
- **WHEN** the miner runs over the ingested safety genre
- **THEN** proposals corresponding to confinement of radioactive material, control of reactivity, and heat removal are present in staging, each with an evidence sentence and `msr:citedIn` a safety `Document`

#### Scenario: A prepositional safety concept survives the token window
- **WHEN** a safety sentence contains a multi-word safety concept whose surface form exceeds the existing 1–3 content-token window (e.g. "removal of residual heat")
- **THEN** the miner emits the noun-phrase candidate (not only its constituent unigrams) with document-frequency evidence

### Requirement: Genre-aware triage places safety candidates within the fixed kind set
The system SHALL make the `candidate-triage` classifier genre-aware for the safety genre **without adding new triage kinds**: safety concepts are triaged as `class`-kind proposals whose proposed placement is a Safety broader class (`SafetyFunction`/`Requirement`/`Confinement`/`DefenceInDepth`/`DesignBasis`), and the two linking edges are triaged as `relation`-kind proposals with proposed domain/range. The genre prompt SHALL keep the classifier from rejecting domain-shaped safety phrases as boilerplate. The `change-proposal-schema` mini-schema, `proposal-staging` graphs, and `approval-typed-routing` remain unchanged. Proposals SHALL remain invisible via the core-dataset client until approved.

#### Scenario: A safety concept is triaged as a class proposal with a Safety placement
- **WHEN** triage classifies a mined safety concept such as "heat removal"
- **THEN** the emitted `msr:ChangeProposal` carries `msr:kind "class"` with a proposed Safety broader-class placement, validates against the existing mini-schema, and its proposed triples sit in `urn:msr:proposal/{id}` (invisible to the core-dataset client)

#### Scenario: A linking edge is triaged as a relation proposal
- **WHEN** triage classifies a mined linking concept (e.g. a safety-function-to-property dependency)
- **THEN** the emitted proposal carries `msr:kind "relation"` with proposed domain/range, and its object-property triples route to `urn:msr:ontology` on approval by triple type
