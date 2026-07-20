## Why

The `provenance-model` change (archived) records, for every fact, a **stable per-pipeline** `prov:Activity` (`msrd:activity-loader-nist`, `msrd:activity-extraction`) via `prov:wasGeneratedBy` in `urn:msr:data`, and writes a timestamped `Activity` **record** into a fresh per-run named graph `urn:msr:run:<pipeline>/<ts>`. That design (archived design D8) deliberately traded away **per-run lineage**: because the fact→activity edge collapses onto one stable IRI and the run graphs record only "a run happened at T" (never *which* facts a run touched), there is no way to answer "which run(s) produced this fact?" — the information is not stored, so no query recovers it.

It also produces the symptom that motivated this change: one new `urn:msr:run:*` graph accumulates **per load**, cluttering the GraphDB graph list, while each such graph holds nothing but a near-empty `Activity` stub.

This change adds true per-run lineage and, in doing so, removes the per-run graph proliferation.

## What Changes

- **Per-run activity node + generation lineage.** Each pipeline run mints a **per-run** `prov:Activity` IRI — reusing the existing run identifier `urn:msr:run:<pipeline>/<ts>` now as a *node* (not a graph name) — carrying the run's agent, `startedAtTime`/`endedAtTime`, and ontology `owl:versionInfo`. For **every fact the run asserts**, the run records `<fact> prov:wasGeneratedBy <urn:msr:run:<pipeline>/<ts>>`. A fact asserted by N runs therefore accumulates N generation edges, one per run — that set *is* the lineage.
- **Single `urn:msr:provenance` audit graph replaces the per-run/per-source graphs.** All per-run activity records and generation edges live in one graph `urn:msr:provenance`. The per-run graphs `urn:msr:run:<pipeline>/<ts>` and the per-source graph `urn:msr:src:*` are removed: the fact→run edge's *object* already identifies the run, so a distinct named graph per run added clutter without adding queryability, and the `urn:msr:src:*` `Dataset` copy was redundant (the self-contained `Dataset` node already lives in `urn:msr:data`).
- **"Touched" (asserted) semantics.** A run logs a generation edge for every fact it asserts, **including facts already present** (a no-op against `urn:msr:data`). This is the honest statement "run R asserted F at time T", needs no read-before-write, and yields full multi-run history. (The narrower "which run *first created* F" is a distinct question deferred until a real need — see design D3.)
- **`urn:msr:data` unchanged and still idempotent.** Facts keep their deterministic `prov:wasDerivedFrom` and their **stable** `prov:wasGeneratedBy msrd:activity-<pipeline>` edge; the stable per-pipeline `Activity` is additionally typed/attributed once in `urn:msr:data` (no timestamps, so still a set-semantics no-op). The idempotency boundary moves from `urn:msr:run:*` to `urn:msr:provenance`, which is explicitly append-only.
- **Core reads and the agent are untouched.** `urn:msr:provenance` is outside `CoreGraphs`, so grounding/answer-time queries exclude it automatically and continue to see exactly one `wasGeneratedBy` per fact. Per-run lineage is opt-in via an explicit `GRAPH <urn:msr:provenance>` query. A typed `graph.Provenance` constant is added.

## Capabilities

### Modified Capabilities

- `provenance-model`: replaces the per-source/per-run named-graph audit dimension with a single `urn:msr:provenance` graph; adds the per-run activity node + per-run generation-lineage edges; splits the activity model into a stable per-pipeline IRI (in `urn:msr:data`, idempotent) and a per-run IRI (in `urn:msr:provenance`, timestamped).
- `nist-structured-loading`: the loader writes its per-run `Activity` and one generation edge per emitted fact into `urn:msr:provenance` (not `urn:msr:run:loader/<ts>`); the idempotency guarantee's exempt store changes from `urn:msr:run:*` to `urn:msr:provenance`.
- `mention-graph-writing`: the extraction linker writes its per-run `Activity` and one generation edge per written `msr:Mention` into `urn:msr:provenance`.
- `document-graph`: document ingest writes a per-run generation edge per `msr:Document` into `urn:msr:provenance`.
- `core-dataset-access`: `urn:msr:provenance` is a typed graph constant, excluded from core reads.

## Impact

- **Loader**: `cmd/loader/nist.go` (`buildRunGraphData` → build the `urn:msr:provenance` update: per-run activity + generation edges over all emitted fact IRIs; drop the `urn:msr:src:*` write; type the stable activity in `urn:msr:data`).
- **Extraction**: `extraction/src/msr_extraction/provenance.py` (per-run activity into `urn:msr:provenance`), `mentions.py` / `documents.py` (emit generation edges for each written IRI).
- **Graph client**: `internal/graph/graph.go` (add `Provenance` typed constant; it is *not* added to `CoreGraphs`).
- **Docs**: `docs/PROVENANCE_AND_TRUST_DESIGN.md` §1.2 (revise the named-graph-per-run description) and note the archived `provenance-model` D8 revision.
- **Downstream (contract only)**: `shacl-validation` (chunk 13) shape catalogue targets `urn:msr:provenance` for run/lineage shapes rather than `urn:msr:run:*`.
- **No migration**: POC data is disposable. `urn:msr:provenance` is append-only across loads by design (that is what makes cross-run lineage meaningful); a full teardown clears it with everything else. Pre-existing `urn:msr:run:*` / `urn:msr:src:*` graphs from earlier loads are orphaned and removed on the next clean repo rebuild.
- **Not affected**: `analysis-agent` / `chat-api` — the answer-time stamp and trace contract are unchanged because core reads still see the single stable generation edge.
