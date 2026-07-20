# Tasks — provenance-run-lineage

## 1. Graph client

- [x] 1.1 Add typed constant `Provenance GraphIRI = "urn:msr:provenance"` in `internal/graph/graph.go`. Do **not** add it to `CoreGraphs`. It is written via SPARQL `Update` (explicit `GRAPH` target), so it is deliberately absent from the `knownGraphs`/`PutGraph` allowlist.

## 2. NIST loader (`cmd/loader/nist.go`)

- [x] 2.1 Type the stable activity in `urn:msr:data`: in `buildInsertData`, emit `msrd:activity-loader-nist a prov:Activity ; prov:wasAssociatedWith <agent:loader@<version>> ; owl:versionInfo "<version>"` exactly once (no timestamps — deterministic, idempotent).
- [x] 2.2 Replace `buildRunGraphData` with a builder that targets `GRAPH <urn:msr:provenance>` and writes: (a) the per-run activity node `<urn:msr:run:loader/<ts>> a prov:Activity` with `prov:wasAssociatedWith <agent:loader@<version>>`, `prov:startedAtTime`/`prov:endedAtTime` (= `<ts>`), and `owl:versionInfo`; (b) one `<factIRI> prov:wasGeneratedBy <urn:msr:run:loader/<ts>>` edge for **every** emitted fact IRI (each `MoltenSalt`, `Constituent`, `ChemicalCompound`, `PropertyMeasurement`, and the `Dataset` node).
- [x] 2.3 Thread the emitted fact IRIs into the provenance builder (they are already enumerated/deduped in `buildInsertData`; expose the deduped IRI set so both builders share it and no fact is missed or double-listed).
- [x] 2.4 Remove the `urn:msr:src:nist-srd27` write (the `Dataset` node stays self-contained in `urn:msr:data`).
- [x] 2.5 Keep the builder pure (caller supplies `<ts>`, no `time.Now()` inside), matching the existing testability contract.

## 3. Extraction pipeline

- [x] 3.1 `provenance.py`: change `activity_insert_data` to write the per-run activity node into `GRAPH <urn:msr:provenance>`, using the per-run IRI `<urn:msr:run:extraction/<run_ts>>` as the subject (typed `prov:Activity`, agent, start/end, `owl:versionInfo`).
- [x] 3.2 `mentions.py`: for each written `msr:Mention` IRI, additionally emit `<mention> prov:wasGeneratedBy <urn:msr:run:extraction/<run_ts>>` into `GRAPH <urn:msr:provenance>` (keep the stable `msrd:activity-extraction` edge in `urn:msr:data` unchanged).
- [x] 3.3 `documents.py`: for each written `msr:Document` IRI, emit the analogous per-run generation edge into `urn:msr:provenance`.
- [x] 3.4 Ensure the single per-invocation `run_ts` is shared by the activity record and every generation edge of that run (one run → one per-run activity node).

## 4. Docs

- [x] 4.1 Update `docs/PROVENANCE_AND_TRUST_DESIGN.md` §1.2: describe the single `urn:msr:provenance` graph with per-run activity nodes + generation-lineage edges, and note it supersedes the archived `provenance-model` D8 per-run-graph approach.

## 5. Tests

### Go loader (`cmd/loader/nist_test.go`)

- [x] 5.1 Assert the provenance update targets `GRAPH <urn:msr:provenance>` and contains the per-run activity `<urn:msr:run:loader/<ts>>` with agent, start/end timestamps, and `owl:versionInfo`.
- [x] 5.2 Assert a `<factIRI> prov:wasGeneratedBy <urn:msr:run:loader/<ts>>` edge is emitted for every fact IRI in the corresponding `buildInsertData` output (count parity: every emitted fact has exactly one generation edge in the run's provenance write).
- [x] 5.3 Assert `buildInsertData` types the stable `msrd:activity-loader-nist a prov:Activity` with no timestamp literals (idempotency of `urn:msr:data`).
- [x] 5.4 Assert no `urn:msr:src:` graph target appears in either builder's output.
- [x] 5.5 Two distinct `<ts>` values produce two distinct per-run activity IRIs and two disjoint sets of generation edges (append-only lineage).

### Extraction (`extraction`, run via `uv run --extra test python -m pytest`)

- [x] 5.6 `provenance.py`: `activity_insert_data(run_ts)` targets `GRAPH <urn:msr:provenance>` with subject `<urn:msr:run:extraction/<run_ts>>`; distinct `run_ts` → distinct subject.
- [x] 5.7 `mentions.py`/`documents.py`: a written mention/document IRI gets a `prov:wasGeneratedBy <urn:msr:run:extraction/<run_ts>>` edge in the `urn:msr:provenance` update, and its stable `msrd:activity-extraction` edge in `urn:msr:data` is unchanged.

### Integration (monkeypatched/opt-in, guarded by env per `core-dataset-access`)

- [x] 5.8 Loader integration test: `urn:msr:data` triple count is unchanged across a repeat run (existing guarantee still holds after the stable-activity typing is added).
- [x] 5.9 Lineage query test: after two loader runs (two `<ts>`), a re-asserted fact (e.g. the FLiBe salt) has **two** `prov:wasGeneratedBy` edges in `urn:msr:provenance` (one per run) and still exactly **one** stable `wasGeneratedBy` in a core-scoped read.
- [x] 5.10 Core-read isolation test: a core-scoped `Select` for a fact's `prov:wasGeneratedBy` returns exactly the single stable activity (the per-run lineage in `urn:msr:provenance` does not leak into core reads).

## 6. Validation

- [x] 6.1 `openspec validate provenance-run-lineage --strict` passes.
- [x] 6.2 Full Go test suite green; extraction suite green.
