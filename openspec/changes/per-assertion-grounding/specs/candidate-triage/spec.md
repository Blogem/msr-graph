## MODIFIED Requirements

### Requirement: Proposed placement is recorded as span-grounded claims
The classifier SHALL propose placement for the candidate — a broader class for a `class`
kind; a `quantityKind` and `canonicalUnit` for a `property` kind; domain/range for a
`relation` kind — and any external (QUDT / INIS) reference. Any placement or relation the
classifier proposes that becomes an **asserted triple** (a broader-class / `rdfs:subClassOf`
axiom, `rdfs:domain`/`rdfs:range`, or an object-property declaration) MUST be accompanied by a
verbatim source quote justifying it, and that quote MUST be verified to occur in the
candidate's source document text (the same containment check `novelty-detection` applies to
candidate evidence). A proposed placement or relation with no verifiable quote SHALL NOT be
asserted: it is dropped from the bundle while the candidate's grounded existence proposal is
still emitted. External (QUDT / INIS) references remain LLM-asserted reviewer claims and are
still not dereferenced against external catalogs.

#### Scenario: A span-grounded placement is asserted
- **WHEN** the classifier proposes a broader class and supplies a source quote that occurs in the candidate's document text
- **THEN** the placement triple is emitted with its evidence span attached

#### Scenario: An unjustified placement is dropped but existence is kept
- **WHEN** the classifier proposes a broader class but supplies no quote, or a quote absent from the source text
- **THEN** the placement triple is not asserted, and the candidate is still proposed with its existence evidence for the reviewer to place

#### Scenario: External references are recorded without dereferencing
- **WHEN** the classifier proposes an INIS descriptor or QUDT reference
- **THEN** it is recorded as a reviewer claim and no external catalog is dereferenced to confirm it
