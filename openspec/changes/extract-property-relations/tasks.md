# Tasks: extract-property-relations

## 1. Extraction project setup

- [ ] 1.1 Add relation-extraction modules under `extraction/src/msr_extraction/`: Flash relation extractor + validator, unit→QUDT mapper, equation-form/coefficient parser, Python `measurement_value` writer, text-measurement triple writer, salt role/reactor edge writer, and an `extract` CLI subcommand
- [ ] 1.2 Extend `config.py` additively: add the SQLite DB path and a confidence threshold (following the existing `MSR_*` env-var convention, e.g. `MSR_EXTRACT_CONFIDENCE_THRESHOLD`), and a `relations_path(report)` helper alongside the existing `mentions_path`/`segments_path`; reuse the existing `deepseek_base_url` / `deepseek_api_key` / `llm_model_extract` and `sparql_query_endpoint` / `sparql_update_endpoint`; keep all clients/paths injectable for tests
- [ ] 1.3 Confirm the `extraction/` image still builds (no new heavy dependency beyond the chunk-6 DeepSeek client; stdlib `sqlite3` and `ontology/qudt-units.json` are already present)

## 2. Known schema + prompt reuse

- [ ] 2.1 Reuse and **extend** chunk 6's `graph_reader.py` (`GraphReader`): its merged `read_known_entities()` exposes only concept/class/salt kinds (SKOS concepts, `owl:Class`, `PhysicalProperty`-as-`class`, `MoltenSalt`) — add new accessors for `msr:SaltRole` individuals (`FuelSalt`/`CoolantSalt`/`FlushSalt`) and `msr:MoltenSaltReactor` individuals (e.g. `msrd:MSRE`) plus a `PhysicalProperty`-specific accessor, so the run's known-IRI set covers salts, properties, roles, and reactors keyed by IRI (staging/proposal graphs never read); leave `read_known_entities()` unchanged to preserve chunk 6's NER seeding + byte-stable prompt prefix
- [ ] 2.2 Reuse chunk 6's cached KG-schema prompt builder (`kg-schema-prompt`) as the Flash prefix; do not re-derive the TBox/vocab/salt-catalog serialization

## 3. Relation extraction (`relation-extraction`)

- [ ] 3.1 Select the extraction inputs: curated-document sentences from `segments.jsonl` that carry ≥ 1 chunk-6 `status:"linked"` mention (from `data/corpus/{report#}/mentions.jsonl`), with the linked entities identified for the prompt
- [ ] 3.2 Implement the injected OpenAI-compatible Flash extractor call (JSON output mode) over each selected sentence on top of the cached KG-schema prompt; parse the schema-constrained JSON app-side
- [ ] 3.3 Treat the Flash output as a list of zero or more relations (multiple relations per sentence extracted independently); obtain a per-relation extraction confidence + rationale, and apply the configurable confidence threshold, marking below-threshold relations as skipped
- [ ] 3.4 Validate each proposed relation against the known-IRI set — salt ∈ loaded `MoltenSalt`, property ∈ seed `PhysicalProperty`, role ∈ seed `SaltRole`, reactor ∈ loaded `MoltenSaltReactor` — rejecting any relation naming an unknown referent; drop malformed/schema-violating JSON with no partial write
- [ ] 3.5 Write the `data/corpus/{report#}/relations.jsonl` trace artifact — one record per proposed relation with its confidence, rationale, and disposition (`written`/`rejected`/`skipped` + reason); deterministically regenerated per run (mirroring chunk 6's `mentions.jsonl`)

## 4. Unit → QUDT mapping (`unit-qudt-mapping`)

- [ ] 4.1 Implement the unit-surface-form → canonical QUDT `unit:` IRI mapper driven by the vendored `ontology/qudt-units.json` (e.g. `cP`/`mPa·s`→`unit:MilliPA-SEC`, `g/cm³`→`unit:GM-PER-CentiM3`, `mN/m`→`unit:MilliN-PER-M`, `S/cm`→`unit:S-PER-CentiM`)
- [ ] 4.2 Validate every mapped IRI against the allowlist and reject an unmappable/out-of-allowlist unit; cross-check the unit is dimensionally consistent with the extracted property via the property→canonical-unit map

## 5. Text-measurement writing (`text-measurement-writing`)

- [ ] 5.0 Add the extraction-provenance TBox to `ontology/msr.ttl` — `msr:extractionConfidence` (datatype, `xsd:decimal`) and `msr:extractionRationale` (datatype, `xsd:string`), domain-agnostic (attach to a text-derived `msr:PropertyMeasurement` or a reified role/reactor edge); add the `rdf:` prefix if absent; keep it additive and rdflib-valid; ensure `make load-seed` (re-`PUT` of `urn:msr:ontology`) precedes `make extract`
- [ ] 5.1 Implement the equation-form/coefficient parser: map the extracted correlation to a seed `msr:EquationForm` (`Linear`/`Polynomial2`/`Polynomial3`/`Arrhenius`/`DiscretePoint`) and place coefficients into `c0..c4` (incl. `η = 0.084·exp(4340/T)` → Arrhenius `c0=0.084`, `c1=4340`; single value at T → DiscretePoint with `validTempMin=validTempMax`); reject on a coefficient-count/form mismatch
- [ ] 5.2 Derive the shared locator `doc/{report#}/{property}#{slug}` (canonical salt slug) and the deterministic measurement IRI from it (no blank nodes); ensure the same locator keys both stores
- [ ] 5.3 Implement the text-measurement triple writer: `msr:PropertyMeasurement` with `msr:ofSalt`, `msr:forProperty`, `msr:hasUnit`, `msr:equationForm`, `msr:validTempMin`/`Max`, `msr:dataLocator`, `prov:wasDerivedFrom`, `msr:citedIn`, and the queryable `msr:extractionConfidence` + `msr:extractionRationale` → `urn:msr:data` via additive `INSERT DATA` through the chunk-5 `SparqlClient` (never `PUT`)
- [ ] 5.4 Implement the Python `measurement_value` writer via stdlib `sqlite3` through a connection helper pinning `journal_mode=DELETE` + non-zero `busy_timeout` (no WAL sidecars); insert rows with `source='document'`, `doc_id`, canonical `salt`, `property`, `equation_form`, `t_min`/`t_max`, `uncertainty`, `c0..c4`; upsert on the `locator` primary key
- [ ] 5.5 Skip (and record in the run summary) any measurement whose salt resolved only to a bare concept, never guessing a composition

## 6. Salt role / reactor edges (`salt-role-reactor-edges`)

- [ ] 6.1 Write validated `msrd:{salt} msr:hasRole msr:{Role}` and `msrd:{salt} msr:usedIn msrd:{Reactor}` direct edges to `urn:msr:data` via additive `INSERT DATA`; for a text-derived edge also write a deterministic `rdf:Statement` reification of it (`rdf:subject`/`rdf:predicate`/`rdf:object`) carrying `msr:extractionConfidence` + `msr:extractionRationale` (direct edge preserved unchanged for the agent); no blank nodes
- [ ] 6.2 Reject a role/reactor edge naming an unknown role/reactor individual; ensure re-asserting an existing (incl. seed) edge is a no-op

## 7. `extract` orchestration, wiring & docs

- [ ] 7.1 Implement the `extract` CLI umbrella: load known schema + prompt → select mention-bearing sentences → extract + validate → write measurements (both stores) + role/reactor edges, over the curated set; print a run summary (per doc: sentences seen, relations extracted, measurements/edges written, rejected/skipped counts)
- [ ] 7.2 Add the `make extract` target (`docker compose run --rm extraction extract`, mirroring `link:` — **no** `load-seed` prerequisite; add `extract` to the Makefile `.PHONY` list); update the README bootstrap order to `up → load-nist (runs load-seed) → ingest → link → extract`, with a note to never re-run `load-seed` after data is loaded (it graph-replaces `urn:msr:data`); document the new `source='document'` rows + text-derived `PropertyMeasurement` nodes (with confidence/rationale) + role/reactor edge reifications + the `relations.jsonl` trace artifact

## 8. Tests

- [ ] 8.1 Stubbed-Flash relation-extraction tests over fixture sentences → expected validated relations (salt + property + value + unit, incl. the Arrhenius `η = 0.084·exp(4340/T)` case and a DiscretePoint value-at-T case); relations naming an unknown salt/property/reactor/role IRI or an out-of-allowlist unit are rejected; malformed JSON → dropped, no write
- [ ] 8.2 Sentence-selection tests: only sentences carrying a `status:"linked"` mention are sent to Flash; a mention-free sentence is skipped
- [ ] 8.3 Unit→QUDT mapping table tests (surface form → canonical `unit:` IRI); unmappable/out-of-allowlist rejected; property-vs-unit dimensional-consistency rejection
- [ ] 8.4 Equation-form/coefficient parsing tests: each form → correct `msr:EquationForm` + `c0..c4`; coefficient-count/form mismatch rejected
- [ ] 8.5 Measurement dual-store write tests: a validated measurement → the exact expected `INSERT DATA` triples (deterministic IRI, `msr:citedIn`, no blank nodes) against a fake SPARQL client, and the exact `measurement_value` row (`source='document'`, shared locator, coefficients) against a temp SQLite DB; re-run leaves both unchanged (idempotency); assert no `-wal`/`-shm` sidecar after the write and `journal_mode=delete`
- [ ] 8.6 Role/reactor edge tests: validated statement → expected direct `hasRole`/`usedIn` triple plus an `rdf:Statement` reification carrying queryable `msr:extractionConfidence`/`msr:extractionRationale`; a hand-curated seed edge carries no reification; unknown role/reactor rejected; re-assert (incl. a seed edge) leaves both edge and reification-node counts unchanged
- [ ] 8.7 Core-dataset read guard test: a salt/property present only in `urn:msr:staging` is not in the known-IRI set and is never a valid extraction referent
- [ ] 8.8 Bare-concept skip test: a measurement statement whose salt resolved to a concept (no composition) writes nothing and is recorded as skipped
- [ ] 8.9 Multiple-relations-per-sentence test: a sentence asserting two relations (e.g. a role and a reactor) yields two, each validated and written independently; an empty relation list writes nothing
- [ ] 8.10 Confidence/rationale tests: a written measurement carries `msr:extractionConfidence` + `msr:extractionRationale` queryable in `urn:msr:data` while a NIST measurement carries neither; a written relation is recorded in `relations.jsonl` with confidence + rationale + `disposition:"written"`; a below-threshold relation is `skipped` (nothing written); a validation failure is `rejected` with its reason; the physical `uncertainty` string (when present) lands in the SQLite column, separate from the extraction confidence
- [ ] 8.11 Guarded integration test (opt-in env flag, mirroring chunk 1's `GRAPHDB_REQUIRED`): after seed + catalog + `link` + a real `extract` over ORNL-TM-2316, a known FLiBe viscosity statement becomes a `PropertyMeasurement` with its value in `measurement_value` and `msr:citedIn msrd:ORNL-TM-2316`, the unchanged chunk-4 agent answers a question using it, and a second `extract` run leaves both stores' counts unchanged

## 9. Manual acceptance run

- [ ] 9.1 After a full bootstrap (`make up` → `load-seed` → `load-nist` → `ingest` → `link` → `extract`), do a real end-to-end run over the actual curated documents and manually inspect the output: confirm a known FLiBe viscosity statement in ORNL-TM-2316 became a `PropertyMeasurement` (with `msr:citedIn`) whose value is in `measurement_value` (`source='document'`), spot-check role/reactor edges, verify the chunk-4 agent now answers the text-derived value unchanged, and confirm a second `extract` run adds no duplicates — the change is done only after this manual verification passes, not on green tests alone
