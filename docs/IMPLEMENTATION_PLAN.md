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
| 3 | `sandbox-exec-pool` | structured | Go, Docker | 1 |
| 4 | `grounded-analysis-agent` | structured | Go, DeepSeek V4 Pro | 1, 2, 3 |
| 5 | `ingest-archive-documents` | unstructured | Python | 1 |
| 6 | `ner-entity-linking` | unstructured | Python, spaCy, DeepSeek V4 Flash | 1, 2, 5 |
| 7 | `extract-property-relations` | unstructured | Python, DeepSeek V4 Flash | 2, 6 |
| 8 | `mine-ontology-candidates` | evolution | Python, DeepSeek V4 Flash | 1, 6 |
| 9 | `apply-ontology-changes` | evolution | Go | 1, 8 |
| 10 | `web-frontend` | UI | SvelteKit | 4, 9 |
| 11 | `ingest-iaea-safety` *(stretch)* | unstructured | Python | 6–10 |

**Two tracks** run after the foundation: a **structured** track (2 · 3 → 4) that lands the
grounded-analysis demo early (chat API with full trace, before any UI), and an
**unstructured/evolution** track (5 → 6 → 7 → 8 → 9); chunk 10 puts both demos in the
single frontend. The analysis agent (4) is schema-generic, so it automatically benefits
from data added by 7 and 9 with **no rework**. Chunk 6 depends on 2 on purpose: the salt
catalog loads **before** NER so mentions link to existing salt individuals.

**Milestones:** chunk 4 = grounded-analysis demo works (traced, via API); chunk 10 = both
demos in the web app, incl. checkpoint/reset re-runs.

## Cross-cutting contracts (bind all chunks)

Fixed here so each OpenSpec change references them instead of re-deciding. Detail in
`ARCHITECTURE.md` → *Runtime contracts*.

- **Repo layout:**

  ```
  docker-compose.yml  Makefile
  ontology/       msr.ttl, vocab.ttl, example-flibe.ttl   (already materialized)
  cmd/            loader/  server/                        (Go binaries)
  internal/       graph/ (SPARQL client + FROM injection) · store/ (SQLite) ·
                  sandbox/ (container pool) · agent/ (loop, tools, trace events)
  extraction/     Python project — spaCy pipeline, miner, triage (pyproject.toml)
  webapp/         SvelteKit frontend — chat + review + admin (static build embedded in server)
  data/           nist/ (vendored CSVs) · corpus/ (OCR cache) · checkpoints/  (both gitignored)
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
- **LLM access:** DeepSeek API only (OpenAI-compatible; no Anthropic models, no local
  LLMs) — **V4 Flash** for extraction/disambiguation/triage, **V4 Pro** for the analysis
  agent; cached byte-stable KG-schema system prompt (TBox + vocab + salt catalog,
  regenerated on version bump); config `DEEPSEEK_BASE_URL`, `LLM_MODEL_EXTRACT`,
  `LLM_MODEL_ANALYSIS`. Clients are injected interfaces — **every test runs against a
  stub, never a live model**.
- **Run model & deployment:** the whole solution runs in containers (Compose): `graphdb`,
  `server` (Go binary + embedded frontend; mounts the Docker socket to manage sandbox
  **sibling** containers), one-shot `extraction` runs behind `make` targets, and the
  sandbox pool. The SQLite file lives on a shared volume — server read-write, sandboxes
  **read-only**. EntityRuler patterns are rebuilt from the graph at each extraction-run
  start; back-population = re-run.
- **Testing standard** (repo-wide): Go = table-driven `testing` with injected deps;
  Python = pytest; UI = vitest. Every chunk's OpenSpec `tasks.md` must carry a dedicated
  test section — seed it from that chunk's *Test seed* line.
- **OpenSpec mapping per chunk:** *Goal* → the proposal's why · *Scope + Interfaces* (+
  these contracts) → design · *Acceptance + Test seed* → tasks incl. the test section.

---

## 1 — `bootstrap-graph-infra`  *(foundation)*
- **Goal:** Stand up local stores and load the seed ontology + vocabulary so the design is live and queryable.
- **Scope:** Docker Compose for the **whole solution** (GraphDB repo `msr` with **inference disabled**; `server` and `extraction` image scaffolds; the sandbox base image — minimal Python + numpy/pandas; shared data volume); repo layout per the contracts; SQLite init (`measurement_value` DDL); named-graph bootstrap — `msr.ttl`→`urn:msr:ontology`, `vocab.ttl`→`urn:msr:vocab`, `example-flibe.ttl`→`urn:msr:data`; create `urn:msr:staging`; the shared **`internal/graph` client with core-dataset `FROM` injection** (GraphDB has no store-side graph exclusion — this client *is* the enforcement); `make up` / `make load-seed`.
- **Interfaces:** produces compose + Makefile, initialized stores, and `internal/graph` — the read/write path every later chunk uses.
- **Depends on:** —
- **Acceptance:** GraphDB reachable; a SPARQL query **via the core-dataset client** returns the FLiBe example measurement; a triple placed in `urn:msr:staging` does **not** appear via the client but **does** appear in a raw no-`FROM` query (pinning why the client exists); `make load-seed` run twice yields identical triple counts.
- **Test seed:** Go tests for the client's `FROM` injection + staging exclusion (against the dockerized GraphDB); load idempotency.

## 2 — `load-nist-structured-data`  *(structured)*
- **Goal:** Load the fluoride subset of NIST into SQLite and emit catalog triples into the graph.
- **Scope:** Go loader (`cmd/loader`); vendor the 4 NIST CSVs into `data/nist/`; fluoride-subset filter (per `DATA_SCOPE.md`); salt-formula + composition parser → constituents (**minted IRIs, no blank nodes**); rows → `measurement_value` (`source='nist'`, locator per contract); emit `MoltenSalt` + `Constituent` + `PropertyMeasurement` (metadata + `dataLocator`) → `urn:msr:data` via `internal/graph`. Numbers stay in SQLite.
- **Interfaces:** consumes `data/nist/*.txt`; produces SQLite rows + catalog triples that chunk 4 reads, chunk 6 links mentions against, and chunk 7 extends.
- **Depends on:** 1
- **Acceptance:** FLiBe density coefficients (`2.413, -4.88e-4`) present in SQLite; SPARQL returns a FLiBe density `PropertyMeasurement` with a resolvable locator; no chloride rows loaded (fluoride filter verified); row counts logged; re-running the loader changes nothing.
- **Test seed:** table-driven tests for the formula/composition parser (positional mole %, composition *ranges*, component alphabetization `BeF2-LiF` ≡ `LiF-BeF2`), equation-form mapping (`P1/P2/P3/+E/DP`), and the fluoride filter (rejects chlorides + mixed-anion salts); loader idempotency.

## 3 — `sandbox-exec-pool`  *(structured · execution)*
- **Goal:** A warm pool of throwaway sandbox containers that runs Python scripts safely — **all analysis computation happens here**, not in the model and not in SQLite (supersedes the earlier `msr_eval` design).
- **Scope:** Go `internal/sandbox`: a buffered channel `chan *Sandbox` *is* the pool (size N, default 3); acquire = channel receive; after **one** script run the container is force-removed and a goroutine replenishes the pool with a fresh one. Container spec: sandbox base image (minimal Python + numpy/pandas), `--network none`, read-only root FS + tmpfs `/tmp`, non-root, CPU/mem/pids limits, wall-clock timeout; SQLite bind-mounted **read-only** at `/data/msr.db`. Script contract: source on stdin (`docker exec -i … python -`), JSON result on stdout, stderr + exit code captured.
- **Interfaces:** `Run(ctx, script) → (stdout, stderr, exitCode)` consumed by chunk 4's `run_python` tool; sandboxes are sibling containers managed via the Docker socket.
- **Depends on:** 1
- **Acceptance:** a script queries `/data/msr.db` and returns JSON; a write attempt on the DB fails; network access fails; a long-running script is killed at the timeout; after each run the used container is gone and a fresh one sits in the pool; concurrent acquires drain and refill the pool without races.
- **Test seed:** unit tests against a faked container-runtime interface (drain/replenish, timeout, concurrency under `-race`); one integration test against real Docker exercising the isolation properties (read-only mount, no network, teardown).

## 4 — `grounded-analysis-agent`  *(structured · demo #1)*
- **Goal:** A conversational agent that answers domain questions using the graph + the table — **all computation in sandboxed scripts, never in the model** — and streams a full trace of how each answer was produced.
- **Scope:** Go agent loop (`internal/agent`, DeepSeek V4 Pro via an injected OpenAI-compatible client) with **three** tools — `sparql_query` (grounding: resolve "FLiBe" → salt / measurement / locator / equation-form / valid range via the graph + SKOS altLabels; **reads through the core-dataset client**), `sql_query` (read-only, SELECT-only guard), and `run_python` (chunk-3 pool; scripts read `/data/msr.db` and compute — equation evaluation, aggregation, comparison). Cached KG-schema system prompt (byte-stable TBox + vocab + salt-catalog serialization). **Chat API:** `POST /api/chat` on the server, streaming SSE **trace events** — `text`, `tool_call`, `tool_result`, `script_run` (source + stdout/stderr + exit code), `provenance` (dataLocators, `citedIn` docs, dataset DOIs, ontology version), `done`. This event schema is the chunk-10 contract. Traces persist to a `trace` SQLite table for replay.
- **Interfaces:** read-only over both stores + the chunk-3 pool; schema-generic (no salt/property names hardcoded), so chunks 7 and 9 grow its answer surface with no code change.
- **Depends on:** 1, 2, 3
- **Acceptance:**
  - "density of the LiF-BeF2 (34-66) melt at 900 K" → ≈ **1.974 g·cm⁻³**; the trace shows SPARQL grounding → coefficient fetch → a `script_run` whose source contains the evaluation; the final number equals the script output (the model did no arithmetic).
  - A temperature outside `[t_min, t_max]` is flagged/refused, not silently extrapolated.
  - A comparative query ("lowest-viscosity fluoride salt at 700 K") is answered by one script aggregating over the mounted DB.
  - Every trace event type appears in a demo run; provenance events name the NIST DOI / ORNL report behind each value.
- **Test seed:** agent-loop tests with a **stubbed LLM** + fake pool (final answer equals script output; event sequence correct); SELECT-only-guard table tests; SSE handler + trace-persistence tests; prompt-prefix stability test (same graph state → byte-identical prompt).

## 5 — `ingest-archive-documents`  *(unstructured)*
- **Goal:** Acquire and prepare the curated corpus for NER.
- **Scope:** LFS-skip clone (all 637 OCR sidecars land in `data/corpus/`, used later for frequency stats; only the curated ~12 are processed further); parse the README manifest (title / report# / date); OCR-normalization pre-pass (de-hyphenation, whitespace, sub/superscripts); sentence/paragraph segmentation; `Document` + provenance nodes → graph.
- **Interfaces:** produces `data/corpus/{report#}/normalized.txt` + `segments.jsonl` (sentence, char offsets) — the input format chunks 6–8 consume — and `Document` nodes keyed by report number.
- **Depends on:** 1
- **Acceptance:** 12 `Document` nodes with metadata in the graph; normalized, segmented text for ORNL-TM-2316 available to the pipeline; manifest parsed into structured records.
- **Test seed:** pytest fixtures for the normalizer (line-break de-hyphenation, `THERMAL-STRE SS`-style splits, sub/superscripts, common OCR confusions) and the manifest parser (real README rows).

## 6 — `ner-entity-linking`  *(unstructured · NER core)*
- **Goal:** Recognize and link known MSR entities to vocab concepts / ontology classes / **loaded salt individuals**.
- **Scope:** Python/spaCy `EntityRuler` + `PhraseMatcher` **seeded from the graph at run start** (vocab + approved concepts: prefLabels + altLabels + generated variants, `attr="LOWER"`, **plus the chunk-2 salt catalog** so salt mentions link to the loaded `MoltenSalt` individuals) — this per-run re-seed is also how approved evolution changes reach NER (no push signal); dedicated chemical-formula normalizer; bounded `rapidfuzz` fallback; **DeepSeek V4 Flash disambiguation layer** for spans layers 1–4 can't settle (cached KG-schema prompt; schema-constrained JSON that may only reference *existing* IRIs — validated, else rejected — or declare the span novel); write linked mention triples (deterministic IRIs: report# + char offsets) → `urn:msr:data` via SPARQL UPDATE.
- **Interfaces:** consumes `segments.jsonl` + the graph's concept labels + salt catalog; produces mention triples that chunks 7 and 8 consume.
- **Depends on:** 1, 2, 5
- **Acceptance:** in ORNL-TM-2316, "LiF-BeF2", "FLiBe", "viscosity", "MSRE" link to the correct concepts **and the LiF-BeF2 mention resolves to the loaded salt individual**; formula variants (`BeF2-LiF` ≡ `LiF-BeF2`) unify; an OCR-mangled span unresolved lexically is settled by the Flash layer (fixture); Flash output referencing an unknown IRI is rejected; precision spot-check on a labelled sample passes an agreed threshold; re-running the pipeline adds no duplicate mentions.
- **Test seed:** pytest for the formula normalizer (hyphen/order/`·`/subscript variants → one canonical form), pattern-variant generation, **stubbed-Flash** disambiguation (accept on valid IRI, reject on unknown IRI, novel-span path), and a small labelled-sample precision harness (fixture sentences from ORNL-TM-2316).
- **Open tuning:** fuzziness threshold (see ARCHITECTURE open questions).

## 7 — `extract-property-relations`  *(unstructured · relations)*
- **Goal:** Turn linked entities into salt↔property↔value measurements and salt↔reactor↔role edges.
- **Scope:** relation extraction via **DeepSeek V4 Flash** (cached KG-schema prompt; schema-constrained JSON validated against known IRIs and units — resolves the earlier rules-vs-LLM question) over sentences with linked entities; text-derived `PropertyMeasurement` triples → `urn:msr:data`, values → `measurement_value` (`source='document'`, `doc_id` set, locator `doc/{report#}/{property}#{slug}`) written by Python via stdlib `sqlite3`; unit-string → QUDT unit mapping; salt role / reactor edges.
- **Interfaces:** consumes chunk-6 mentions; extends exactly the stores chunk 4 already reads — the agent's answer surface grows with no agent change.
- **Depends on:** 2, 6
- **Acceptance:** a known statement (e.g. a FLiBe viscosity value in ORNL-TM-2316) becomes a `PropertyMeasurement` whose value is in SQLite and which `citedIn` the source document; the analysis agent (chunk 4) can then answer using it, unchanged; re-run adds no duplicates.
- **Test seed:** **stubbed-Flash** fixture-sentence relation tests (salt + property + value + unit, incl. equation forms like `η = 0.084·exp(4340/T)`; invalid IRIs/units rejected); unit-string → QUDT mapping table tests; SQLite write idempotency.

## 8 — `mine-ontology-candidates`  *(evolution · detection)*
- **Goal:** Surface novel concepts as reviewable change proposals in staging.
- **Scope:** novelty miner (unlinked salient terms; **document-frequency scoring over all 637 OCR texts**, evidence sentences from the curated ~12); triage into property / class / instance / relation (context signals + **DeepSeek V4 Flash** classifier via an injected OpenAI-compatible client) with QUDT/INIS grounding; **ChangeProposal mini-schema** — `msr:ChangeProposal` with `msr:kind`, `msr:reviewStatus`, `msr:term`, `msr:docFrequency`, evidence (sentence text + `msr:citedIn` doc ref, span offsets), and a link to its proposal graph — written to `urn:msr:staging`, proposed triples to `urn:msr:proposal/{id}`.
- **Interfaces:** consumes chunk-6 mention/miss output + `data/corpus/` for frequency stats; produces the staging records that chunk 9's API serves.
- **Depends on:** 1, 6
- **Acceptance:** a run over the corpus surfaces **`solubility`** (property) and **`graphite`** (class) as proposals with correct triage kind + evidence; proposals are invisible via the core-dataset client.
- **Test seed:** salience-scorer unit tests (threshold, already-linked exclusion); triage with a **stubbed LLM** returning fixed classifications → emitted proposal graphs validate against the mini-schema; staging invisibility test.
- **Open tuning:** salience threshold.

## 9 — `apply-ontology-changes`  *(evolution · governance backend)*
- **Goal:** Approve / edit / reject proposals; promote approved changes to core; auto-accept instances; **checkpoint/restore the whole store for demo rollback**.
- **Scope:** Go engine (in `cmd/server`) + HTTP JSON API; **approve** = `ADD urn:msr:proposal/{id} TO urn:msr:ontology` (or `…/data`) + `owl:versionInfo` minor bump + PROV activity in staging; **reject** = mark rejected (triples remain in staging); **edit** = mutate the proposal graph; **instance auto-accept** path → `urn:msr:data` flagged `autoAccepted`. No EntityRuler push signal and no back-population trigger — both are covered by the next extraction re-run (per the run-model contract). **Checkpoint/restore:** checkpoint = full repository export (TriG, all named graphs) + SQLite file copy + ontology version → `data/checkpoints/{label}/`; restore = clear repo → import → put the SQLite copy back (atomic demo rollback — proposal statuses, back-populated instances, and text-derived rows revert together).
- **Interfaces (the chunk-10 API contract):** `GET /api/proposals?status=` (queue) · `GET /api/proposals/{id}` (proposal triples + evidence + affected ontology neighborhood for the diff render) · `PUT /api/proposals/{id}/graph` (edit) · `POST /api/proposals/{id}/approve` · `POST /api/proposals/{id}/reject` · `GET|POST /api/checkpoints` · `POST /api/checkpoints/{label}/restore`.
- **Depends on:** 1, 8
- **Acceptance:** approving the `solubility` proposal moves its triples into core (now visible to the core dataset and the analysis agent) and bumps the ontology version with a PROV record; reject leaves core unchanged; an instance proposal is auto-accepted without review; **checkpoint → approve → restore** reverts everything (version back, proposal `pending` again, the agent no longer answers solubility questions) and the approval can be re-run.
- **Test seed:** lifecycle integration tests against the dockerized GraphDB — approve moves the graph + bumps version, reject leaves core untouched, edit persists, auto-accept bypasses review; checkpoint/restore round-trip (triple counts + SQLite hash identical to pre-checkpoint state); API handler tests with a fake graph client.

## 10 — `web-frontend`  *(UI · demo #2)*
- **Goal:** The **single user-facing app**: conversational analytics with a visible trace, ontology-diff review, and checkpoint/reset admin.
- **Scope:** one SvelteKit app (static adapter, **embedded in the `server` binary** — one deployable) with three surfaces. **(a) Chat** — conversation pane + per-turn expandable **trace timeline** rendering every chunk-4 event type: tool calls with args, result payloads, script source + stdout, provenance chips linking NIST DOI / ORNL reports, and the ontology version used. **(b) Review** — queue list; proposal detail with a **rendered ontology-neighborhood diff** (new nodes/edges highlighted), evidence panel (source spans + document links), editable placement/unit fields, approve/edit/reject controls; raw-triples advanced view. **(c) Admin** — checkpoint list / create / restore.
- **Interfaces:** consumes exactly the chunk-4 SSE event schema and the chunk-9 API; no direct store access.
- **Depends on:** 4, 9
- **Acceptance:** one app serves all three surfaces; the density question's full trace is inspectable (incl. script source and provenance chips); reviewer sees the `solubility` proposal as a visual diff, sets its unit to mole fraction, and approves — the `graphite` proposal shows the new class + `moderatedBy` relation; **demo reset:** restoring a pre-demo checkpoint from the admin panel lets the whole evolution demo be re-run end-to-end.
- **Test seed:** vitest component tests — trace timeline (each event type renders; script + provenance visible) against a mocked SSE stream; diff render (added nodes/edges highlighted); queue/detail and admin flows against a mocked API.

## 11 — `ingest-iaea-safety`  *(stretch)*
- **Goal:** Add the IAEA PUB2027 MSR-safety sections as a second NER genre → a `Safety` ontology branch via the same evolution loop.
- **Depends on:** 6–10 (reuses the whole pipeline). Deferred per `DATA_SCOPE.md`.

---

## Granularity notes (if you want coarser/finer)

- **6 + 7** can merge into one "NER pipeline" change; kept split because relation
  extraction carries its own validation risk.
- **9 + 10** can merge into one "web app" change; kept split so the apply engine and
  checkpoints are testable via API before any UI exists.
- **5** can fold into 6 if you prefer fewer changes.
- **3** is deliberately standalone: the sandbox pool is the security-sensitive piece and
  deserves its own spec and review.
- Chunks **3** and **5** can be specced/built in parallel once **1** lands.
