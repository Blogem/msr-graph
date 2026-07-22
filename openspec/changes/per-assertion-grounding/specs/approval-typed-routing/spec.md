## ADDED Requirements

### Requirement: Ungrounded axioms are refused at approval
The approval engine SHALL re-check, before routing, that every assertion-required triple in the
proposal graph carries a span-backed evidence link, and SHALL refuse the approval — routing
nothing into any core graph and leaving the proposal pending with a typed error — if any
assertion-required triple is ungrounded. This mirrors the `proposal-staging` grounding gate at
the promotion boundary so that an ungrounded axiom can never reach `urn:msr:ontology` /
`urn:msr:data`, regardless of how the proposal graph was produced (e.g. a legacy proposal
staged before this change). Grounded triples SHALL continue to route to core graphs by triple
type, unchanged.

#### Scenario: Approval refuses an ungrounded axiom
- **WHEN** a proposal graph containing an ungrounded `owl:ObjectProperty` declaration is approved
- **THEN** the engine refuses the promotion, no triples are copied into any core graph, and the proposal remains pending with a typed grounding error

#### Scenario: A fully grounded proposal routes normally
- **WHEN** an approved proposal's assertion-required triples are all span-grounded
- **THEN** the grounding re-check passes and routing proceeds by triple type as before
