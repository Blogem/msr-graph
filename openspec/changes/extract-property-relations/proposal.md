# Proposal: extract-property-relations

## Why

Chunk 6 links text spans to known salts, properties, reactors, and vocab concepts, but a
linked mention is not yet a fact: nothing turns "the viscosity of FLiBe is
`η = 0.084·exp(4340/T)`" in ORNL-TM-2316 into a queryable measurement. This change closes
the unstructured→structured loop by extracting salt↔property↔value measurements and
salt↔reactor↔role edges from the linked sentences and writing them into **exactly the two
stores the analysis agent (chunk 4) already reads** — the graph (`urn:msr:data`) and the
`measurement_value` table — so the agent's answer surface grows to text-derived facts with
**no agent code change**. It is the P4 milestone's "knowledge grows from text" for the
_known_ schema (novel concepts like `solubility` are chunk 8's job).

## What Changes

- **DeepSeek V4 Flash relation extractor over linked sentences**: for each curated
  sentence that carries chunk-6 linked mentions, a schema-constrained Flash call proposes
  relations (a salt + property + value/equation + unit; a salt + role; a salt + reactor).
  Output is validated app-side against the run's **known-IRI set** (salts, `PhysicalProperty`
  individuals, `MoltenSaltReactor` individuals, `SaltRole` individuals) and the QUDT unit
  allowlist — any relation naming an unknown IRI or unit is **rejected, never written**.
  This resolves the plan's rules-vs-LLM question: the LLM extracts, the app validates. The
  client is an injected OpenAI-compatible interface, **stubbed in every test**.
- **Unit-string → QUDT unit mapping**: extracted unit surface forms (`cP`, `mPa·s`,
  `g/cm³`, `mN/m`, …) map to the canonical QUDT `unit:` IRI and are validated against the
  vendored `ontology/qudt-units.json` allowlist authored by chunk 2; an unmappable or
  out-of-allowlist unit rejects the relation.
- **Text-derived measurements written to both stores**: each validated measurement becomes
  a `msr:PropertyMeasurement` in `urn:msr:data` (`msr:ofSalt`, `msr:forProperty`,
  `msr:hasUnit`, `msr:equationForm`, `msr:validTempMin`/`Max`, `msr:dataLocator`,
  `prov:wasDerivedFrom`, `prov:wasGeneratedBy` the stable extraction activity, and
  **`msr:citedIn` the source document** — the citation edge both the `provenance-model` and
  `analysis-agent` main specs explicitly defer to this chunk) plus one `measurement_value`
  row with `source='document'`, `doc_id` set, coefficients `c0..c4` from the extracted
  equation/point, and the shared locator `doc/{report#}/{property}#{slug}`. Equation forms
  (Linear / Polynomial / Arrhenius / DiscretePoint) map to the seed `msr:EquationForm`
  individuals; coefficients live only in SQLite.
- **Reintroduced role/reactor TBox + edges**: `ground-demo-in-real-docs` removed the
  `msr:hasRole`/`msr:usedIn` OWL layer and deferred its return here, so chunk 7 re-adds it to
  the seed ontology — `msr:SaltRole` + the closed `FuelSalt`/`CoolantSalt`/`FlushSalt`
  individuals + `msr:hasRole`, and `msr:MoltenSaltReactor` + `msr:usedIn` — and populates it
  from real text: a validated salt↔role edge (`msr:hasRole`) links to one of the reintroduced
  seed role individuals; a salt↔reactor edge (`msr:usedIn`) **mints** its
  `msr:MoltenSaltReactor` individual from a chunk-6-linked reactor mention (deterministic IRI,
  `rdfs:label`, grounding concept, and provenance), so no reactor is hand-curated.
- **Generation provenance on every asserted fact**: satisfying the merged `provenance-model`
  spec, the `extract` run reuses the existing pipeline helper `provenance.py` so each written
  measurement, minted reactor, and edge-reification node carries `prov:wasGeneratedBy` the
  stable `msrd:activity-extraction` in `urn:msr:data` and a per-run generation edge into the
  append-only `urn:msr:provenance` graph — identical in shape to how chunk 6 provenances its
  mentions and documents.
- **Queryable extraction confidence + rationale**: each extracted relation carries an
  extraction confidence and a short rationale, persisted **queryably in the graph** via a
  small additive TBox (`msr:extractionConfidence`, `msr:extractionRationale`) — directly on a
  written text-derived measurement, and on a written role/reactor edge via an `rdf:Statement`
  reification of the edge (the direct edge is kept unchanged for the agent). A per-document
  `relations.jsonl` trace artifact additionally records every proposed relation (written /
  rejected / skipped) with its confidence, rationale, and disposition, and a configurable
  confidence threshold drops low-confidence relations rather than writing them.
- **Deterministic, idempotent writes**: measurement IRIs are minted deterministically from
  the locator (no blank nodes); triples are additive `INSERT DATA` via chunk 5's Python
  SPARQL-UPDATE helper; SQLite rows upsert on the `locator` primary key. Re-running the
  extraction leaves both stores unchanged.
- **`extract` run**: a new one-shot extraction subcommand + `make extract` target, ordered
  after `make link`, that reads the curated `segments.jsonl` + `mentions.jsonl`, runs the
  extractor, and writes both stores; it reuses chunk 6's graph reader and cached KG-schema
  prompt builder rather than re-deriving them.

## Capabilities

### New Capabilities

- `relation-extraction`: the DeepSeek V4 Flash relation extractor over chunk-6
  linked-mention sentences — extracting all relations in a sentence (zero or more), each with
  an extraction confidence + rationale, schema-constrained JSON validated to reference only
  existing salt / property / reactor / role IRIs (else rejected); a configurable confidence
  threshold; a `relations.jsonl` trace artifact of every proposed relation and disposition;
  injected client, stubbed in tests; reuses the chunk-6 cached KG-schema prompt.
- `unit-qudt-mapping`: map an extracted unit surface form to the canonical QUDT `unit:`
  IRI and validate it against the vendored `ontology/qudt-units.json` allowlist; reject an
  unmappable or out-of-allowlist unit.
- `text-measurement-writing`: write a validated text-derived measurement to both stores —
  a `msr:PropertyMeasurement` (with `msr:citedIn`, generation provenance `prov:wasDerivedFrom`
  + `prov:wasGeneratedBy`, and queryable `msr:extractionConfidence` + `msr:extractionRationale`)
  in `urn:msr:data` and a `measurement_value` row (`source='document'`, coefficients, shared
  locator) in SQLite — with deterministic IRIs and idempotency across both stores, honoring the
  SQLite runtime contract from Python; owns the small additive extraction-provenance TBox added
  to the seed ontology and the per-run generation lineage into `urn:msr:provenance` (via the
  reused `provenance.py`).
- `salt-role-reactor-edges`: reintroduce the role/reactor OWL TBox that
  `ground-demo-in-real-docs` removed (`msr:SaltRole` + `FuelSalt`/`CoolantSalt`/`FlushSalt` +
  `msr:hasRole`; `msr:MoltenSaltReactor` + `msr:usedIn`) and write validated edges to
  `urn:msr:data`: `msr:hasRole` to a reintroduced seed role individual (closed set), and
  `msr:usedIn` to a `msr:MoltenSaltReactor` **minted** from a chunk-6-linked reactor mention
  (deterministic IRI + provenance); each text-derived edge carries an `rdf:Statement`
  reification with confidence/rationale + generation provenance; deterministic and idempotent.

### Modified Capabilities

- `measurement-store`: the merged spec requires the **chunk-7 extraction writer** to write
  through the Go `internal/store` helper "so the upsert-by-locator contract and the pinned
  connection settings are enforced in code, not convention." Chunk 7 is Python (the extraction
  container) and cannot link the Go helper across the language boundary, so this change amends
  the requirement: the Python extraction writer SHALL enforce the **identical runtime contract**
  (`journal_mode=DELETE`, non-zero `busy_timeout`, upsert-by-`locator`) via a Python stdlib
  `sqlite3` connection helper (D7). The "write through the Go helper" obligation is scoped to
  the Go writers (the chunk-2 NIST loader); the contract itself is unchanged. No table/schema
  change (new `source='document'` rows only).

Otherwise additive: this change reads through the existing `core-dataset-access` contract,
consumes the chunk-6 mentions and prompt builder and the chunk-2 salt catalog + QUDT
allowlist, reuses the `provenance-model` pipeline provenance helper, and grows the
`container-stack` `extraction` image additively without changing their requirements. (The
role/reactor OWL TBox it re-adds to `ontology/msr.ttl` is the return of a layer
`ground-demo-in-real-docs` explicitly deferred to chunk 7, not a modification of a current
capability's requirements.)

## Impact

- **New code**: relation-extraction modules in `extraction/src/msr_extraction/` (Flash
  relation extractor + validator, unit→QUDT mapper, equation-form/coefficient parser, a
  Python `measurement_value` writer honoring the SQLite runtime contract, a text-measurement
  triple writer, a salt role/reactor edge writer incl. a grounded reactor minter, and an
  `extract` CLI subcommand that also emits the run's provenance) plus a `pytest` suite under
  `extraction/tests/`.
- **Reused (not re-derived)**: chunk 6's Python core-dataset graph reader (known-IRI set),
  its cached KG-schema prompt builder (`kg-schema-prompt`), the pipeline provenance helper
  `provenance.py` (stable + per-run generation lineage), and chunk 5's Python SPARQL-UPDATE
  helper; the chunk-2 vendored QUDT allowlist `ontology/qudt-units.json`.
- **Config**: reuses `DEEPSEEK_BASE_URL`, `LLM_MODEL_EXTRACT` (Flash); the DB path for the
  Python writer. Clients are injected interfaces, stubbed in tests.
- **Make targets**: a `make extract` one-shot Compose run added additively to the root
  `Makefile`, ordered after `make link`.
- **Ontology**: the seed `ontology/msr.ttl` gains two additive TBox blocks, loaded into
  `urn:msr:ontology` via `make load-seed`'s `PUT` (no loader code change): (a) the
  extraction-provenance vocabulary (`msr:extractionConfidence`, `msr:extractionRationale`,
  domain-agnostic so they attach to a measurement or a reified `rdf:Statement` edge), and
  (b) the **reintroduced role/reactor OWL layer** removed by `ground-demo-in-real-docs` and
  deferred here (`msr:SaltRole` + `FuelSalt`/`CoolantSalt`/`FlushSalt` + `msr:hasRole`;
  `msr:MoltenSaltReactor` + `msr:usedIn`). Adding to `msr.ttl` bumps `owl:versionInfo`,
  rebuilding the cached KG-schema prompt. The role/reactor SKOS concepts already remain in
  `vocab.ttl`.
- **Trace artifact**: a per-document `data/corpus/{report#}/relations.jsonl` records every
  proposed relation with confidence, rationale, and disposition (written / rejected /
  skipped).
- **Stores**: `urn:msr:data` gains text-derived `msr:PropertyMeasurement` nodes, minted
  `msr:MoltenSaltReactor` individuals, and role/reactor edges (each edge with an
  `rdf:Statement` reification carrying confidence/rationale) — every one also carrying
  `prov:wasDerivedFrom` + `prov:wasGeneratedBy`; `urn:msr:provenance` gains a per-run
  `prov:Activity` node and one generation edge per asserted fact (append-only);
  `measurement_value` gains `source='document'` rows. SQLite schema unchanged (the
  `uncertainty` column already exists).
- **Depends on**: chunk 2 (`load-nist-structured-data` — the salt catalog, the
  `measurement_value` table, the QUDT allowlist, `PropertyMeasurement` triple shape), chunk 6
  (`ner-entity-linking` — `mentions.jsonl`, the `msr:Mention` triples, the graph reader, the
  KG-schema prompt builder), and the trust trilogy (`ground-demo-in-real-docs` — the removed
  role/reactor layer chunk 7 restores; `provenance-model` + `provenance-run-lineage` — the
  generation-provenance contract and the reused `provenance.py`). **Downstream**: nothing
  consumes chunk 7 except the chunk-4 agent's (unchanged) answer surface and the chunk-10
  demo — it has no dependents, so it may run alongside P5.
