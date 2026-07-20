# salt-role-reactor-edges Specification

## Purpose

Define how chunk 7 reintroduces the role/reactor OWL layer that `ground-demo-in-real-docs`
removed (and explicitly deferred here) and populates it from real text: validated salt↔role
statements become `msr:hasRole` edges to a **closed** set of reintroduced seed `msr:SaltRole`
individuals, and validated salt↔reactor statements become `msr:usedIn` edges to a
`msr:MoltenSaltReactor` individual **minted** from a chunk-6-linked reactor mention (never
hand-curated). Every text-derived edge is annotated with extraction confidence/rationale via
RDF reification, and every asserted individual carries generation provenance — deterministically
and idempotently.

## ADDED Requirements

### Requirement: Reintroduce the role/reactor OWL TBox in the seed ontology
The change SHALL re-add to `ontology/msr.ttl` (loaded into `urn:msr:ontology` by `make
load-seed`) the role/reactor OWL layer that `ground-demo-in-real-docs` removed and deferred to
chunk 7: the `msr:SaltRole` class with its closed controlled-vocabulary individuals
`msr:FuelSalt`/`msr:CoolantSalt`/`msr:FlushSalt`, the `msr:hasRole` object property (domain
`msr:MoltenSalt`, range `msr:SaltRole`), the `msr:MoltenSaltReactor` class, and the `msr:usedIn`
object property (domain `msr:MoltenSalt`, range `msr:MoltenSaltReactor`). The addition SHALL be
additive and rdflib-valid, and SHALL NOT seed any reactor individual (reactors are minted from
extraction). The role/reactor SKOS concepts already retained in `vocab.ttl` for NER SHALL NOT
be duplicated.

#### Scenario: Role/reactor TBox loaded with the seed
- **WHEN** `make load-seed` runs after the role/reactor layer is re-added to `ontology/msr.ttl`
- **THEN** `urn:msr:ontology` contains `msr:SaltRole` + `msr:FuelSalt`/`msr:CoolantSalt`/`msr:FlushSalt`, `msr:hasRole`, `msr:MoltenSaltReactor`, and `msr:usedIn`, and no `msr:MoltenSaltReactor` individual is present until extraction mints one

### Requirement: Write salt role edges to a closed set of seed role individuals
The writer SHALL emit a validated salt↔role statement as `msrd:{salt} msr:hasRole msr:{Role}`
into `urn:msr:data` via additive SPARQL `INSERT DATA` through the chunk-5 Python SPARQL-UPDATE
helper, where the salt is a loaded `MoltenSalt` individual and the role is one of the closed set
of reintroduced `msr:SaltRole` individuals (`FuelSalt`/`CoolantSalt`/`FlushSalt`). The direct
edge introduces no new domain individuals and no blank nodes (its extraction-provenance
reification is covered below).

#### Scenario: A coolant-role statement becomes a hasRole edge
- **WHEN** a validated statement asserts that the loaded FLiBe salt is a coolant salt
- **THEN** the graph gains the direct edge `msrd:salt-BeF2-LiF-34.0-66.0 msr:hasRole msr:CoolantSalt` with no blank nodes

### Requirement: Mint and link reactor individuals from grounded mentions
Because `ground-demo-in-real-docs` removed all reactor individuals, the writer SHALL **mint** a
`msr:MoltenSaltReactor` individual when — and only when — the reactor reference in the sentence
is a chunk-6 `status:"linked"` mention resolving to a surviving reactor concept in `vocab.ttl`.
The minted individual SHALL have a deterministic IRI (`msrd:reactor-{slug}`, e.g.
`msrd:reactor-msre`), be typed `a msr:MoltenSaltReactor`, and carry an `rdfs:label` and a link
to its grounding vocab concept via a general-purpose predicate (e.g. `skos:exactMatch` or
`rdfs:seeAlso`) — **not** `msr:linksTo`, whose `rdfs:domain` is `msr:Mention` and which is
constrained by the merged SHACL `LinksToTargetKindShape`. The writer SHALL then emit
`msrd:{salt} msr:usedIn msrd:reactor-{slug}` into `urn:msr:data`. Minting SHALL be deterministic
(the same reactor reference always yields the same IRI) and SHALL NOT create blank nodes. No
installed SHACL shape targets `msr:MoltenSaltReactor`, so the minted individual is unconstrained
by the current catalogue.

#### Scenario: A used-in statement mints a reactor and a usedIn edge
- **WHEN** a validated statement asserts the loaded FLiBe salt was used in the MSRE, and the "MSRE" span is a chunk-6 `linked` mention to the reactor vocab concept
- **THEN** the graph gains a minted `msrd:reactor-msre a msr:MoltenSaltReactor` (with `rdfs:label` and its grounding concept) and the edge `msrd:salt-BeF2-LiF-34.0-66.0 msr:usedIn msrd:reactor-msre`

### Requirement: Every minted reactor carries generation provenance
A minted `msr:MoltenSaltReactor` individual SHALL carry `prov:wasDerivedFrom` its source
`Document` and `prov:wasGeneratedBy msrd:activity-extraction` in `urn:msr:data`, plus a per-run
`prov:wasGeneratedBy <urn:msr:run:extraction/<ts>>` generation edge in `urn:msr:provenance`
(via the reused `provenance.py`) — because it is a pipeline-asserted individual and the
`provenance-model` spec requires generation provenance on every such individual, exactly like a
measurement.

#### Scenario: A minted reactor is fully provenanced
- **WHEN** a reactor individual is minted from an ORNL-TM-2316 mention
- **THEN** it carries `prov:wasDerivedFrom msrd:ORNL-TM-2316` and `prov:wasGeneratedBy msrd:activity-extraction` in `urn:msr:data`, and `urn:msr:provenance` carries its per-run generation edge

### Requirement: Reject unknown roles; require a grounded mention for reactors
The writer SHALL reject a role statement whose role is not one of the closed seed `msr:SaltRole`
individuals, writing nothing — the model can only assert a role from the known set. A `usedIn`
statement whose reactor reference is **not** a chunk-6 `linked` mention to a reactor concept
SHALL produce no edge and SHALL mint nothing — grounding on a linked mention is the guard that
keeps the model from minting a reactor out of thin air.

#### Scenario: An unknown role is rejected
- **WHEN** a statement names a role that is not one of the seed `msr:SaltRole` individuals
- **THEN** the edge is rejected and no triple is written

#### Scenario: An ungrounded reactor reference mints nothing
- **WHEN** a `usedIn` statement's reactor reference is not a chunk-6 `linked` mention to a reactor `vocab.ttl` concept
- **THEN** no reactor individual is minted and no `usedIn` edge is written

### Requirement: Extraction provenance on edges via RDF reification
For a text-derived role/reactor edge, the writer SHALL — in addition to the direct edge — write
a deterministic `rdf:Statement` node reifying that edge (`rdf:subject` the salt, `rdf:predicate`
`msr:hasRole` or `msr:usedIn`, `rdf:object` the role/reactor) carrying `msr:extractionConfidence`
and `msr:extractionRationale`, so the edge's extraction confidence and rationale are queryable
in `urn:msr:data`. The reification node is itself a pipeline-asserted individual, so it SHALL
carry `prov:wasDerivedFrom`/`prov:wasGeneratedBy` generation provenance like any other. It SHALL
have a deterministic IRI with no blank nodes, and the direct edge SHALL remain present and
unchanged so the agent's grounding is unaffected.

#### Scenario: A text-derived role edge carries queryable confidence and provenance
- **WHEN** a text-derived coolant-role edge for the FLiBe salt is written
- **THEN** the graph gains both the direct edge `msrd:salt-BeF2-LiF-34.0-66.0 msr:hasRole msr:CoolantSalt` and an `rdf:Statement` reifying it (`rdf:subject`/`rdf:predicate`/`rdf:object`) that carries `msr:extractionConfidence`, `msr:extractionRationale`, and generation provenance — all queryable

### Requirement: Minted reactors and edges are idempotent
Re-running the extraction MUST leave the role/reactor edge count, the `rdf:Statement`
reification-node count, and the minted-reactor count in `urn:msr:data` unchanged. Because the
direct edges are plain triples on existing individuals and the reification nodes and minted
reactor IRIs are deterministic (no blank nodes), re-asserting anything already present MUST be a
set-semantics no-op. (There are no hand-curated seed edges to re-assert — ground-demo removed
them all.)

#### Scenario: Re-run adds no duplicate edges, reification nodes, or reactors
- **WHEN** the extraction runs twice and asserts the same role/reactor edges
- **THEN** the `urn:msr:data` role/reactor edge count, `rdf:Statement` reification-node count, and minted `msr:MoltenSaltReactor` count are identical after the second run
