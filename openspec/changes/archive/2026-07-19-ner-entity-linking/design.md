# Design: ner-entity-linking

## Context

Chunks 1, 2, 3, and 5 are **merged to main and archived**. Chunk 1 (`bootstrap-graph-infra`) shipped the running stores, the seed ontology/vocab/A-Box, the `internal/graph` core-dataset client, and the `extraction/` Python scaffold. Chunk 2 (`load-nist-structured-data`) landed the salt catalog — `MoltenSalt`/`Constituent`/`PropertyMeasurement` individuals in `urn:msr:data`, where the loaded MSRE-coolant FLiBe individual is `msrd:salt-BeF2-LiF-34.0-66.0` (34 mol% BeF2 / 66 mol% LiF, carrying the density measurement) — and authored the shared drift-guard fixture `testdata/salt-canonicalization.json` (now covering fixed-composition **and** isotherm-range cases). Chunk 5 (`ingest-archive-documents`) landed the curated corpus as `data/corpus/{report#}/normalized.txt` + `segments.jsonl` (one JSON object per sentence: `{report, index, text, char_start, char_end}`, offsets absolute into `normalized.txt`), the committed curated-set list `curated.CURATED_REPORTS`, the `Document` provenance nodes (`msrd:{report#}`), and a reusable Python `SparqlClient` (UPDATE-only, in `extraction/src/msr_extraction/sparql.py`) plus the `cli.py` subcommand dispatcher chunk 6 extends.

This change is the NER core (chunk 6). It reads the segmented text and the graph's known entities, links spans with high precision, and writes linked-mention triples back. It is bound by the cross-cutting contracts in `docs/ARCHITECTURE.md` → _Runtime contracts_ / _Matching & OCR robustness_ and `docs/IMPLEMENTATION_PLAN.md` → _Cross-cutting contracts_. Fixed points it must honor:

- **Canonical salt naming** is implemented **twice on purpose** — Go in the loader (chunk 2), Python here — because it is pure string/structure work and duplication beats a cross-language dependency; the shared `testdata/salt-canonicalization.json` fixture is the drift guard both suites must pass.
- **EntityRuler is rebuilt from the graph at the start of every extraction run** — approval doesn't push a refresh signal; the next run simply reads the current (approved) concepts. This per-run re-seed is how the evolution loop reaches NER.
- **Precision-biased, bounded fuzziness** — a fuzzy hit should resolve to an existing concept, not spawn a false novelty candidate; the formula normalizer + expanded exact patterns do most of the work and true fuzzy matching is a bounded fallback.
- **LLM = DeepSeek V4 Flash only**, via an injected OpenAI-compatible client, **stubbed in every test**; schema-constrained output validated against existing IRIs.
- **Cached KG-schema prompt** — the Python byte-stable prompt builder lives here (chunk 6), reused by chunks 7 and 8; regenerated only on an `owl:versionInfo` bump read at run start.
- **Deterministic IRIs, no blank nodes, idempotent re-runs**; Python writes the graph directly via SPARQL UPDATE over the language-neutral GraphDB HTTP endpoint (chunk 5's helper), naming an explicit `GRAPH` target.

## Goals / Non-Goals

**Goals:**

- Rebuild a spaCy `EntityRuler`/`PhraseMatcher` from the graph on each run: vocab prefLabels + altLabels + generated surface variants (`attr="LOWER"`) **and** the chunk-2 salt catalog, so known concepts, classes, and loaded salt individuals are matchable.
- A Python chemical-formula normalizer that unifies salt-mention variants to the canonical form and maps them to the loader-minted salt IRIs; passes the shared fixture.
- A layered, precision-biased linking pipeline over `segments.jsonl` (expanded exact → formula normalizer → bounded `rapidfuzz`), each span resolved to a vocab concept / ontology class / loaded salt individual, with the resolving layer recorded.
- A DeepSeek V4 Flash disambiguation layer for spans the lexical layers can't settle — validated existing-IRI-only or novel; injected, stubbed.
- A Python cached, byte-stable KG-schema prompt builder (TBox + vocab + salt catalog), version-gated, reusable by chunks 7 and 8.
- Linked-mention triples with deterministic IRIs written to `urn:msr:data`, idempotently; the full per-span classification (linked + novel/unresolved) emitted as the mention/miss artifact chunks 7 and 8 consume.
- A labelled-sample precision harness gating linking precision ≥ 0.90 on ≥ 50 ORNL-TM-2316 mentions (recall reported, not gated).

**Non-Goals:**

- **No relation extraction** (salt↔property↔value, salt↔reactor↔role), no `PropertyMeasurement` from text, and **no SQLite writes** — all chunk 7. _Deferred, not dropped:_ the split keeps chunk 6's deterministic, precision-gated linking (the M3 ≥ 0.90 criterion) independently verifiable, separate from chunk 7's different risk profile (LLM relation extraction with schema/unit validation and SQLite writes). Nothing is lost — the mention triples are exactly chunk 7's input; the only consequence of stopping here is that text-derived _values_ aren't answerable by the agent until chunk 7 consumes these mentions. Per the plan's granularity note, 6 + 7 may be merged into one "NER pipeline" change if fewer, larger changes are preferred.
- **No novelty mining, salience scoring, triage, or `ChangeProposal`/staging writes** — chunk 8. Chunk 6 only _emits_ the novel/unresolved spans (the "miss output") as an artifact; it never writes to `urn:msr:staging` or `urn:msr:proposal/{id}`.
- **No back-population** of parked mentions into measurements — that is a chunk 7/9 re-run concern.
- **No Go changes** — the Go `internal/graph` client is the core read/enforcement layer; chunk 6 is Python and writes the graph directly over HTTP.
- **No changes to `testdata/salt-canonicalization.json`** — chunk 2 authors it; chunk 6 must pass it unchanged.
- **No embedding-similarity matcher** — the architecture supersedes that stretch idea with the Flash layer.
- **No re-OCR or document normalization** — chunk 5 owns the OCR pre-pass; chunk 6 consumes `normalized.txt`/`segments.jsonl` as-is.

## Decisions

### D1 — One-shot `link` stage; matcher rebuilt from the **core dataset** at run start

The extraction package gains a `link` subcommand (a one-shot Compose run, sibling to chunk 5's `ingest`) that, per run: reads the current vocab + ontology + salt catalog from the graph, builds the matcher, links every curated document's segments, and writes mentions. There is no long-running NER service and no push signal on approval — re-seeding from the graph each run **is** the mechanism by which approved evolution concepts (chunks 8→9) reach NER.

- **Read the core dataset only.** The seed must include _approved_ concepts and salt individuals but **must not** include pending proposals sitting in `urn:msr:staging` / `urn:msr:proposal/{id}` — otherwise NER would link mentions to unreviewed concepts. GraphDB's no-dataset default is union-of-all-graphs, so the Python graph **reader** replicates the core-dataset contract: it injects `FROM <urn:msr:ontology> FROM <urn:msr:data> FROM <urn:msr:vocab>` (equivalently the protocol `default-graph-uri`/`named-graph-uri` parameters) on every read, exactly as the Go `internal/graph` client does. This mirrors chunk 1's enforcement on the Python side rather than sharing the Go client (the language boundary keeps Python self-contained; the endpoint is language-neutral). The merged chunk-5 `SparqlClient` is **UPDATE-only** (POSTs to the `/statements` endpoint), so this read client is genuinely new work — it targets the repository query endpoint (`{graphdb_url}/repositories/{repo}`) with the three core graphs as dataset parameters.
- _Alternative — read via a Go helper shelled out from Python:_ rejected; it blurs the language boundary for no gain when a three-line `FROM` injection in the Python reader is equivalent and testable.

### D2 — Layered, precision-biased matcher; the resolving layer is recorded per span

Matching is the architecture's layered scheme, biased toward linking to a known concept. Layer 1 (OCR normalization) is **chunk 5's** pre-pass (already applied to `normalized.txt`); chunk 6 owns layers 2–5 over the segmented text:

2. **Expanded exact matching** — vocab altLabels + generated variants (hyphen/no-hyphen, spacing, case via `attr="LOWER"`) and the salt catalog's canonical labels fed into spaCy `PhraseMatcher`/`EntityRuler`. Most "fuzziness" becomes many cheap exact patterns.
3. **Chemical-formula normalizer** (D3) — salts get a structural parse, not fuzzy matching.
4. **Bounded `rapidfuzz` fallback** (D4) — the long tail only.
5. **Flash disambiguation** (D5) — spans still unresolved after 2–4.

Each recognized span records which layer resolved it and the target's kind (concept / class / salt individual) — surfaced in the mention artifact and used by the precision harness (D9) to diagnose false links per layer. Pattern-variant generation is a pure, tested function so the exact-match surface is reproducible.

### D3 — Python chemical-formula normalizer: structural, and pinned to the shared fixture

A dedicated parser splits a salt mention (`LiF-BeF2`, `BeF2-LiF`, `LiF·BeF₂`, `2LiF-BeF2`, spacing/subscript variants) into (compound, fraction) structure and canonicalizes it identically to chunk 2's Go rule — components byte-wise alphabetized, composition values reordered in lockstep, one-decimal mole % — then maps the canonical string to the loader-minted salt IRI (`msrd:salt-{formula}-{composition}`). Because the IRI-minting rule is identical, a text mention and the NIST row meet at exactly one IRI.

- **The drift guard is the contract.** The Python normalizer's pytest suite loads `testdata/salt-canonicalization.json` and must pass **every** case chunk 2 authored — which the merged fixture expanded to include both fixed-composition cases (`is_range:false`) and isotherm/composition-range cases (`is_range:true`, e.g. `KF-ZrF4 | ZrF4 0.0-33.3`), so the Python normalizer implements range canonicalization too, not only fixed mole-%. Chemistry has structure; the normalizer uses it rather than fuzzy string matching, which keeps salt linking exact.
- _Composition without an explicit mole %:_ a bare formula mention (`LiF-BeF2` with no composition in the sentence) links to the salt **concept**/compound family (e.g. `voc:flibe` for FLiBe) rather than a specific composed individual; a mention carrying a composition resolves to the specific `msrd:salt-…` individual. This keeps precision high — the pipeline never guesses a composition.
- _Why duplicate the rule in Python:_ per the contract it is pure string/structure work; a cross-language runtime dependency (shelling to Go, or an RPC) would be heavier and more fragile than one shared fixture both suites pass.

### D4 — Bounded `rapidfuzz` fallback

For OCR-mangled multi-word terms that survive normalization, a `rapidfuzz` pass with a **high threshold** (~90) and a **minimum token length** matches against the same known-label set. It only ever _links to an existing_ label — it never creates a novelty candidate — so an over-eager fuzzy hit costs precision on linking, not queue pollution. The threshold is the one build-time tuning knob (see Open Questions); it is a config value pinned by tests, not hardcoded magic.

### D5 — Flash disambiguation: schema-constrained, validated, existing-IRI-or-novel

Spans unresolved after layers 2–4 go to DeepSeek V4 Flash with their sentence context on top of the cached KG-schema prompt (D6). The client is an **injected OpenAI-compatible interface** (`DEEPSEEK_BASE_URL`, `LLM_MODEL_EXTRACT`, pinned to `deepseek-v4-flash`); **every test uses a stub**. The call uses DeepSeek's **JSON output mode** — `response_format={"type":"json_object"}`, with the word `json` and a shape example in the prompt — which _guarantees syntactically valid JSON_ but, unlike Gemini/OpenAI strict schemas, does **not** enforce field-level structure (DeepSeek strict JSON-Schema exists only in its beta tool-calling path, for function arguments, not the final message). The layer therefore always validates the parsed object app-side (shape check + the known-IRI check below), so correctness never depends on the model honoring a schema. Flash returns JSON that either:

- links the span to an **existing** IRI — validated against the run's known-IRI set (the same set that seeded the matcher); an IRI not in the set is **rejected** (the span falls through to novel), so Flash can only map _to_ known entities, never invent them; or
- declares the span **novel** → recorded in the miss artifact for chunk 8, not written as a link.

- _Why validate rather than trust:_ the "LLM-asserted, reviewer-verified" principle — the model's job is disambiguation within the known schema; anything outside it is a candidate for the human-reviewed evolution loop, not an auto-added link. Malformed JSON or a schema violation is treated as "unresolved/novel," never a silent link.

### D6 — Python cached KG-schema prompt builder (owned here, reused by 7 and 8)

A deterministic, byte-stable serialization of the ontology TBox + SKOS vocab + salt catalog (canonical ordering, stable formatting) forms the cache-friendly prompt prefix for every Flash call. It is rebuilt only when `owl:versionInfo` (one cheap SELECT at run start) differs from the cached value — invalidating the cache exactly when the schema changes (approvals, restores). The builder lives in `extraction/` and is imported by chunks 7 and 8; it need not be byte-identical to chunk 4's Go builder, only stable within itself (each side caches its own prefix). Instance data (mentions, measurements) stays out of the prompt — it reaches the model only as per-span context, keeping the prefix small and stable.

### D7 — Mention output: linked triples to the graph, full classification to a JSONL artifact

Two outputs, one per consumer:

- **Graph (chunks 7 + 8 read via SPARQL):** each linked span becomes an `msr:Mention` individual in `urn:msr:data` with a deterministic IRI `msrd:mention-{report#}-{start}-{end}` (offsets into `normalized.txt`, matching chunk 5's segment offsets), no blank nodes. Written via chunk 5's `SparqlClient.update` (`extraction/src/msr_extraction/sparql.py`) as additive `INSERT DATA { GRAPH <urn:msr:data> { … } }` — re-asserting the same mention is a set-semantics no-op, so re-running adds no duplicates.
- **Artifact (the mention/miss output):** `data/corpus/{report#}/mentions.jsonl` — one record per recognized span: `{report, seg_index, char_start, char_end, surface_form, status: "linked"|"novel", target_iri, target_kind, layer, score}`. `status:"novel"` records **are** the miss output chunk 8's novelty miner consumes; `status:"linked"` records mirror the graph triples for chunk 7's convenience. The artifact is regenerated wholesale per run (deterministic), so it is idempotent too.

### D8 — A minimal mention TBox added to the seed ontology

The seed T-Box has no mention/annotation vocabulary, but linked mentions need one. Chunk 6 adds a small, self-contained mention schema to **`ontology/msr.ttl`** (loaded into `urn:msr:ontology` by the existing `make load-seed` graph-replace `PUT`):

```turtle
msr:Mention     a owl:Class ; rdfs:comment "A text span in a Document linked to a known entity." .
msr:linksTo     a owl:ObjectProperty ; rdfs:domain msr:Mention .   # → concept / class / individual
msr:inDocument  a owl:ObjectProperty ; rdfs:domain msr:Mention ; rdfs:range msr:Document .
msr:surfaceForm a owl:DatatypeProperty ; rdfs:domain msr:Mention ; rdfs:range xsd:string .
msr:startOffset a owl:DatatypeProperty ; rdfs:domain msr:Mention ; rdfs:range xsd:integer .
msr:endOffset   a owl:DatatypeProperty ; rdfs:domain msr:Mention ; rdfs:range xsd:integer .
```

- _Why the ontology, not staging?_ This is **pipeline infrastructure schema**, not domain discovery — it is not a reviewable evolution candidate, so it belongs in the seed T-Box loaded up front, exactly like chunk 5 relied on `msr:Document`/`dcterms:`/`prov:` pre-existing. The mention _instances_ (ABox) are written by the Python run to `urn:msr:data`; the _schema_ (TBox) rides the seed file loaded by the Go loader — clean TBox/ABox and Go/Python separation.
- _Ordering:_ the `msr.ttl` edit must be loaded (`make load-seed`) before a `make link` run; documented in the bootstrap order. Exact predicate names above are the design intent and confirmed against the IRI-pattern contract (`msrd:mention-{report#}-{start}-{end}`); minor naming is settled at implementation and reflected in the spec.

### D9 — Labelled-sample precision harness

A committed gold fixture labels ≥ 50 mentions from ORNL-TM-2316 (surface span → expected target IRI, or "no link"). The harness runs the full pipeline (with a **stubbed** Flash for determinism) over those sentences and computes **precision = correct links / total links emitted**; the suite fails if precision < 0.90. **Recall** (labelled mentions found) is computed and reported but does not gate — the design is deliberately precision-biased. The fixture doubles as regression protection for the layered matcher.

### D10 — Test strategy

Hermetic pytest, no live model and (for units) no GraphDB:

- **Formula normalizer** — the shared `testdata/salt-canonicalization.json` (every case) plus hyphen/order/`·`/subscript variant cases → one canonical form and the correct salt IRI.
- **Pattern-variant generation** — a label → its expected generated surface variants.
- **Matcher/linker** — fixture sentences → expected spans and targets (concept / class / salt individual), incl. `BeF2-LiF ≡ LiF-BeF2` unification and the bare-formula-vs-composed-individual rule (D3).
- **Stubbed-Flash disambiguation** — accept on a valid IRI, **reject** on an unknown IRI (→ novel), and the novel-span path; malformed JSON → unresolved.
- **KG-schema prompt** — same graph state → byte-identical prefix; a bumped `owl:versionInfo` → rebuilt prefix.
- **Mention emission** — a fixed linked span → the exact expected `INSERT DATA` triples (deterministic IRI, no blank nodes) against a fake SPARQL client; re-run yields identical triples (idempotency).
- **Precision harness** (D9) — the labelled ORNL-TM-2316 sample, precision ≥ 0.90 gate.
- **Core-dataset read guard** — the Python reader injects the three core `FROM` graphs; a concept present only in `urn:msr:staging` does **not** seed the matcher.
- **Guarded integration** (opt-in env flag, mirroring chunk 1's `GRAPHDB_REQUIRED`): after seed + catalog + a real `link` run, the ORNL-TM-2316 anchor mentions (`LiF-BeF2`, `FLiBe`, `viscosity`, `MSRE`) resolve to the correct IRIs, the `LiF-BeF2` mention resolves to the loaded salt individual, and a second run leaves `urn:msr:data` mention-triple counts unchanged.
- **Manual acceptance run** — beyond the automated suite, a real end-to-end `link` run over the actual curated documents with human inspection of the emitted mentions is an explicit task (see tasks §11), so the change isn't considered done on green tests alone.

## Risks / Trade-offs

- **Over-fuzzy matching pollutes both the graph and (via chunk 8) the novelty queue** → the formula normalizer + expanded exact patterns do most of the work; `rapidfuzz` is bounded (high threshold, min token length) and only links to existing labels; precision is the gated metric.
- **Go/Python canonicalization drift** → the shared `testdata/salt-canonicalization.json` fixture both suites must pass; chunk 6 consumes it unchanged.
- **NER seeding from unapproved concepts** would leak staging into linked data → the Python reader injects the three core `FROM` clauses (D1), pinned by a test; staging-only concepts never seed the matcher.
- **Flash hallucinates an IRI** → schema-constrained output is validated against the known-IRI set and rejected on a miss (D5); the model can only map to known entities, never mint them; malformed output is "unresolved," never a silent link.
- **Precision gate flakiness from a live model** → Flash is stubbed in the harness and all unit tests; the ≥ 0.90 gate runs deterministically.
- **Editing the chunk-1 seed `ontology/msr.ttl`** (D8) touches a foundational file → the addition is additive and self-contained (a class + five predicates), loaded by the existing idempotent graph-replace `PUT`; no loader code change, and re-running `load-seed` is a no-op on the rest.
- **Mention offsets defined against `normalized.txt`** (chunk 5's artifact) → offsets are consistent with `segments.jsonl` by construction; provenance is document-granular per the chunk-5 contract (no raw-OCR offset map), which is accepted for the POC.
- **spaCy model download weight in the extraction image** → the image already exists (chunk 1) and is network-enabled; the model is pinned and installed at build time, not at run time.

## Migration Plan

Additive on top of chunks 1, 2, and 5. Bootstrap order becomes `make up` → `make load-seed` (now including the mention TBox) → `make load-nist` → `make ingest` → `make link` → `make test`. The `ontology/msr.ttl` mention-TBox edit is picked up on the next `make load-seed` (idempotent `PUT`). Rollback: delete the `msr:Mention` triples from `urn:msr:data` (or `make load-seed` re-`PUT`s `urn:msr:data`… note it does not, since the seed A-Box is `example-flibe.ttl` — mentions are removed by a targeted `DELETE WHERE { GRAPH <urn:msr:data> { ?m a msr:Mention … } }` or a full `down -v` + re-bootstrap) and remove `data/corpus/{report#}/mentions.jsonl`. Everything is re-creatable from the vendored inputs and the graph. Root `Makefile` gains the `link` target additively per the parallel-execution contract; the `extraction` image gains spaCy + `rapidfuzz` + the DeepSeek client.

## Open Questions

- **Fuzziness threshold** (the plan's noted _Open tuning_) — the `rapidfuzz` cutoff (~90) and minimum token length are build-time knobs; start conservative (precision-biased) and tune against the labelled sample. Pinned by config + tests either way.- **spaCy pipeline shape** — `EntityRuler` alone vs. `EntityRuler` + a blank/statistical model for span candidates; for the curated ~12 docs a rules-first pipeline is expected to suffice, confirmed against the precision harness at implementation.- **Exact mention predicate names** (D8) — the class + five predicates are the design intent; final spellings are settled when `ontology/msr.ttl` is edited and reflected in the spec/tests. Non-blocking.