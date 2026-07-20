## Context

Provenance is the project's stated central principle but is nowhere a requirement. Today:

- `cmd/loader/nist.go` emits `prov:wasDerivedFrom msrd:nist-srd27` on each `PropertyMeasurement`, but the `msrd:nist-srd27` `Dataset` node (with its DOI) was defined only in the hand-curated seed (`ontology/example-flibe.ttl`) — so before this change a measurement's `wasDerivedFrom` DOI is unresolvable once the seed is gone.
- `internal/agent/loop.go` emits a `ProvenanceEvent` **only** when a `sparql_query` result happens to bind a variable whose name matches the `locator`/`cited`/`doi` convention (`internal/agent/sparql.go`). A numeric answer can reach the user with zero provenance events; there is no turn-end groundedness stamp.
- `internal/agent/python.go` emits a `ScriptRunEvent` but nothing ties the computed number to the `dataLocator`(s) the script actually read.
- The extraction writers (`extraction/src/msr_extraction/mentions.py`, `documents.py`) write `Mention`/`Document` individuals with no generating `Activity`.

Constraints that shape the design:

- **The agent read path is restricted to the core graphs** (`internal/graph`: `CoreGraphs = [Ontology, Data, Vocab]`); `sparql_query` uses `Select`, which never sees `urn:msr:staging`/proposal graphs. Any provenance the agent must _query_ has to live in a core graph.
- `graph.Client.Update` runs arbitrary SPARQL UPDATE with explicit `GRAPH` targets and has **no** graph-IRI allowlist; only `PutGraph` (graph-replace) restricts to the known constants. So writers can target new named graphs without touching the client's allowlist.
- POC data is disposable: after `ground-demo-in-real-docs`, `load-seed` graph-**replaces** only the TBox/vocab graphs (`urn:msr:ontology`, `urn:msr:vocab`) — the hand-curated A-Box is gone — and `urn:msr:data` is populated solely by the NIST loader and extraction writers via additive `INSERT DATA`.
- This change is scoped to **provenance + the vocabulary**. The write-time SHACL gate that _enforces_ these invariants is chunk 13 (`shacl-validation`), which depends on the vocabulary defined here.

## Goals / Non-Goals

**Goals:**

- A PROV-O slice in the ontology sufficient to attribute every fact to who/what/when produced it.
- Every **pipeline-asserted instance individual** (`PropertyMeasurement`, `Mention`, and the loader's `MoltenSalt`/`Constituent`/`ChemicalCompound`) carries **complete + required** `prov:wasGeneratedBy` (a run `Activity` with `Agent`, ontology version, timestamps) and `prov:wasDerivedFrom` its source. Source entities (`Dataset`/`Document`) are derivation roots (external id); TBox/vocab are excluded (definitional, `owl:versionInfo`-versioned). (No `msr:citedIn` — deferred; see Non-Goals / D3.)
- The NIST loader is self-contained: it emits the dataset node + DOI itself (the seed no longer provides them).
- The extraction writers stamp an extraction-run `Activity`.
- A coarse per-source/per-run audit dimension via named graphs.
- The agent stamps **every** answer grounded-vs-ungrounded (enforced in the loop, not the model) and surfaces the provenance chain of the facts used; a `run_python` result references the `dataLocator`(s) its script read.

**Non-Goals:**

- **No SHACL** — enforcement is chunk 13. This change makes writers _emit_ complete provenance; it does not add the database-side gate. (Tests here assert emitted output; rejection tests belong to chunk 13.)
- **No RDF-star** statement-level annotation (design doc §1.2: marginal gain at POC scale).
- **No new domain/safety schema** — the requirements/safety branch is the real IAEA ingest (chunk 11).
- **No graph-layout refactor** — facts stay in `urn:msr:data`; named graphs are additive (see Decisions).
- **No fabricated data / no fabricated provenance** — provenance points only at real datasets/documents/runs; no writer invents provenance for a fact it can't trace to a real source (D9).
- **No `msr:citedIn` from the loader** — NIST SRD-27 has no per-row citation, so a truthful measurement↔document citation has no source yet; it is deferred to chunk-7 citation extraction (D3). Every measurement's derivation is still complete via `prov:wasDerivedFrom` the dataset (+ DOI).
- **No seed removal or grounding rework here** — deleting `example-flibe.ttl` and re-grounding the agent on real `msr:Mention` links is the separate change `ground-demo-in-real-docs` (D9); this change only makes the real-data writers self-sufficient so that removal is clean.

## Decisions

### D1 — Property-level PROV-O is the enforced baseline; facts stay in `urn:msr:data`

Every pipeline-asserted instance individual carries `prov:wasGeneratedBy` (a run `Activity`) and, where it derives from a source, `prov:wasDerivedFrom` (that source `Entity`). This is not just `PropertyMeasurement`/`Mention` but the loader's `MoltenSalt`/`Constituent`/`ChemicalCompound` too (they are asserted from NIST rows, so they are facts with a source). Source entities (`Dataset`/`Document`) are the roots — their external identifier (DOI / report number) is their provenance. Schema (TBox) and SKOS vocab are excluded: definitional, not source-derived, versioned by `owl:versionInfo`. The `Activity` carries `prov:wasAssociatedWith` an `Agent` (`agent:loader@<version>`, `agent:extraction@<version>`, or a human reviewer), `prov:startedAtTime`/`prov:endedAtTime`, and the `owl:versionInfo` in effect. *(Why not "everything"? Because schema/vocab are the model, not empirical claims from a source — their versioning is `owl:versionInfo`; every instance fact, however, is now in scope.)*

Facts continue to be written to `urn:msr:data` — the layout is unchanged. This is minimally disruptive and, critically, keeps the agent's core-graph `Select` able to reach every measurement/mention _and_ its property-level provenance in one query. **Alternative rejected:** move facts into the per-run named graphs and expand the core read set to their union. This is a bigger, invariant-touching change to the read path and interacts with the staging-exclusion guarantee; deferred as a future enhancement.

### D2 — Named graphs hold the `Activity` records (audit dimension), written via `Update`

Each source gets `urn:msr:src:<id>` (e.g. `urn:msr:src:nist-srd27`) and each pipeline run gets `urn:msr:run:<pipeline>/<ts>` (e.g. `urn:msr:run:loader/<ts>`, `urn:msr:run:extraction/<ts>`). Each named graph holds a single PROV `Activity` record plus the run's `Agent`/`Dataset` metadata. Facts in `urn:msr:data` point at these Activities via `prov:wasGeneratedBy`, so "everything from run Y" is answerable by joining on the Activity IRI.

Written via `graph.Client.Update` with an explicit `GRAPH <urn:msr:run:...>` target — no `PutGraph`, so no change to the client's known-graph allowlist and no graph-replace risk. **Timestamps** (`prov:startedAtTime`/`endedAtTime`) come from the loader/extraction process clock at write time and live in the timestamped run graph (see D8).

The `Activity` IRI that facts in `urn:msr:data` reference via `prov:wasGeneratedBy` is **deterministic per pipeline/source** (e.g. `msrd:activity-loader-nist`, `msrd:activity-extraction`), _not_ timestamped. This keeps the `wasGeneratedBy` edge in `urn:msr:data` byte-stable across re-runs so the existing fact-store idempotency guarantees hold (D8). The wall-clock `Activity` record (type, agent, timestamps, ontology version) is asserted in the timestamped run graph.

**Rollback note / trade-off:** because facts live in `urn:msr:data` (D1), dropping a run graph does not remove that run's facts. At POC scale rollback is a wholesale rebuild (re-run `load-nist` + `ingest` + `link`); per-run-graph `DROP` as a true rollback unit is deferred to the future layout change in D1.

### D3 — The loader is the sole source of the NIST dataset node, DOI, and measurement

The seed is already gone (removed by the prerequisite `ground-demo-in-real-docs`), so `cmd/loader/nist.go` is now the **sole** source of the NIST `msrd:nist-srd27` `msr:Dataset` node (with `dcterms:identifier "doi:10.18434/mds2-2298"`) and the FLiBe density `PropertyMeasurement` (plus the catalog salts/constituents/compounds), all with full provenance. This closes the interim gap `ground-demo` left: the loader already emits `prov:wasDerivedFrom msrd:nist-srd27`, but that node did not exist until now — this change defines it, so every measurement's derivation resolves to a real dataset + DOI. Constants (dataset IRI, DOI) live in the loader alongside the existing `insertPrefixes`.

**No `msr:citedIn` from the loader.** A `citedIn` edge is a *citation* claim — this measurement is reported in that document — and the vendored NIST SRD-27 CSVs carry **no per-row citation column** (`Salt, Composition range, Data type, T min/max, Uncertainty, Data 1–5, Comment, Formatting comment`), so the loader cannot assert one truthfully for any row, let alone a single "default" ORNL report for every row (SRD-27 is a compilation of many primary sources; one report backs almost none of them). Emitting a blanket `msr:citedIn msrd:ORNL-TM-2316` would merely relocate the seed's hand-curated citation into the loader — the exact fabrication `ground-demo` removed. Per Principle 3 (only real data) and the project's "defer capabilities without a real source" principle, `msr:citedIn` is **deferred to chunk-7 citation/relation extraction**, which can derive real measurement↔document citations from text; the predicate stays declared in the TBox (unused for now). Document-traceability for the demo already comes from the grounding `msr:Mention`'s `msr:inDocument` (established by `ground-demo`), not from `citedIn`. **Alternative rejected:** keep a loader `citedIn` default — it asserts a citation that is false for the overwhelming majority of rows, defeating the whole point of this trust work.

### D9 — Only real data; the seed is already gone (prerequisite), provenance layers on top

Principle 3 of `docs/PROVENANCE_AND_TRUST_DESIGN.md` — *only real data, nothing fabricated for demonstration* — governs scope. The provenance requirement here applies to the outputs of the **real-data writers**: the loader (over the real vendored NIST CSVs) and the extraction pipeline (over real ORNL documents). Their asserted instance individuals carry complete, required provenance tracing to real sources and real run activities.

The hand-curated seed A-Box (`ontology/example-flibe.ttl`) — scaffolding and all — is **already removed by the prerequisite `ground-demo-in-real-docs`**, which lands first and reworks agent grounding onto real `msr:Mention → msr:linksTo → salt` links. So `provenance-model` operates on an all-real, seed-free graph and simply layers the provenance invariant on top — no seed to coexist with, no grounding rework here. Sequencing the *make-it-real* re-architecture before the *make-it-provenanced* retrofit keeps each change reviewable and never leaves grounding broken mid-change. **Alternative rejected:** fold seed removal + grounding rework into `provenance-model`, or run provenance first and have it carry seed-coexistence hedging — both are messier than the clean `ground-demo → provenance → shacl` layering.

### D4 — Answer-time groundedness stamp enforced in `loop.go`

The loop tracks, per turn, whether any `ProvenanceEvent` was emitted (i.e. the answer drew on grounded facts) and aggregates the union of their locators/citedIn/DOIs. When the model returns a final answer (no further tool calls), the loop emits a **new first-class trace event** carrying `grounded: bool` and the aggregated provenance chain, _before_ the `done` event. An answer with no provenance events is stamped `grounded: false`. This is enforced in the loop, independent of the model naming its variables a certain way.

New event type `EventAnswer` (`"answer"`) with payload `{ grounded bool, provenance ProvenanceEvent }` added to `internal/agent/events.go`, extending the existing `Event` union. **Alternative rejected:** overload the existing `ProvenanceEvent` with a `grounded` flag — but the per-tool provenance event and the per-turn answer stamp are distinct concerns (one is a tool result, one is a turn verdict), so a separate event is clearer and matches the chat-API contract's one-event-per-concern shape. `SystemInstructions` already tells the model to refuse a number without grounding (rule 2/4); the loop stamp makes it machine-checked rather than prompt-dependent.

### D5 — Compute-time locator linkage by scanning the script against grounded locators

The loop already sees every `dataLocator` surfaced by `sparql_query` this turn (they flow through `ProvenanceEvent`s). When a `run_python` script runs, the loop scans the script source for any of those known locator strings and attaches the matched set to the run's provenance (carried on the `ScriptRunEvent` via a new `DataLocators []string` field, and folded into the turn's aggregated chain). This ties the computed number to the grounded rows it read without asking the model to self-report. **Alternative rejected:** require the model to declare the locators it used — unreliable and unenforceable. Scanning against the _actually grounded_ locator set is deterministic and cannot be gamed by the model naming a locator it never grounded.

### D6 — Extraction writers stamp an extraction-run `Activity`

`mentions.py`/`documents.py` add `prov:wasGeneratedBy msrd:activity-extraction` (the deterministic per-pipeline Activity IRI, D2) to each individual, and write the timestamped `Activity` record (agent `agent:extraction@<version>`, `startedAtTime`/`endedAtTime`, ontology version) into `urn:msr:run:extraction/<ts>`. The timestamp is generated once per CLI invocation and threaded to both writers so a single run shares one run graph and one Activity record. Provenance-triple construction mirrors the existing `_escape_literal`/`INSERT DATA` helpers.

### D7 — Vocabulary is the contract for chunk 13

The exact predicate set, cardinalities, and IRI conventions defined here (in the `provenance-model` spec) are what chunk 13's SHACL shapes encode as `minCount`/target-class constraints. This change documents them as requirements; chunk 13 turns them into a write-time gate.

### D8 — Idempotency reconciliation: fact stores stay idempotent; audit graphs are per-run

The loader (`Idempotent re-runs across both stores`) and mention writer (`Additive write to urn:msr:data, idempotent across re-runs`) both guarantee that a repeat run leaves `urn:msr:data` and SQLite byte-for-byte unchanged. Adding provenance preserves this **for the fact stores**: the added triples in `urn:msr:data` — the `prov:wasDerivedFrom`/`prov:wasGeneratedBy` edges (referencing a _deterministic_ Activity IRI, D2), the self-contained `Dataset` node, and the fact individuals — are all deterministic, so re-assertion is a set-semantics no-op.

The one non-idempotent element is the wall-clock `Activity` **record** (`prov:startedAtTime`/`endedAtTime` differ per run). It is isolated into the **timestamped run graph** `urn:msr:run:<pipeline>/<ts>`; a repeat wall-clock run appends a new timestamped audit graph. This is intended (each run is a distinct audit record) and is **explicitly outside** the fact-store idempotency guarantee. The existing tests (which count `urn:msr:data` and `measurement_value`) stay green because nothing they measure changes; the modified idempotency requirements below make the audit-graph carve-out explicit. **Alternative rejected:** a timestamped Activity IRI referenced from `urn:msr:data` — it would make the `wasGeneratedBy` edge change every run and break the tested fact-store idempotency. Multi-run audit disambiguation (the thing a timestamped IRI would buy) is a non-issue under the wholesale-reload operational model.

## Risks / Trade-offs

- **Provenance emitted but not yet enforced** → until chunk 13 lands, a writer bug could still emit an under-provenanced triple. Mitigation: unit tests here assert every emitted measurement/mention carries the required edges; chunk 13 adds the DB-side gate. Sequencing (12 → 13) is deliberate.
- **Named-graph rollback is not a true unit** (D2) → dropping `urn:msr:run:*` leaves facts in `urn:msr:data`. Mitigation: documented; POC rollback is wholesale-replace; revisit with the D1 layout change.
- **Ontology version bump invalidates the cached KG-schema prompt** → the PROV-O slice bumps `owl:versionInfo`, forcing a prompt rebuild on next request. This is the intended mechanism (design D4 of the agent), not a regression; the prompt already rebuilds on version bump.
- **Locator-scan false negatives** (D5) → a script that reads a locator via string concatenation would not match. Mitigation: acceptable at POC scale — the model is instructed to embed the literal locator; the common path (literal locator in the query) is covered, and a miss degrades to a less-specific (not incorrect) provenance chain.
- **Loader is the sole source of the NIST source node** (D3) → with the seed already gone, the `Dataset`/DOI and the measurements exist only if the loader emits them; a loader bug loses them entirely (no seed fallback). Mitigation: reuse the existing `formatFloat`/`quoteLiteral` conventions, pin the DOI constant, and cover with a "loader emits a self-contained Dataset + DOI that every measurement's `prov:wasDerivedFrom` resolves to" test and the idempotency test.
- **Ordering dependency** → `provenance-model` assumes `ground-demo-in-real-docs` has already run (seed gone, grounding on `linksTo`). Running it before `ground-demo` would reintroduce seed-coexistence issues. Mitigation: the sequence `ground-demo → provenance-model → shacl` is documented in both changes.

## Migration Plan

No data migration. POC data is disposable and replaced wholesale on every load. Deploy order: `ground-demo-in-real-docs` (seed removed, grounding reworked) → **this change** (vocabulary + emitters + source nodes + Activity trail) → `shacl-validation` (chunk 13, the write-time gate). Rollback: revert the change and re-run `load-nist` + `ingest` + `link` to rebuild the graph (writers are additive/idempotent).

## Resolved Questions

- **Bulk-load validation strategy** — *Resolved (user):* use whatever is easiest in GraphDB. Concretely that is GraphDB's default per-transaction `ShaclSail` validation on commit, with no bespoke bulk-import path: the loader/extraction writes are small at POC scale (four NIST files; ~12 curated documents), so a single commit-time validation per write is sufficient. If a batch ever measurably slows, GraphDB's load-then-validate option is the fallback. Owned by chunk 13; recorded here because this change fixes the emitters' output volume.
- **Human-reviewer Agent IRI shape** — *Resolved (user):* accepted. This change defines only the `agent:loader@<version>` and `agent:extraction@<version>` agents; the human-reviewer approval `Activity`/`Agent` IRI is settled when the HITL surface (chunk 9) is built, reusing this vocabulary.
- **The hand-curated seed** — *Resolved (user):* the seed A-Box (`example-flibe.ttl`) is removed **entirely** — scaffolding and all — with the graph and demo grounded exclusively in real data. That re-architecture (seed removal + reworking agent grounding onto real `msr:Mention` links + re-deriving reactor/role facts from real text) is the separate change `ground-demo-in-real-docs`, sequenced after this one. `provenance-model` does not touch the seed; it makes the real-data writers self-sufficient so the removal is clean.
