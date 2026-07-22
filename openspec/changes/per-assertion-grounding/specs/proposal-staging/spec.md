## ADDED Requirements

### Requirement: Grounding gate rejects ungrounded assertion triples
The staging step SHALL, before a proposal is written to `urn:msr:staging` / `urn:msr:proposal/{id}`, classify each bundle triple as **assertion-required** or **scaffolding-exempt** (the enumerated set defined by `change-proposal-schema`) and reject any assertion-required triple that carries no span-backed evidence link. A bundle containing an ungrounded
assertion-required triple SHALL be rejected as a whole — dropped from the run and not written —
in parallel to the QUDT-allowlist guard. Scaffolding-exempt triples (the `owl:Class` type
declaration of the grounded term, the individual's `rdf:type`, and `prov:*` edges) SHALL NOT
trip the gate.

#### Scenario: An ungrounded axiom rejects the proposal
- **WHEN** a bundle would assert an `owl:ObjectProperty` declaration (or a broader-class axiom) with no evidence link
- **THEN** the grounding gate fires and nothing is written for that proposal

#### Scenario: A fully grounded bundle is written
- **WHEN** every assertion-required triple in a bundle references a span and only scaffolding triples lack evidence
- **THEN** the grounding gate passes and the proposal is staged
