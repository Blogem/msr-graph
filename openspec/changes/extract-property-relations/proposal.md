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
  `prov:wasDerivedFrom`, and **`msr:citedIn` the source document**) plus one
  `measurement_value` row with `source='document'`, `doc_id` set, coefficients `c0..c4`
  from the extracted equation/point, and the shared locator `doc/{report#}/{property}#{slug}`.
  Equation forms (Linear / Polynomial / Arrhenius / DiscretePoint) map to the seed
  `msr:EquationForm` individuals; coefficients live only in SQLite.
- **Salt role / reactor edges**: validated salt↔role (`msr:hasRole`) and salt↔reactor
  (`msr:usedIn`) statements are written to `urn:msr:data`, linking only to the seed
  `msr:SaltRole` and `msr:MoltenSaltReactor` individuals.
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
  a `msr:PropertyMeasurement` (with `msr:citedIn`, and queryable `msr:extractionConfidence`
  + `msr:extractionRationale`) in `urn:msr:data` and a `measurement_value` row
  (`source='document'`, coefficients, shared locator) in SQLite — with deterministic IRIs
  and idempotency across both stores, honoring the SQLite runtime contract from Python; owns
  the small additive extraction-provenance TBox added to the seed ontology.
- `salt-role-reactor-edges`: write validated salt↔role (`msr:hasRole`) and salt↔reactor
  (`msr:usedIn`) edges to `urn:msr:data`, linking only to seed role/reactor individuals;
  deterministic and idempotent.

### Modified Capabilities

None — this change reads through the existing `core-dataset-access` contract, consumes the
chunk-6 mentions and prompt builder and the chunk-2 salt catalog + QUDT allowlist, extends
the `measurement-store` table additively (new `source='document'` rows, no schema change),
and grows the `container-stack` `extraction` image additively without changing their
requirements.

## Impact

- **New code**: relation-extraction modules in `extraction/src/msr_extraction/` (Flash
  relation extractor + validator, unit→QUDT mapper, equation-form/coefficient parser, a
  Python `measurement_value` writer honoring the SQLite runtime contract, a text-measurement
  triple writer, a salt role/reactor edge writer, and an `extract` CLI subcommand) plus a
  `pytest` suite under `extraction/tests/`.
- **Reused (not re-derived)**: chunk 6's Python core-dataset graph reader (known-IRI set),
  its cached KG-schema prompt builder (`kg-schema-prompt`), and chunk 5's Python
  SPARQL-UPDATE helper; the chunk-2 vendored QUDT allowlist `ontology/qudt-units.json`.
- **Config**: reuses `DEEPSEEK_BASE_URL`, `LLM_MODEL_EXTRACT` (Flash); the DB path for the
  Python writer. Clients are injected interfaces, stubbed in tests.
- **Make targets**: a `make extract` one-shot Compose run added additively to the root
  `Makefile`, ordered after `make link`.
- **Ontology**: the seed `ontology/msr.ttl` gains a small additive extraction-provenance
  TBox (`msr:extractionConfidence`, `msr:extractionRationale`, domain-agnostic so they attach
  to a measurement or a reified `rdf:Statement` edge), loaded via `make load-seed`'s
  graph-replace `PUT` exactly like chunk 6's mention TBox — no loader code change.
- **Trace artifact**: a per-document `data/corpus/{report#}/relations.jsonl` records every
  proposed relation with confidence, rationale, and disposition (written / rejected /
  skipped).
- **Stores**: `urn:msr:data` gains text-derived `msr:PropertyMeasurement` nodes (with
  extraction confidence/rationale) + role / reactor edges (each with an `rdf:Statement`
  reification carrying its confidence/rationale); `measurement_value` gains `source='document'`
  rows. SQLite schema unchanged (the `uncertainty` column already exists).
- **Depends on**: chunk 2 (`load-nist-structured-data` — the salt catalog, the
  `measurement_value` table, the QUDT allowlist, `PropertyMeasurement` triple shape) and
  chunk 6 (`ner-entity-linking` — `mentions.jsonl`, the `msr:Mention` triples, the graph
  reader, the KG-schema prompt builder). **Downstream**: nothing consumes chunk 7 except
  the chunk-4 agent's (unchanged) answer surface and the chunk-10 demo — it has no
  dependents, so it may run alongside P5.
