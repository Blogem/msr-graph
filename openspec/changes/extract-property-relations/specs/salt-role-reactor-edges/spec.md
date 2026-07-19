# salt-role-reactor-edges Specification

## Purpose

Define how validated salt↔role and salt↔reactor statements extracted from text are written
to `urn:msr:data` as plain edges on existing individuals — `msr:hasRole` to a seed
`msr:SaltRole` and `msr:usedIn` to a loaded `msr:MoltenSaltReactor` — deterministically and
idempotently, linking only to entities already in the known schema.

## ADDED Requirements

### Requirement: Write salt role and reactor edges to the core data graph
The writer SHALL emit a validated salt↔role statement as `msrd:{salt} msr:hasRole
msr:{Role}` and a validated salt↔reactor statement as `msrd:{salt} msr:usedIn
msrd:{Reactor}` into `urn:msr:data` via additive SPARQL `INSERT DATA` through the chunk-5
Python SPARQL-UPDATE helper. Both the salt and the role/reactor MUST be existing individuals
(a loaded `MoltenSalt`, and a seed `msr:SaltRole` — `FuelSalt`/`CoolantSalt`/`FlushSalt` —
or a loaded `msr:MoltenSaltReactor`); the direct edge introduces no new domain individuals and
no blank nodes (its extraction-provenance reification node is covered separately below).

#### Scenario: A coolant-role statement becomes a hasRole edge
- **WHEN** a validated statement asserts that the loaded FLiBe salt is a coolant salt
- **THEN** the graph gains the direct edge `msrd:salt-BeF2-LiF-34.0-66.0 msr:hasRole msr:CoolantSalt` with no blank nodes

#### Scenario: A used-in statement becomes a usedIn edge
- **WHEN** a validated statement asserts that the loaded FLiBe salt was used in the MSRE
- **THEN** the graph gains `msrd:salt-BeF2-LiF-34.0-66.0 msr:usedIn msrd:MSRE`

### Requirement: Reject edges naming unknown roles or reactors
The writer SHALL reject a role/reactor statement whose role is not a seed `msr:SaltRole`
individual or whose reactor is not a loaded `msr:MoltenSaltReactor` individual, writing
nothing — the model can only relate known individuals, never introduce a new role or reactor.

#### Scenario: An unknown reactor is rejected
- **WHEN** a statement names a reactor IRI absent from the known-IRI set
- **THEN** the edge is rejected and no triple is written

#### Scenario: An unknown role is rejected
- **WHEN** a statement names a role that is not one of the seed `msr:SaltRole` individuals
- **THEN** the edge is rejected and no triple is written

### Requirement: Extraction provenance on edges via RDF reification
For a text-derived role/reactor edge, the writer SHALL — in addition to the direct edge —
write a deterministic `rdf:Statement` node reifying that edge (`rdf:subject` the salt,
`rdf:predicate` `msr:hasRole` or `msr:usedIn`, `rdf:object` the role/reactor) and carrying
`msr:extractionConfidence` and `msr:extractionRationale`, so the edge's extraction confidence
and rationale are queryable in `urn:msr:data`. The reification node SHALL have a deterministic
IRI with no blank nodes, and the direct edge SHALL remain present and unchanged so the agent's
grounding is unaffected. A hand-curated seed edge (not extracted from text) SHALL carry no
reification and no extraction confidence.

#### Scenario: A text-derived role edge carries queryable confidence
- **WHEN** a text-derived coolant-role edge for the FLiBe salt is written
- **THEN** the graph gains both the direct edge `msrd:salt-BeF2-LiF-34.0-66.0 msr:hasRole msr:CoolantSalt` and an `rdf:Statement` reifying it (`rdf:subject`/`rdf:predicate`/`rdf:object`) that carries `msr:extractionConfidence` and `msr:extractionRationale`, both queryable

#### Scenario: A hand-curated seed edge has no extraction provenance
- **WHEN** an edge exists only from the hand-curated seed A-Box, not extracted from text
- **THEN** it carries no `rdf:Statement` reification and no `msr:extractionConfidence`

### Requirement: Role/reactor edges are idempotent
Re-running the extraction MUST leave both the role/reactor edge count and the reification-node
count unchanged. Because the direct edges are plain triples on existing individuals and the
reification nodes have deterministic IRIs (no blank nodes), re-asserting an edge that already
exists — a previously extracted edge or a hand-curated seed edge (e.g. the FLiBe `msr:hasRole
msr:CoolantSalt`) — MUST be a set-semantics no-op.

#### Scenario: Re-run adds no duplicate edges or reification nodes
- **WHEN** the extraction runs twice and asserts the same role/reactor edges
- **THEN** the `urn:msr:data` role/reactor edge count and `rdf:Statement` reification-node count are identical after the second run

#### Scenario: Re-asserting a seed edge is a no-op
- **WHEN** the extractor asserts an edge already present in the seed A-Box
- **THEN** no duplicate direct triple is created
