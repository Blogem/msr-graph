# entity-ruler-seeding Specification

## Purpose
TBD - created by archiving change ner-entity-linking. Update Purpose after archive.
## Requirements
### Requirement: Matcher seeded from the graph at run start
The extraction run SHALL build its spaCy `EntityRuler`/`PhraseMatcher` by reading the graph at the start of every run: SKOS concepts from `urn:msr:vocab` (prefLabels + altLabels), the ontology classes/properties from `urn:msr:ontology`, and the `MoltenSalt` individuals of the chunk-2 salt catalog from `urn:msr:data` (their canonical labels/IRIs). No pattern set is persisted between runs — the matcher is rebuilt from the current graph each time.

#### Scenario: Vocab and salt catalog seed the matcher
- **WHEN** an extraction run starts with the seed vocab loaded and the chunk-2 salt catalog present in `urn:msr:data`
- **THEN** the built matcher contains patterns for the vocab concept labels (e.g. `viscosity`, `MSRE`) and for the loaded salt individuals (e.g. the `LiF-BeF2` canonical labels), each associated with its target IRI

#### Scenario: Rebuilt every run, not cached
- **WHEN** two extraction runs execute against the same graph
- **THEN** each run rebuilds the matcher from the graph rather than reusing a persisted pattern file

### Requirement: Seeding reads the core dataset only
The graph reader that seeds the matcher SHALL restrict its reads to the three core graphs (`urn:msr:ontology`, `urn:msr:data`, `urn:msr:vocab`) by injecting them as the query's dataset (SPARQL `FROM`/`FROM NAMED` or the equivalent protocol `default-graph-uri`/`named-graph-uri` parameters), mirroring the core-dataset-access contract on the Python side. Concepts residing only in `urn:msr:staging` or `urn:msr:proposal/{id}` MUST NOT seed the matcher.

#### Scenario: Approved concepts seed, pending proposals do not
- **WHEN** one concept exists in `urn:msr:vocab` (approved) and another exists only in `urn:msr:staging` (pending), and the matcher is built
- **THEN** the approved concept produces a pattern and the staging-only concept does not

### Requirement: Pattern-variant generation for expanded exact matching
The seeding step SHALL expand each label into generated surface variants — hyphen/no-hyphen, spacing, and case (via spaCy `attr="LOWER"`) — so common OCR-surface variation is matched as cheap exact patterns rather than requiring fuzzy matching. Variant generation MUST be a pure, deterministic function of the input label.

#### Scenario: Case and spacing variants generated
- **WHEN** variant generation runs on a label such as `LiF-BeF2`
- **THEN** it yields the case-insensitive and hyphen/spacing variants (e.g. `lif-bef2`, `LiF BeF2`) as additional exact patterns for the same target

### Requirement: Approved evolution concepts reach NER on the next run
Because the matcher is rebuilt from the core dataset each run, a concept promoted into a core graph by the evolution loop (chunks 8→9) SHALL be seeded on the next extraction run with no separate refresh signal.

#### Scenario: A newly-approved concept becomes matchable
- **WHEN** a new concept is added to `urn:msr:vocab` (as an approval would) and a subsequent extraction run starts
- **THEN** the rebuilt matcher includes a pattern linking that concept's labels to its IRI

### Requirement: OCR-subscript surface variants for known formulas
Pattern-variant generation SHALL additionally emit surface variants that model the corpus OCR subscript artifact — a comma or a period standing in for a subscript digit — for each known catalog compound and `MoltenSalt` formula token that carries a subscript digit, so the seeded matcher recognizes the OCR forms of entities that actually exist. Variant generation MUST remain a pure, deterministic function of its input and MUST derive OCR variants ONLY from the graph's known formulas — it MUST NOT invent a formula the catalog has not loaded.

#### Scenario: Comma and period subscript variants are generated
- **WHEN** OCR-variant generation runs on a known compound formula such as `BeF2`
- **THEN** it yields the comma and period subscript forms (`BeF,`, `BeF.`) as additional exact patterns for the same target

#### Scenario: Multi-component salt formula OCR variants
- **WHEN** OCR-variant generation runs on a multi-component formula such as `LiF-BeF2`
- **THEN** it yields the per-component comma/period subscript form (e.g. `LiF-BeF,`) for the same target

#### Scenario: OCR variants derive only from known formulas
- **WHEN** a formula token is not among the graph's loaded compounds/salts
- **THEN** no OCR-subscript variant is seeded for it (matching stays anchored to known entities)

