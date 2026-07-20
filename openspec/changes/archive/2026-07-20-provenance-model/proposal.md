## Why

The project's central principle — every fact in the graph and every answer the agent gives must be traceable to a source — is not actually a requirement anywhere. Provenance exists only as scattered per-artifact conventions: the NIST loader emits `prov:wasDerivedFrom` pointing at a `Dataset` node/DOI that lived only in the hand-curated seed (now removed); the agent can return a number with zero provenance events (emission depends on the model naming a SPARQL variable a certain way); extraction-written mentions carry no generating activity. This change makes provenance a **first-class, required invariant** across the write path, the answer path, and the compute path — the trust foundation (Phase P3.5, chunk 12) that gates P4 so the pipelines that mass-produce facts are born provenance-complete rather than retrofitted. See `docs/PROVENANCE_AND_TRUST_DESIGN.md`.

## What Changes

- **PROV-O slice in the ontology** — add `prov:Activity`, `prov:Agent`, `prov:wasGeneratedBy`, `prov:startedAtTime`/`prov:endedAtTime`, `prov:wasAssociatedWith`, and `owl:versionInfo` usage so every fact-bearing individual can declare who/what/when produced it. Bumps `owl:versionInfo`.
- **Complete + required provenance on every pipeline-asserted instance individual** — not just measurements/mentions but also the `MoltenSalt`, `Constituent`, and `ChemicalCompound` the loader mints: each carries `prov:wasGeneratedBy` a run `Activity` (with an `Agent`, ontology version, and timestamps) and `prov:wasDerivedFrom` its source. Source entities (`Dataset`/`Document`) are derivation *roots*, identified by their real external id (DOI / report number). The ontology TBox and SKOS vocab are excluded by design — they are definitional (not source-derived facts) and versioned by `owl:versionInfo`, not per-node PROV. (No `msr:citedIn`: a truthful measurement↔document citation has no per-row source in NIST SRD-27 — see What Changes / design D3.)
- **Per-source / per-run named graphs** — each source (`urn:msr:src:*`) and pipeline run (`urn:msr:run:*`) gets its own named graph holding a single PROV `Activity` record, giving a coarse audit dimension ("everything from source X / run Y") that complements the property-level edges. Written via SPARQL `Update` (explicit `GRAPH` targets), not `PutGraph`.
- **Retrofit the NIST loader** — emit a **self-contained** `msr:Dataset` node with its DOI and the FLiBe measurement (plus the catalog salts/constituents/compounds), all carrying `prov:wasDerivedFrom` the dataset and full generation provenance; attach a loader-run `Activity`. The loader is the single, real source of NIST-derived data (the seed is already gone). **No `msr:citedIn`**: NIST SRD-27 carries no per-row citation, so a truthful measurement↔document citation is deferred to chunk-7 citation extraction (design D3).
- **Assumes an all-real, seed-free graph** — the hand-curated seed (`ontology/example-flibe.ttl`) is already removed by the prerequisite change `ground-demo-in-real-docs`, which lands **first** (see Impact). So this change adds provenance to a graph populated exclusively by the real-data writers — no seed to coexist with or work around. It closes the interim provenance gap that `ground-demo` leaves: it defines the self-contained `Dataset` node (+DOI) the loader's `wasDerivedFrom` points at, plus the generation `Activity` trail.
- **Retrofit the extraction writers** — mention and document writers stamp `prov:wasGeneratedBy` an extraction-run `Activity` (agent `agent:extraction@<version>`, timestamps, ontology version) and write under the run graph.
- **Answer-time enforcement in the agent** — the loop stamps **every** answer grounded-vs-ungrounded and returns the provenance chain of the facts it used, enforced in `loop.go` and surfaced as a first-class trace event, so a bare number can no longer reach the user unmarked. **BREAKING** (trace contract): a new answer-stamp trace event is added to the streamed event set.
- **Compute-time linkage** — a `run_python` result references the `dataLocator`(s) the script read, tying a computed number to the grounded rows it derived from.

## Capabilities

### New Capabilities

- `provenance-model`: the cross-cutting provenance invariant — the PROV-O ontology slice, the requirement that every fact-bearing individual (measurement, mention) carries complete + required derivation and generation provenance, and the per-source/per-run named-graph audit dimension with `Activity` records. Defines the provenance vocabulary that chunks 13 (`shacl-validation`), 7, and 8 conform to.

### Modified Capabilities

- `nist-structured-loading`: loader must emit a self-contained `msr:Dataset` + DOI (load-order-independent) that every measurement's `prov:wasDerivedFrom` resolves to, and attach a loader-run `prov:Activity`. (No `msr:citedIn` — deferred to chunk-7; see design D3.)
- `mention-graph-writing`: written mentions must carry `prov:wasGeneratedBy` an extraction-run `Activity` (agent, ontology version, timestamps).
- `document-graph`: `Document` nodes must carry generation provenance from the ingest/extraction run `Activity`.
- `analysis-agent`: the loop must stamp every answer grounded-vs-ungrounded, refuse to present a numeric result without a provenance chain, and reference the `dataLocator`(s) a `run_python` script read.
- `chat-api`: the streamed trace contract must include the grounded/ungrounded answer stamp and the aggregated provenance chain of facts used.

## Impact

- **Ontology**: `ontology/msr.ttl` (PROV-O slice, `owl:versionInfo` bump). `ontology/example-flibe.ttl` no longer exists (removed by the prerequisite `ground-demo-in-real-docs`).
- **Loader**: `cmd/loader/nist.go` (self-contained dataset/DOI, `prov:wasDerivedFrom` on all instance individuals, loader Activity, source/run graph), `cmd/loader/seed.go`.
- **Extraction**: `extraction/src/msr_extraction/mentions.py`, `documents.py` (extraction-run Activity + run graph).
- **Agent**: `internal/agent/loop.go` (answer-time stamp), `events.go` (new event type), `python.go` (compute-time locator linkage), `sparql.go`.
- **Downstream (contract only)**: defines the provenance vocabulary consumed by `shacl-validation` (chunk 13), `extract-property-relations` (7), and `mine-ontology-candidates` (8). The cached KG-schema prompt is rebuilt on the `owl:versionInfo` bump.
- **No migration**: POC data is disposable and replaced wholesale; every writer emits provenance-complete data — no grandfathering.
- **Prerequisite change** `ground-demo-in-real-docs`: lands **before** this one. It removes `example-flibe.ttl` entirely and re-grounds the agent on real `msr:Mention → linksTo` edges (no `skos:closeMatch`), and trims the orphaned role/reactor TBox. Sequence: `ground-demo` → this → `shacl-validation` (chunk 13) — *make the data real → make it provenanced → enforce it*.
