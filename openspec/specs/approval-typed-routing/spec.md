# approval-typed-routing Specification

## Purpose

Define how an approved proposal's bundle is promoted into the core graphs. A proposal is one
bundle of nodes + edges the reviewer accepts as a whole, but its triples belong to different
core graphs; approval therefore routes each triple **by what it is** — not by the proposal's
display `msr:kind` — copying it into `urn:msr:vocab`, `urn:msr:ontology`, or `urn:msr:data`,
while leaving the proposal graph in place as the audit record. The routing must be atomic
against the SHACL sail and idempotent across re-runs.

## Requirements

### Requirement: Triples are routed to core graphs by type, not by proposal kind
On approval the engine SHALL copy the proposal graph's triples into the core graphs by triple
type, ignoring the proposal's `msr:kind`: subjects that are `skos:Concept` and SKOS-predicate
triples SHALL go to `urn:msr:vocab`; TBox axioms — `owl:Class`/`owl:ObjectProperty`/
`owl:DatatypeProperty` declarations, `rdfs:subClassOf`, `rdfs:domain`/`rdfs:range`, and
`msr:PhysicalProperty` individuals with their `msr:quantityKind`/`msr:canonicalUnit` — SHALL go
to `urn:msr:ontology`; all remaining triples (individuals and edges between individuals) SHALL
go to `urn:msr:data`.

#### Scenario: A property proposal routes to ontology and vocab
- **WHEN** the `solubility` proposal is approved
- **THEN** the `msr:solubility` TBox triples are copied into `urn:msr:ontology` and the `voc:solubility` SKOS concept into `urn:msr:vocab`, and both are now visible through the core-dataset read

#### Scenario: A mixed class bundle routes each triple by type
- **WHEN** the `graphite` bundle (`msr:Moderator` class + `msr:moderatedBy` object property + the `msrd:graphite` individual typed by that class) is approved
- **THEN** the `Moderator` class and `moderatedBy` property are copied into `urn:msr:ontology` and the `graphite` individual (and its edges) into `urn:msr:data`

### Requirement: Routing is implemented as filtered graph-to-graph copies in one transaction
Routing SHALL be performed as filtered `INSERT { GRAPH <dest> { ?s ?p ?o } } WHERE { GRAPH
<urn:msr:proposal/{id}> { ?s ?p ?o } FILTER(...) }` copies, and all copies for one approval
SHALL execute in a single SPARQL UPDATE request so GraphDB validates and commits them as one
transaction. If the SHACL sail rejects any routed triple, the whole promotion SHALL be rolled
back and nothing SHALL be copied into any core graph.

#### Scenario: SHACL rejection rolls back the whole promotion
- **WHEN** approving a proposal whose routed triples would violate a SHACL shape
- **THEN** GraphDB rejects the transaction, no triples appear in any core graph, and a typed validation error is surfaced

### Requirement: The proposal graph is retained as an audit record
Approval SHALL copy triples out of the `urn:msr:proposal/{id}` graph without deleting them; the
proposal graph SHALL remain intact after approval as the audit record of what was promoted.

#### Scenario: Proposal graph survives approval
- **WHEN** a proposal is approved
- **THEN** its `urn:msr:proposal/{id}` graph still contains the original proposed triples

### Requirement: Re-running an approval is idempotent
Approving the same proposal again (including after a restore that reset it to `pending`) SHALL
leave the core graphs' triple counts unchanged from the first successful approval, with no
duplicated triples — because routing copies are additive `INSERT` and proposal IRIs are
deterministic.

#### Scenario: Second approval adds no duplicate core triples
- **WHEN** an already-approved proposal is approved a second time
- **THEN** the core graphs contain the same triples as after the first approval, with no duplicates
