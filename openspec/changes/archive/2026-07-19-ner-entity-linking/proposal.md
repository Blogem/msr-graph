# Proposal: ner-entity-linking

## Why

The structured spine (chunk 2) loads salt individuals into the graph and the corpus (chunk 5) lands OCR-cleaned, segmented text — but nothing yet connects the prose to the schema. The unstructured/evolution track (chunks 7–10) needs text mentions of known MSR entities recognized and **linked** to vocab concepts, ontology classes, and the loaded `MoltenSalt` individuals, with high precision, before any relation extraction or novelty mining can run. This change lands the NER core: a precision-biased, graph-seeded spaCy linker with a bounded fuzzy fallback and a DeepSeek V4 Flash disambiguation backstop, plus the reusable Python KG-schema prompt builder that chunks 7 and 8 depend on. Chunk 6 gates the most downstream work in the plan, so it is staffed first within Phase 3.

## What Changes

- **Graph-seeded spaCy matcher, rebuilt at run start**: an `EntityRuler` + `PhraseMatcher` seeded from the graph on every extraction run — vocab concepts (prefLabels + altLabels + generated surface variants, `attr="LOWER"`) **and the chunk-2 salt catalog** (the loaded `MoltenSalt` individuals). This per-run re-seed is also the mechanism by which approved evolution concepts reach NER — there is no push signal, the next run simply reads the current graph.
- **Python chemical-formula normalizer**: a dedicated parser that maps salt-mention variants (`BeF2-LiF` ≡ `LiF-BeF2`, `LiF·BeF₂`, subscript/spacing forms) to the contract's canonical salt form, so mentions land on the exact loader-minted salt IRIs. Implemented in Python on purpose (the deliberately-duplicated rule) and pinned against the shared `testdata/salt-canonicalization.json` fixture authored by chunk 2 so Go and Python canonicalization cannot drift.
- **Layered, precision-biased linking pipeline** over chunk-5 `segments.jsonl`: expanded exact matching → formula normalizer → a bounded `rapidfuzz` fallback (high threshold, minimum token length), each span resolved to a vocab concept, an ontology class, or a loaded salt individual. Linking precision is the gated metric (≥ 0.90 on a labelled sample); recall is reported but not gated.
- **DeepSeek V4 Flash disambiguation layer**: spans the lexical layers 1–4 cannot settle go to Flash with sentence context on the cached KG-schema prompt. Output is schema-constrained JSON that may only reference an **existing** IRI (validated against the graph, else rejected) or declare the span **novel**. The client is an injected OpenAI-compatible interface — stubbed in every test, never a live model.
- **Python cached KG-schema prompt builder**: the byte-stable, deterministically-ordered serialization of the ontology TBox + SKOS vocab + salt catalog, regenerated only on an `owl:versionInfo` bump (read at run start). This is the Python counterpart to chunk 4's Go builder and is **reused by chunks 7 and 8**.
- **Linked-mention triples to the graph**: deterministic mention IRIs (`msrd:mention-{report#}-{start}-{end}`, no blank nodes) written to `urn:msr:data` via SPARQL UPDATE over HTTP (reusing chunk 5's Python graph-write helper), so re-running the pipeline adds no duplicate mentions.

## Capabilities

### New Capabilities

- `entity-ruler-seeding`: build the spaCy `EntityRuler`/`PhraseMatcher` from the graph at run start — vocab prefLabels + altLabels + generated surface variants (`attr="LOWER"`) plus the chunk-2 salt catalog — so known entities (concepts, classes, loaded salt individuals) are matchable and approved evolution concepts reach NER on the next run with no push signal.
- `salt-formula-normalization`: the Python chemical-formula parser/normalizer that unifies salt-mention variants to the canonical form and maps them to the loader-minted salt IRIs; passes the shared `testdata/salt-canonicalization.json` drift-guard fixture.
- `entity-linking`: the layered, precision-biased matching pipeline over `segments.jsonl` (expanded exact match → formula normalizer → bounded `rapidfuzz` fallback) that resolves spans to vocab concepts / ontology classes / loaded salt individuals at ≥ 0.90 precision on a labelled sample.
- `llm-disambiguation`: the DeepSeek V4 Flash layer for spans layers 1–4 cannot settle — schema-constrained JSON validated to reference only existing IRIs (else rejected) or to declare the span novel; injected client, stubbed in tests.
- `kg-schema-prompt`: the Python cached, byte-stable KG-schema prompt builder (TBox + vocab + salt-catalog serialization; version read at run start), reused by chunks 7 and 8.
- `mention-graph-writing`: write linked-mention triples with deterministic IRIs (`msrd:mention-{report#}-{start}-{end}`, no blank nodes) into `urn:msr:data` via SPARQL UPDATE, idempotent across re-runs.

### Modified Capabilities

None — this change reads through the existing `core-dataset-access` contract, consumes chunk-2 catalog triples and chunk-5 `segments.jsonl` + the Python graph-write helper, and grows the `container-stack` `extraction` image additively without changing their requirements.

## Impact

- **New code**: real NER modules in `extraction/src/msr_extraction/` (graph reader/ruler-seeder, formula normalizer, layered linker, Flash disambiguator + validator, KG-schema prompt builder, mention-triple writer, a `link` CLI subcommand) plus a `pytest` suite under `extraction/tests/`.
- **Dependencies**: `spaCy` (+ its English model) and `rapidfuzz` added to `extraction/pyproject.toml`; an OpenAI-compatible client for DeepSeek. Config `DEEPSEEK_BASE_URL`, `LLM_MODEL_EXTRACT` (Flash). The extraction Dockerfile gains these; clients are injected interfaces stubbed in tests.
- **Make targets**: a `make link` (or extended extraction entry point) one-shot Compose run added additively to the root `Makefile`, ordered after `make ingest` and `make load-nist`.
- **Stores**: `urn:msr:data` gains `msr:Mention` triples linking spans to concepts/classes/salt individuals; no SQLite writes (text-derived values are chunk 7).
- **Shared fixture**: consumes (does not author) `testdata/salt-canonicalization.json` — the Python normalizer must pass every case Go authored.
- **Depends on**: chunk 1 (`bootstrap-graph-infra`), chunk 2 (`load-nist-structured-data` — the salt catalog + the fixture), chunk 5 (`ingest-archive-documents` — `segments.jsonl`, `Document` nodes, the Python SPARQL-UPDATE helper). **Downstream**: produces the mention triples chunks 7 (relations) and 8 (novelty mining) consume, and the KG-schema prompt builder both reuse.
