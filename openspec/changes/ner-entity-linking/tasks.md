# Tasks: ner-entity-linking

## 1. Extraction project setup

- [x] 1.1 Grow the `extraction/` package with NER modules under `extraction/src/msr_extraction/`: graph reader/ruler-seeder, formula normalizer, layered linker, Flash disambiguator + validator, KG-schema prompt builder, mention-triple writer, and a `link` CLI subcommand
- [x] 1.2 Add runtime dependencies to `pyproject.toml` (`spaCy` + its pinned English model, `rapidfuzz`, an OpenAI-compatible client for DeepSeek); pin versions
- [x] 1.3 Extend the config module with `DEEPSEEK_BASE_URL`, `LLM_MODEL_EXTRACT`, the fuzzy threshold + min-token-length, and corpus paths (injectable for tests)
- [x] 1.4 Extend the `extraction/` Dockerfile to install spaCy + model + `rapidfuzz`; confirm the image still builds

## 2. Mention vocabulary in the seed ontology (`mention-graph-writing`)

- [x] 2.1 Add the mention TBox to `ontology/msr.ttl` — `msr:Mention` class plus `msr:linksTo`, `msr:inDocument` (range `msr:Document`), `msr:surfaceForm`, `msr:startOffset`, `msr:endOffset`; keep it additive and rdflib-valid
- [x] 2.2 Update the README/bootstrap order so `make load-seed` (re-`PUT` of `urn:msr:ontology`) precedes `make link`

## 3. Graph reader & matcher seeding (`entity-ruler-seeding`)

- [x] 3.1 Implement a Python graph reader that injects the three core `FROM` graphs (`urn:msr:ontology`, `urn:msr:data`, `urn:msr:vocab`) on every read, mirroring the core-dataset-access contract, so staging/proposal graphs are never read
- [x] 3.2 Read vocab concepts (prefLabels + altLabels), ontology classes/properties, and the chunk-2 salt catalog (`MoltenSalt` individuals + canonical labels/IRIs) into a known-entity set keyed by target IRI
- [x] 3.3 Implement pure, deterministic pattern-variant generation (hyphen/no-hyphen, spacing, `attr="LOWER"` case) per label
- [x] 3.4 Build the spaCy `EntityRuler`/`PhraseMatcher` from the known-entity set at run start (rebuilt every run, no persisted pattern file)

## 4. Salt formula normalizer (`salt-formula-normalization`)

- [x] 4.1 Implement the Python formula parser/normalizer: parse mention → (compound, fraction) structure; byte-wise alphabetize, lockstep-reorder composition, one-decimal mole % → canonical string (identical rule to chunk 2's Go)
- [x] 4.2 Map a composed canonical form to the loader-minted salt IRI (`msrd:salt-{formula}-{composition}`); resolve a bare-formula mention to the salt concept/compound family (never fabricate a composition)
- [x] 4.3 Wire the normalizer in as matching layer 3 (salt spans), unifying order/`·`/subscript/spacing variants

## 5. Layered linking pipeline (`entity-linking`)

- [x] 5.1 Implement the linker over `data/corpus/{report#}/segments.jsonl`: expanded exact match (layer 2) → formula normalizer (layer 3) → bounded `rapidfuzz` fallback (layer 4); record resolving layer, target IRI, and target kind per span
- [x] 5.2 Implement the bounded `rapidfuzz` fallback (configurable threshold + min token length; links only to existing labels, never spawns a novelty candidate)
- [x] 5.3 Emit `data/corpus/{report#}/mentions.jsonl` — one record per span `{report, seg_index, char_start, char_end, surface_form, status, target_iri, target_kind, layer, score}`; deterministic regeneration per run

## 6. Flash disambiguation (`llm-disambiguation`)

- [x] 6.1 Implement the injected OpenAI-compatible Flash client wrapper (`DEEPSEEK_BASE_URL`, `LLM_MODEL_EXTRACT`); interface stubbed in tests
- [x] 6.2 Send only layers-2–4-unresolved spans to Flash with sentence context + the cached KG-schema prompt; parse schema-constrained JSON
- [x] 6.3 Validate returned link IRIs against the run's known-IRI set — accept if present, reject (→ novel) if absent; treat novel declarations and malformed/schema-violating output as unresolved/novel (never a silent link)

## 7. KG-schema prompt builder (`kg-schema-prompt`)

- [x] 7.1 Implement the byte-stable, deterministically-ordered serialization of TBox + vocab + salt catalog (excluding instance data)
- [x] 7.2 Read `owl:versionInfo` at run start; cache the prefix and rebuild only on a version change; expose the builder as an importable component for chunks 7 and 8

## 8. Mention graph writer (`mention-graph-writing`)

- [x] 8.1 Emit each linked span as `msrd:mention-{report#}-{start}-{end} a msr:Mention` with `msr:linksTo`, `msr:inDocument`, `msr:surfaceForm`, `msr:startOffset`, `msr:endOffset`; deterministic IRIs, no blank nodes
- [x] 8.2 Write mention triples to `urn:msr:data` via additive `INSERT DATA` through the chunk-5 Python SPARQL-UPDATE helper (never `PutGraph`); ensure re-run leaves the mention-triple count unchanged

## 9. `link` orchestration, wiring & docs

- [x] 9.1 Implement the `link` CLI umbrella: build prompt → seed matcher → link segments → disambiguate → write mentions + `mentions.jsonl`, over the curated set; print a run summary (per doc: spans, linked, novel, per-layer counts)
- [x] 9.2 Add the `make link` target (one-shot Compose run of the extraction container invoking `link`, ordered after `load-nist` + `ingest`); update the README bootstrap order and the `data/corpus/{report#}/mentions.jsonl` layout note

## 10. Tests

- [x] 10.1 Formula-normalizer tests driven by the shared `testdata/salt-canonicalization.json` (Python must pass every case) plus order/`·`/subscript/spacing variant cases → one canonical form + correct salt IRI; bare-formula-vs-composed-individual rule
- [x] 10.2 Pattern-variant generation tests (label → expected generated surface variants)
- [x] 10.3 Matcher/linker tests on fixture sentences → expected spans and targets (concept / class / salt individual), incl. `BeF2-LiF ≡ LiF-BeF2` unification; bounded-fuzzy accept-above / no-link-below-threshold cases
- [x] 10.4 Core-dataset read guard test: a concept present only in `urn:msr:staging` does not seed the matcher; an approved concept does
- [x] 10.5 Stubbed-Flash disambiguation tests: accept on valid IRI, reject on unknown IRI (→ novel), novel-span path, and malformed-JSON → unresolved
- [x] 10.6 KG-schema prompt tests: same graph state → byte-identical prefix; bumped `owl:versionInfo` → rebuilt prefix; instance data excluded
- [x] 10.7 Mention-emission tests: a fixed linked span → the exact expected `INSERT DATA` triples (deterministic IRI, no blank nodes) against a fake SPARQL client; idempotent-shape re-run
- [x] 10.8 Labelled-sample precision harness: committed gold fixture of ≥ 50 ORNL-TM-2316 mentions → precision ≥ 0.90 gate (stubbed Flash); recall computed and reported, not gated
- [x] 10.9 Guarded integration test (opt-in env flag, mirroring chunk 1's `GRAPHDB_REQUIRED`): after seed + catalog + a real `link` run, `LiF-BeF2`/`FLiBe`/`viscosity`/`MSRE` resolve to correct IRIs, the `LiF-BeF2` mention resolves to the loaded salt individual, and a second run leaves the `urn:msr:data` mention-triple count unchanged

## 11. Manual acceptance run

- [ ] 11.1 After a full bootstrap (`make up` → `load-seed` → `load-nist` → `ingest` → `link`), do a real end-to-end run over the actual curated documents and manually inspect the output: confirm the ORNL-TM-2316 anchors link correctly (`LiF-BeF2` → the loaded salt individual, `FLiBe`, `viscosity`, `MSRE`), spot-check a sample of `linked` vs `novel` records in `data/corpus/{report#}/mentions.jsonl` and the `msr:Mention` triples in `urn:msr:data`, and record observations (precision sanity-check, any systematic mislinks) — the change is done only after this manual verification passes, not on green tests alone
