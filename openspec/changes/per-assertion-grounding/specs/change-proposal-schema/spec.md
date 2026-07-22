## ADDED Requirements

### Requirement: Asserted triples carry per-triple evidence
Every **assertion-required** triple in a proposal bundle MUST reference the source span(s) that justify it, so evidence is resolvable per triple rather than only at the `msr:ChangeProposal` resource. Assertion-required triples are the candidate's existence typing, any `rdfs:subClassOf` / broader-class placement, any `owl:ObjectProperty` / `owl:DatatypeProperty` declaration, and any `rdfs:domain` / `rdfs:range`. A fixed, enumerated set of **scaffolding** triples is exempt:
the `owl:Class` type declaration of an already-grounded term, the `rdf:type` of the candidate's
own individual, and `prov:*` provenance edges. A proposal MUST NOT assert an assertion-required
triple that references no span. The per-triple evidence representation MUST let a reader
resolve, for any asserted triple, the exact span backing it (e.g. via RDF-star or reification;
chosen in design).

#### Scenario: An asserted placement references its own span
- **WHEN** a class proposal asserts a broader-class placement
- **THEN** that triple references the evidence span justifying it, resolvable independently of other triples in the bundle

#### Scenario: Scaffolding triples need no span
- **WHEN** a proposal declares the `owl:Class` for its grounded term and the `rdf:type` / `prov:*` of its individual
- **THEN** those scaffolding triples are emitted without per-triple evidence and do not trip any grounding check

## MODIFIED Requirements

### Requirement: Primary kind is for display; a bundle may mix triple types
The `msr:kind` of a proposal SHALL record the primary kind for triage and display, but the
proposal graph MAY contain a mix of TBox axioms and instance triples in one bundle. The
schema MUST NOT require the proposal graph's triples to all match the primary kind, because
approval routing routes each triple by what it is, ignoring `msr:kind`. Any object or datatype
property appearing in a bundle MUST be a span-grounded relation; the schema MUST NOT synthesize
a companion property from the class name.

#### Scenario: A class proposal bundles only grounded triples
- **WHEN** a `class`-kind proposal is written
- **THEN** its proposal graph contains the class declaration and the candidate individual typed by it, plus any span-grounded placement or relation — and no object property synthesized from the class name
