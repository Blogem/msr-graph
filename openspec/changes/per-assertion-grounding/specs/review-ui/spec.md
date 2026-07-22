## ADDED Requirements

### Requirement: Per-triple grounding shown in proposal detail
The proposal detail SHALL indicate, for each asserted triple in the bundle, whether it carries
a span-backed evidence link, and SHALL surface that span, so a reviewer can see which axioms are
grounded and cannot approve an ungrounded axiom without noticing it. Scaffolding-exempt triples
MAY be marked as such (grounding not applicable). This complements the proposal-level evidence
panel, which continues to show the candidate's aggregate evidence and observation breakdown.

#### Scenario: Grounded and ungrounded triples are distinguished
- **WHEN** a proposal detail is rendered for a bundle mixing span-grounded and (legacy) ungrounded assertion triples
- **THEN** each asserted triple shows its evidence span or is marked as lacking one, and scaffolding triples are shown distinctly as grounding-not-applicable

#### Scenario: A reviewer sees the grounding of a placement before approving
- **WHEN** a reviewer opens a class proposal whose broader-class placement is span-grounded
- **THEN** the detail shows the placement triple alongside the span that backs it
