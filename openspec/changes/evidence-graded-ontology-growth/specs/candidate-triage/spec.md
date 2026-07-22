## ADDED Requirements

### Requirement: A class signal is emitted instance-first until evidence supports promotion
A `class` context signal on its own SHALL NOT mint a new `owl:Class`. When triage confirms a `class` signal, the candidate SHALL be emitted **instance-first** — recorded as an individual (typed by an existing class where one fits, otherwise parked as an unclassified witness) — and marked as a promotion candidate for the type it implies. A new class SHALL be minted only when the accumulated evidence for that implied type crosses the configured promotion threshold (see `novelty-detection`). This prevents a single witness from creating a parentless, evidence-thin class.

#### Scenario: A single-witness class signal does not mint a class
- **WHEN** a candidate triages with a `class` signal but its implied type has evidence below the promotion threshold
- **THEN** the candidate is emitted as an instance (typed by an existing class where one fits, else parked as an unclassified witness) and no new `owl:Class` is minted

#### Scenario: An accumulated type is promoted to a class
- **WHEN** the implied type of several instance witnesses reaches the promotion threshold
- **THEN** a class proposal is created and those accumulated witnesses become the new class's instances and its grounding evidence

### Requirement: Promotion distinguishes instance-of-new-class from subclass-of-existing-class
When a type is promoted, triage SHALL decide — as an evidence-shaped judgment — whether the promoted term is best modeled as an **instance of a new class** (a specific thing, e.g. graphite as an instance of a new `Moderator` class) or a **subclass of an existing class** (a kind-of, e.g. "emergency cooling" as `rdfs:subClassOf` an existing `SafetyFunction`). The decision SHALL be recorded on the proposal as a reviewer-verifiable claim, with its rationale.

#### Scenario: A specific thing promotes to an instance of a new class
- **WHEN** the promoted term denotes a specific individual whose siblings share an unmodeled type
- **THEN** the proposal mints the new class and types the term (and its sibling witnesses) as instances of it

#### Scenario: A kind-of term promotes to a subclass of an existing class
- **WHEN** the promoted term denotes a subtype of a class already in the ontology
- **THEN** the proposal asserts the term as `rdfs:subClassOf` that existing class rather than as an instance

## MODIFIED Requirements

### Requirement: Proposed placement is recorded as reviewer-verifiable claims
The classifier SHALL propose placement for the candidate — a broader/parent class for a `class`
kind; a `quantityKind` and `canonicalUnit` for a `property` kind; domain/range for a
`relation` kind — and any external (QUDT / INIS) reference. These SHALL be recorded as
LLM-asserted claims (evidence for the reviewer), not validated against external catalogs. Each
placement and unit claim SHALL carry a **confidence signal**, and SHALL be recorded as a
*suggested* value distinct from an *asserted* one, so the reviewer can tell a confident
placement from a tentative one. When the unit is uncertain the classifier SHALL record its
best-effort value as a **low-confidence suggestion** rather than omitting it entirely — a blank
is never preferable to a flagged suggestion the reviewer can accept or override.

#### Scenario: Placement recorded without external validation
- **WHEN** the classifier proposes a broader class and an INIS descriptor for a candidate
- **THEN** both are recorded on the candidate as claims, and no external catalog is dereferenced to confirm them

#### Scenario: An uncertain unit is recorded as a low-confidence suggestion
- **WHEN** the classifier is unsure of a property's canonical unit
- **THEN** it records its best-effort unit as a suggested value flagged low-confidence, rather than leaving the unit unset
