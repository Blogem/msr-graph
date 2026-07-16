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

---

## 1 — `bootstrap-graph-infra`  *(foundation)*
- **Goal:** Stand up local stores and load the seed ontology + vocabulary so the design is live and queryable.
- **Scope:** Docker Compose (GraphDB); repo layout (Go module, Python project); SQLite init; named-graph bootstrap — `msr.ttl`→`urn:msr:ontology`, `vocab.ttl`→`urn:msr:vocab`, `example-flibe.ttl`→`urn:msr:data`; create `urn:msr:staging`; configure the **default dataset = core graphs only** (staging excluded); `make up` / load scripts.
- **Depends on:** —
- **Acceptance:** GraphDB reachable; a SPARQL query over the default dataset returns the FLiBe example measurement; a triple placed in `urn:msr:staging` does **not** appear in default-dataset results.

## 2 — `load-nist-structured-data`  *(structured)*
- **Goal:** Load the fluoride subset of NIST into SQLite and emit catalog triples into the graph.
- **Scope:** Go loader; vendor the 4 NIST CSVs; fluoride-subset filter (per `DATA_SCOPE.md`); salt-formula + composition parser → constituents; SQLite schema `nist_measurement(locator, salt, property, c0..c4, t_min, t_max, equation_form, uncertainty, source)`; emit `MoltenSalt` + `Constituent` + `PropertyMeasurement` (metadata + `dataLocator`) → `urn:msr:data`. Numbers stay in SQLite.
- **Depends on:** 1
- **Acceptance:** FLiBe density coefficients (`2.413, -4.88e-4`) present in SQLite; SPARQL returns a FLiBe density `PropertyMeasurement` with a resolvable locator; no chloride rows loaded (fluoride filter verified); row counts logged.

## 3 — `grounded-analysis-agent`  *(structured · demo #1)*
- **Goal:** An LLM agent that answers domain questions using the graph + the table — with **all arithmetic in deterministic code, never in the model**.
- **Scope:** Go agent loop with **two** tools — `sparql_query` (grounding: resolve "FLiBe" → salt / measurement / locator / equation-form / valid range via the graph + SKOS altLabels) and `sql_query` (values). Equation evaluation is a **custom scalar SQLite function `msr_eval(equation_form, c0..c3, T)` registered by the Go app** (dispatches Linear / Polynomial / Arrhenius / DiscretePoint, computes `exp` etc. in Go). Evaluation therefore happens *in SQL* — the agent calls the function, never does arithmetic and never hand-writes equation math. Range guard via `WHERE T BETWEEN t_min AND t_max` (or a NULL return). Ontology context in the prompt.
- **Depends on:** 1, 2
- **Acceptance:**
  - `msr_eval` is deterministic and table-tested per equation form (each within tolerance of hand-computed values).
  - "density of the LiF-BeF2 (34-66) melt at 900 K" → ≈ **1.974 g·cm⁻³**, resolved as SPARQL (ground → locator) → one SQL call using `msr_eval`; the tool trace shows the agent performed no arithmetic itself.
  - A temperature outside `[t_min, t_max]` is flagged/excluded, not silently extrapolated.
  - A comparative query ("lowest-viscosity fluoride salt at 700 K") is answered by a single aggregating SQL query over `msr_eval` — demonstrating why evaluation lives in SQL rather than a per-value calculator.

## 4 — `ingest-archive-documents`  *(unstructured)*
- **Goal:** Acquire and prepare the curated corpus for NER.
- **Scope:** LFS-skip fetch of OCR sidecars for the ~12 curated docs; parse the README manifest (title / report# / date); OCR-normalization pre-pass (de-hyphenation, whitespace, sub/superscripts); sentence/paragraph segmentation; `Document` + provenance nodes → graph.
- **Depends on:** 1
- **Acceptance:** 12 `Document` nodes with metadata in the graph; normalized, segmented text for ORNL-TM-2316 available to the pipeline; manifest parsed into structured records.

## 5 — `ner-entity-linking`  *(unstructured · NER core)*
- **Goal:** Recognize and link known MSR entities to vocab concepts / ontology classes.
- **Scope:** Python/spaCy `EntityRuler` + `PhraseMatcher` seeded from `vocab.ttl` (prefLabels + altLabels + generated variants, `attr="LOWER"`); dedicated chemical-formula normalizer; bounded `rapidfuzz` fallback; write linked entity mentions (→ concept) to the graph.
- **Depends on:** 1, 4
- **Acceptance:** in ORNL-TM-2316, "LiF-BeF2", "FLiBe", "viscosity", "MSRE" link to the correct concepts; formula variants (`BeF2-LiF` ≡ `LiF-BeF2`) unify; precision spot-check on a labelled sample passes an agreed threshold.
- **Open tuning:** fuzziness threshold (see ARCHITECTURE open questions).

## 6 — `extract-property-relations`  *(unstructured · relations)*
- **Goal:** Turn linked entities into salt↔property↔value measurements and salt↔reactor↔role edges.
- **Scope:** relation extraction (dependency patterns and/or LLM) over linked entities; text-derived `PropertyMeasurement` (`source = document`) with the value written to SQLite (`source` column); salt role / reactor edges.
- **Depends on:** 2, 5
- **Acceptance:** a known statement (e.g. a FLiBe viscosity value in ORNL-TM-2316) becomes a `PropertyMeasurement` whose value is in SQLite and which `citedIn` the source document; the analysis agent (chunk 3) can then answer using it, unchanged.
- **Open tuning:** relation-extraction depth (rules vs LLM).

## 7 — `mine-ontology-candidates`  *(evolution · detection)*
- **Goal:** Surface novel concepts as reviewable change proposals in staging.
- **Scope:** novelty miner (unlinked salient terms, corpus-frequency scoring); triage into property / class / instance / relation (context signals + LLM classifier) with QUDT/INIS grounding; write a `ChangeProposal` (`reviewStatus "pending"`) + a per-proposal named graph to `urn:msr:staging` / `urn:msr:proposal/{id}`.
- **Depends on:** 1, 5
- **Acceptance:** a run over the corpus surfaces **`solubility`** (property) and **`graphite`** (class) as proposals with correct triage kind + evidence; proposals are invisible to the default dataset.
- **Open tuning:** salience threshold.

## 8 — `apply-ontology-changes`  *(evolution · governance backend)*
- **Goal:** Approve / edit / reject proposals; promote approved changes to core; auto-accept instances.
- **Scope:** Go engine + API/CLI; **approve** = `ADD urn:msr:proposal/{id} TO urn:msr:ontology` (+ version bump + PROV); **reject** = mark rejected (triples remain in staging); **edit** = mutate the proposal graph; **instance auto-accept** path → `urn:msr:data` flagged `autoAccepted`; back-population trigger; EntityRuler-refresh signal.
- **Depends on:** 1, 7
- **Acceptance:** approving the `solubility` proposal moves its triples into core (now visible to the default dataset and the analysis agent); reject leaves core unchanged; an instance proposal is auto-accepted without review.

## 9 — `review-app-ui`  *(evolution · UI · demo #2)*
- **Goal:** SvelteKit UI for visual ontology-diff review over the staging queue.
- **Scope:** SvelteKit frontend on the chunk-8 API; queue list; proposal detail with a **rendered ontology-neighborhood diff** (new nodes/edges highlighted), evidence panel (source spans + document links), editable placement/unit fields, approve/edit/reject controls; raw-triples advanced view.
- **Depends on:** 8
- **Acceptance:** reviewer sees the `solubility` proposal as a visual diff, sets its unit to mole fraction, and approves; the `graphite` proposal shows the new class + `moderatedBy` relation; the approved change appears in core.

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
