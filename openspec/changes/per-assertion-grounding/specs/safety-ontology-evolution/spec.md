## MODIFIED Requirements

### Requirement: Genre-aware triage places safety candidates within the fixed kind set
The system SHALL make the `candidate-triage` classifier genre-aware for the safety genre **without adding new triage kinds**: safety concepts are triaged as `class`-kind proposals whose proposed placement is a Safety broader class (`SafetyFunction`/`Requirement`/`Confinement`/`DefenceInDepth`/`DesignBasis`), and the two linking edges are triaged as `relation`-kind proposals with proposed domain/range. The genre prompt SHALL keep the classifier from rejecting domain-shaped safety phrases as boilerplate. A `class`-kind safety proposal SHALL NOT auto-emit any companion object property, and its Safety broader-class placement SHALL be asserted only when a source span states it (per `candidate-triage`); a placement with no justifying span SHALL be omitted and left as a reviewer decision. The `change-proposal-schema` mini-schema (as amended for per-triple evidence), `proposal-staging` graphs, and `approval-typed-routing` otherwise remain unchanged. Proposals SHALL remain invisible via the core-dataset client until approved.

#### Scenario: A safety concept is triaged as a class proposal with a span-grounded Safety placement
- **WHEN** triage classifies a mined safety concept such as "heat removal" and a source span states it is a fundamental safety function
- **THEN** the emitted `msr:ChangeProposal` carries `msr:kind "class"` with the Safety broader-class placement asserted from that span, emits no companion object property, and its proposed triples sit in `urn:msr:proposal/{id}` (invisible to the core-dataset client)

#### Scenario: A safety class with no placement span is proposed without a placement axiom
- **WHEN** triage classifies a safety concept but no source span states its broader class
- **THEN** the proposal is emitted with the concept's existence evidence and no broader-class axiom, leaving placement to the reviewer

#### Scenario: A linking edge is triaged as a relation proposal
- **WHEN** triage classifies a mined linking concept (e.g. a safety-function-to-property dependency) stated in a source span
- **THEN** the emitted proposal carries `msr:kind "relation"` with span-grounded domain/range, and its object-property triples route to `urn:msr:ontology` on approval by triple type
