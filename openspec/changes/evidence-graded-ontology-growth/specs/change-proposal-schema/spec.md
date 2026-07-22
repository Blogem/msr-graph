## ADDED Requirements

### Requirement: A promotion proposal references its witness instances
A class or subclass proposal created by promotion SHALL reference, via a dedicated predicate, the accumulated **witness individuals** whose evidence justified the promotion. The witnesses SHALL be resolvable to their evidence (the sentences/documents they were mined from), so a reviewer can see *why* the type earned class-hood rather than taking a one-shot judgment on faith.

#### Scenario: A promoted class links to its witnesses
- **WHEN** a class is proposed by promotion from several instance witnesses
- **THEN** the `ChangeProposal` references each witness individual, and each witness resolves to its grounding evidence

### Requirement: Suggested placement and unit are recorded distinctly from asserted values
The proposal schema SHALL represent a *suggested* placement or unit (a low- or medium-confidence classifier claim awaiting reviewer confirmation) with a predicate distinct from the corresponding *asserted* value (e.g. a `msr:suggestedUnit` separate from `msr:canonicalUnit`, and an analogous distinction for a suggested parent/placement). A suggested value SHALL carry its confidence and SHALL NOT be treated as an asserted axiom by approval routing until a reviewer confirms it.

#### Scenario: A suggested unit is stored separately from a confirmed one
- **WHEN** the classifier proposes a low-confidence unit for a property proposal
- **THEN** the proposal records it under the suggested-unit predicate with its confidence, and no `msr:canonicalUnit` is asserted until a reviewer confirms it

### Requirement: An off-allowlist unit suggestion flags the proposal rather than discarding it
When a classifier's suggested unit is outside the QUDT allowlist, the proposal SHALL be **created and flagged for reviewer adjudication**, carrying the off-allowlist suggestion as evidence — it SHALL NOT be silently discarded. Discarding the whole proposal for an off-allowlist unit hides exactly the case a human should decide (extend the allowlist, pick a different unit, or reject).

#### Scenario: An off-allowlist unit produces a flagged proposal, not a silent drop
- **WHEN** a property candidate's suggested unit is not in the QUDT allowlist
- **THEN** the proposal is still created, flagged as needing a unit decision, and records the off-allowlist suggestion — rather than being dropped with nothing written

### Requirement: A proposal records whether it needs a reviewer placement decision
Each proposal SHALL carry a state distinguishing a **confident placement** (the classifier's placement/unit is high-confidence — the reviewer merely confirms) from one that **needs a reviewer decision** (placement or unit is missing, low-confidence, or off-allowlist). This state is a schema fact on the `ChangeProposal`, so downstream consumers (including a later review UI) can tell "confirm" from "decide" without re-deriving it.

#### Scenario: A low-confidence placement is marked needs-decision
- **WHEN** a proposal's placement or unit is missing, low-confidence, or off-allowlist
- **THEN** the `ChangeProposal` records a needs-decision state

#### Scenario: A high-confidence placement is marked confirm
- **WHEN** a proposal's placement and unit are all high-confidence and allowlisted
- **THEN** the `ChangeProposal` records a confirm state

### Requirement: A promoted class connects into the ontology
A class or subclass proposal SHALL assert at least one **connecting edge** into the existing ontology — an `rdfs:subClassOf` to an existing parent class where one fits, and/or a companion relation whose `rdfs:domain` and `rdfs:range` are both typed against existing or co-proposed classes. A proposal SHALL NOT introduce a bare, parentless `owl:Class` with only a range-only relation (the current floating-island outcome). Where no suitable parent or fully-typed relation can be determined, the proposal SHALL be marked needs-decision rather than committing a disconnected class.

#### Scenario: A promoted class attaches to an existing parent
- **WHEN** a class is promoted and an existing class is a suitable parent
- **THEN** the proposal asserts `rdfs:subClassOf` that parent, so the class is not disconnected

#### Scenario: A class with no determinable placement is flagged, not floated
- **WHEN** a class is promoted but neither a parent nor a fully domain+range-typed relation can be determined
- **THEN** the proposal is marked needs-decision rather than committing a parentless class with a range-only relation
