# MSR KG POC — Implementation Breakdown (OpenSpec chunks)

Each chunk below is sized to become **one OpenSpec change** (problem → design → tasks).
Feed them to OpenSpec one at a time; they're ordered by dependency. Each lists a goal,
scope, dependencies, and concrete acceptance criteria (the seed for the change's test
section). Grounded in `docs/ARCHITECTURE.md`.

## Summary

| # | Change (suggested id) | Track | Tech | Depends on |
|---|-----------------------|-------|------|-----------|
| 1 | `bootstrap-graph-infra` | foundation | Docker, Go, Python | — |
| 2 | `load-nist-structured-data` | structured | Go, SQLite | 1 |
| 3 | `grounded-analysis-agent` | structured | Go, LLM | 1, 2 |
| 4 | `ingest-archive-documents` | unstructured | Python | 1 |
| 5 | `ner-entity-linking` | unstructured | Python, spaCy | 1, 4 |
| 6 | `extract-property-relations` | unstructured | Python | 2, 5 |
| 7 | `mine-ontology-candidates` | evolution | Python, LLM | 1, 5 |
| 8 | `apply-ontology-changes` | evolution | Go | 1, 7 |
| 9 | `review-app-ui` | evolution | SvelteKit | 8 |
| 10 | `ingest-iaea-safety` *(stretch)* | unstructured | Python | 5–9 |

**Two tracks** run after the foundation: a **structured** track (2 → 3) that lands the
grounded-analysis demo early, and an **unstructured/evolution** track (4 → 5 → 6 → 7 → 8 →
9) that lands the self-evolution demo. The analysis agent (3) is schema-generic, so it
automatically benefits from data added by 6 and 8 with **no rework**.

**Milestones:** chunk 3 = grounded-analysis demo works; chunk 9 = self-evolution demo works.

## Cross-cutting contracts (bind all chunks)

Fixed here so each OpenSpec change references them instead of re-deciding. Detail in
`ARCHITECTURE.md` → *Runtime contracts*.

- **Repo layout:**

  ```
  docker-compose.yml  Makefile
  ontology/       msr.ttl, vocab.ttl, example-flibe.ttl   (already materialized)
  cmd/            loader/  agent/  reviewd/               (Go binaries)
  internal/       graph/ (SPARQL client + FROM injection) · store/ (SQLite) · eval/ (msr_eval)
  extraction/     Python project — spaCy pipeline, miner, triage (pyproject.toml)
  webapp/         SvelteKit review UI (static build embedded in reviewd)
  data/           nist/ (vendored CSVs) · corpus/ (OCR cache, gitignored)
  ```

- **Named graphs & core dataset:** core = `urn:msr:ontology` + `urn:msr:data` +
  `urn:msr:vocab`; staging = `urn:msr:staging` + `urn:msr:proposal/{id}`. GraphDB queries
  with no dataset clause see **all** graphs — every core read goes through the shared
  `internal/graph` client, which injects the three `FROM` clauses.
- **SQLite — one shared table** for NIST and text-derived values:

  ```sql
  CREATE TABLE measurement_value (
    locator TEXT PRIMARY KEY, salt TEXT, property TEXT,
    c0 REAL, c1 REAL, c2 REAL, c3 REAL, c4 REAL,
    t_min REAL, t_max REAL, equation_form TEXT, uncertainty TEXT,
    source TEXT NOT NULL CHECK (source IN ('nist','document')), doc_id TEXT
  );
  ```

  Locator formats: `nist-srd27/{property}#{salt}|{composition}` ·
  `doc/{report#}/{property}#{slug}`.
- **Deterministic IRIs, no blank nodes** in pipeline-written data — re-runs are idempotent
  (RDF set semantics); minting scheme in ARCHITECTURE.
- **LLM access:** Anthropic API — Go `anthropic-sdk-go`, Python `anthropic`; model via
  `ANTHROPIC_MODEL` (default `claude-sonnet-5`); clients injected so tests stub them.
- **Run model:** batch CLI stages behind `make` targets; only GraphDB and `reviewd` are
  long-running. EntityRuler patterns are rebuilt from the graph at each extraction-run
  start; back-population = re-run.
- **Testing standard** (repo-wide): Go = table-driven `testing` with injected deps;
  Python = pytest; UI = vitest. Every chunk's OpenSpec `tasks.md` must carry a dedicated
  test section — seed it from that chunk's *Test seed* line.
- **OpenSpec mapping per chunk:** *Goal* → the proposal's why · *Scope + Interfaces* (+
  these contracts) → design · *Acceptance + Test seed* → tasks incl. the test section.

---

## 1 — `bootstrap-graph-infra`  *(foundation)*
- **Goal:** Stand up local stores and load the seed ontology + vocabulary so the design is live and queryable.
- **Scope:** Docker Compose (GraphDB, repo `msr`, **inference disabled**); repo layout per the contracts; SQLite init (`measurement_value` DDL); named-graph bootstrap — `msr.ttl`→`urn:msr:ontology`, `vocab.ttl`→`urn:msr:vocab`, `example-flibe.ttl`→`urn:msr:data`; create `urn:msr:staging`; the shared **`internal/graph` client with core-dataset `FROM` injection** (GraphDB has no store-side graph exclusion — this client *is* the enforcement); `make up` / `make load-seed`.
- **Interfaces:** produces compose + Makefile, initialized stores, and `internal/graph` — the read/write path every later chunk uses.
- **Depends on:** —
- **Acceptance:** GraphDB reachable; a SPARQL query **via the core-dataset client** returns the FLiBe example measurement; a triple placed in `urn:msr:staging` does **not** appear via the client but **does** appear in a raw no-`FROM` query (pinning why the client exists); `make load-seed` run twice yields identical triple counts.
- **Test seed:** Go tests for the client's `FROM` injection + staging exclusion (against the dockerized GraphDB); load idempotency.

## 2 — `load-nist-structured-data`  *(structured)*
- **Goal:** Load the fluoride subset of NIST into SQLite and emit catalog triples into the graph.
- **Scope:** Go loader (`cmd/loader`); vendor the 4 NIST CSVs into `data/nist/`; fluoride-subset filter (per `DATA_SCOPE.md`); salt-formula + composition parser → constituents (**minted IRIs, no blank nodes**); rows → `measurement_value` (`source='nist'`, locator per contract); emit `MoltenSalt` + `Constituent` + `PropertyMeasurement` (metadata + `dataLocator`) → `urn:msr:data` via `internal/graph`. Numbers stay in SQLite.
- **Interfaces:** consumes `data/nist/*.txt`; produces SQLite rows + catalog triples that chunk 3 reads and chunk 6 extends.
- **Depends on:** 1
- **Acceptance:** FLiBe density coefficients (`2.413, -4.88e-4`) present in SQLite; SPARQL returns a FLiBe density `PropertyMeasurement` with a resolvable locator; no chloride rows loaded (fluoride filter verified); row counts logged; re-running the loader changes nothing.
- **Test seed:** table-driven tests for the formula/composition parser (positional mole %, composition *ranges*, component alphabetization `BeF2-LiF` ≡ `LiF-BeF2`), equation-form mapping (`P1/P2/P3/+E/DP`), and the fluoride filter (rejects chlorides + mixed-anion salts); loader idempotency.

## 3 — `grounded-analysis-agent`  *(structured · demo #1)*
- **Goal:** An LLM agent that answers domain questions using the graph + the table — with **all arithmetic in deterministic code, never in the model**.
- **Scope:** Go agent loop (`cmd/agent`, Anthropic Go SDK, injected client) with **two** tools — `sparql_query` (grounding: resolve "FLiBe" → salt / measurement / locator / equation-form / valid range via the graph + SKOS altLabels; **reads through the core-dataset client**) and `sql_query` (values, read-only). Equation evaluation is a **custom scalar SQLite function `msr_eval(equation_form, c0..c4, T)` registered by the Go app** (dispatches Linear / Polynomial / Arrhenius / DiscretePoint, computes `exp` etc. in Go). Evaluation therefore happens *in SQL* — the agent calls the function, never does arithmetic and never hand-writes equation math. Range guard via `WHERE T BETWEEN t_min AND t_max` (or a NULL return). Ontology context in the prompt.
- **Interfaces:** read-only over both stores; schema-generic (no salt/property names hardcoded), so chunks 6 and 8 grow its answer surface with no code change.
- **Depends on:** 1, 2
- **Acceptance:**
  - `msr_eval` is deterministic and table-tested per equation form (each within tolerance of hand-computed values).
  - "density of the LiF-BeF2 (34-66) melt at 900 K" → ≈ **1.974 g·cm⁻³**, resolved as SPARQL (ground → locator) → one SQL call using `msr_eval`; the tool trace shows the agent performed no arithmetic itself.
  - A temperature outside `[t_min, t_max]` is flagged/excluded, not silently extrapolated.
  - A comparative query ("lowest-viscosity fluoride salt at 700 K") is answered by a single aggregating SQL query over `msr_eval` — demonstrating why evaluation lives in SQL rather than a per-value calculator.
- **Test seed:** `msr_eval` table-driven per equation form (hand-computed expected values, out-of-range → NULL); agent-loop integration test with a **stubbed LLM client** asserting the final number equals the `msr_eval` result and the trace contains no model arithmetic.

## 4 — `ingest-archive-documents`  *(unstructured)*
- **Goal:** Acquire and prepare the curated corpus for NER.
- **Scope:** LFS-skip clone (all 637 OCR sidecars land in `data/corpus/`, used later for frequency stats; only the curated ~12 are processed further); parse the README manifest (title / report# / date); OCR-normalization pre-pass (de-hyphenation, whitespace, sub/superscripts); sentence/paragraph segmentation; `Document` + provenance nodes → graph.
- **Interfaces:** produces `data/corpus/{report#}/normalized.txt` + `segments.jsonl` (sentence, char offsets) — the input format chunks 5–7 consume — and `Document` nodes keyed by report number.
- **Depends on:** 1
- **Acceptance:** 12 `Document` nodes with metadata in the graph; normalized, segmented text for ORNL-TM-2316 available to the pipeline; manifest parsed into structured records.
- **Test seed:** pytest fixtures for the normalizer (line-break de-hyphenation, `THERMAL-STRE SS`-style splits, sub/superscripts, common OCR confusions) and the manifest parser (real README rows).

## 5 — `ner-entity-linking`  *(unstructured · NER core)*
- **Goal:** Recognize and link known MSR entities to vocab concepts / ontology classes.
- **Scope:** Python/spaCy `EntityRuler` + `PhraseMatcher` **seeded from the graph at run start** (vocab + approved concepts: prefLabels + altLabels + generated variants, `attr="LOWER"`) — this per-run re-seed is also how approved evolution changes reach NER (no push signal); dedicated chemical-formula normalizer; bounded `rapidfuzz` fallback; write linked mention triples (deterministic IRIs: report# + char offsets) → `urn:msr:data` via SPARQL UPDATE.
- **Interfaces:** consumes `segments.jsonl` + the graph's concept labels; produces mention triples that chunks 6 and 7 consume.
- **Depends on:** 1, 4
- **Acceptance:** in ORNL-TM-2316, "LiF-BeF2", "FLiBe", "viscosity", "MSRE" link to the correct concepts; formula variants (`BeF2-LiF` ≡ `LiF-BeF2`) unify; precision spot-check on a labelled sample passes an agreed threshold; re-running the pipeline adds no duplicate mentions.
- **Test seed:** pytest for the formula normalizer (hyphen/order/`·`/subscript variants → one canonical form), pattern-variant generation, and a small labelled-sample precision harness (fixture sentences from ORNL-TM-2316).
- **Open tuning:** fuzziness threshold (see ARCHITECTURE open questions).

## 6 — `extract-property-relations`  *(unstructured · relations)*
- **Goal:** Turn linked entities into salt↔property↔value measurements and salt↔reactor↔role edges.
- **Scope:** relation extraction (dependency patterns and/or LLM) over linked entities; text-derived `PropertyMeasurement` triples → `urn:msr:data`, values → `measurement_value` (`source='document'`, `doc_id` set, locator `doc/{report#}/{property}#{slug}`) written by Python via stdlib `sqlite3`; unit-string → QUDT unit mapping; salt role / reactor edges.
- **Interfaces:** consumes chunk-5 mentions; extends exactly the stores chunk 3 already reads — the agent's answer surface grows with no agent change.
- **Depends on:** 2, 5
- **Acceptance:** a known statement (e.g. a FLiBe viscosity value in ORNL-TM-2316) becomes a `PropertyMeasurement` whose value is in SQLite and which `citedIn` the source document; the analysis agent (chunk 3) can then answer using it, unchanged; re-run adds no duplicates.
- **Test seed:** fixture-sentence relation tests (salt + property + value + unit patterns, incl. equation forms like `η = 0.084·exp(4340/T)`); unit-string → QUDT mapping table tests; SQLite write idempotency.
- **Open tuning:** relation-extraction depth (rules vs LLM).

## 7 — `mine-ontology-candidates`  *(evolution · detection)*
- **Goal:** Surface novel concepts as reviewable change proposals in staging.
- **Scope:** novelty miner (unlinked salient terms; **document-frequency scoring over all 637 OCR texts**, evidence sentences from the curated ~12); triage into property / class / instance / relation (context signals + LLM classifier via the `anthropic` package, injected) with QUDT/INIS grounding; **ChangeProposal mini-schema** — `msr:ChangeProposal` with `msr:kind`, `msr:reviewStatus`, `msr:term`, `msr:docFrequency`, evidence (sentence text + `msr:citedIn` doc ref, span offsets), and a link to its proposal graph — written to `urn:msr:staging`, proposed triples to `urn:msr:proposal/{id}`.
- **Interfaces:** consumes chunk-5 mention/miss output + `data/corpus/` for frequency stats; produces the staging records that chunk 8's API serves.
- **Depends on:** 1, 5
- **Acceptance:** a run over the corpus surfaces **`solubility`** (property) and **`graphite`** (class) as proposals with correct triage kind + evidence; proposals are invisible via the core-dataset client.
- **Test seed:** salience-scorer unit tests (threshold, already-linked exclusion); triage with a **stubbed LLM** returning fixed classifications → emitted proposal graphs validate against the mini-schema; staging invisibility test.
- **Open tuning:** salience threshold.

## 8 — `apply-ontology-changes`  *(evolution · governance backend)*
- **Goal:** Approve / edit / reject proposals; promote approved changes to core; auto-accept instances.
- **Scope:** Go engine (`cmd/reviewd`) + HTTP JSON API; **approve** = `ADD urn:msr:proposal/{id} TO urn:msr:ontology` (or `…/data`) + `owl:versionInfo` minor bump + PROV activity in staging; **reject** = mark rejected (triples remain in staging); **edit** = mutate the proposal graph; **instance auto-accept** path → `urn:msr:data` flagged `autoAccepted`. No EntityRuler push signal and no back-population trigger — both are covered by the next extraction re-run (per the run-model contract).
- **Interfaces (the chunk-9 API contract):** `GET /api/proposals?status=` (queue) · `GET /api/proposals/{id}` (proposal triples + evidence + affected ontology neighborhood for the diff render) · `PUT /api/proposals/{id}/graph` (edit) · `POST /api/proposals/{id}/approve` · `POST /api/proposals/{id}/reject`.
- **Depends on:** 1, 7
- **Acceptance:** approving the `solubility` proposal moves its triples into core (now visible to the core dataset and the analysis agent) and bumps the ontology version with a PROV record; reject leaves core unchanged; an instance proposal is auto-accepted without review.
- **Test seed:** lifecycle integration tests against the dockerized GraphDB — approve moves the graph + bumps version, reject leaves core untouched, edit persists, auto-accept bypasses review; API handler tests with a fake graph client.

## 9 — `review-app-ui`  *(evolution · UI · demo #2)*
- **Goal:** SvelteKit UI for visual ontology-diff review over the staging queue.
- **Scope:** SvelteKit frontend on the chunk-8 API; queue list; proposal detail with a **rendered ontology-neighborhood diff** (new nodes/edges highlighted), evidence panel (source spans + document links), editable placement/unit fields, approve/edit/reject controls; raw-triples advanced view. Built with the static adapter and **embedded in the `reviewd` binary** — one deployable.
- **Interfaces:** consumes exactly the chunk-8 API contract; no direct store access.
- **Depends on:** 8
- **Acceptance:** reviewer sees the `solubility` proposal as a visual diff, sets its unit to mole fraction, and approves; the `graphite` proposal shows the new class + `moderatedBy` relation; the approved change appears in core.
- **Test seed:** vitest component tests for the diff render (added nodes/edges highlighted) and queue/detail flows against a mocked API.

## 10 — `ingest-iaea-safety`  *(stretch)*
- **Goal:** Add the IAEA PUB2027 MSR-safety sections as a second NER genre → a `Safety` ontology branch via the same evolution loop.
- **Depends on:** 5–9 (reuses the whole pipeline). Deferred per `DATA_SCOPE.md`.

---

## Granularity notes (if you want coarser/finer)

- **5 + 6** can merge into one "NER pipeline" change; kept split because relation
  extraction carries its own tuning risk and validation.
- **8 + 9** can merge into one "review app"; kept split so the apply engine is testable
  via CLI before any UI exists.
- **4** can fold into 5 if you prefer fewer changes.
- Chunks **3** and **4** can be specced/built in parallel once **1–2** land.
