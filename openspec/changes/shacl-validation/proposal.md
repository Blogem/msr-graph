## Why

The ontology declares `rdfs:domain`/`rdfs:range` constraints and a provenance model, but **nothing enforces them**: inference is off (architecture decision D2) and there are no SHACL shapes, so malformed or un-provenanced triples enter the `msr` repository silently. The trust foundation (Phase P3.5, `docs/PROVENANCE_AND_TRUST_DESIGN.md`) makes provenance a first-class invariant; this change adds the **validation layer** that turns those invariants — plus the ontology's data-quality constraints — into declarative gates the database enforces on commit, *before* the P4 pipelines start mass-producing facts.

This is chunk 13 of P3.5 and depends on chunk 12 `provenance-model` — **now landed and archived** — which added the PROV-O vocabulary (`prov:wasDerivedFrom`, `prov:wasGeneratedBy`) and made every writer stamp generation + derivation provenance on the individuals these shapes target. Shapes that require provenance predicates only make sense once those predicates are asserted by every writer, which is now the case. (`msr:citedIn` stays TBox-declared but unused — no writer asserts a per-row citation yet — so the shapes do **not** require it; that constraint is deferred to chunk 7.)

## What Changes

- **Enable GraphDB's native SHACL (`ShaclSail`) on the `msr` repository.** Wrap the vendored repo-config TTL (`deploy/graphdb/msr-repo-config.ttl`) sail as `graphdb:ShaclSail` with the current GraphDB sail under `sail:delegate` and the `sail-shacl:` params (see design D1) so `scripts/ensure-repo.sh` idempotently creates a SHACL-enabled repository. SHACL runs on transaction commit and works with inference off (D2 preserved). SHACL must be enabled at repository creation and cannot be added later. **BREAKING** for repository provisioning: the config surface changes, so a repository created by the old config must be recreated (POC data is disposable and replaced wholesale — no migration); `ensure-repo.sh` detects and warns on a pre-SHACL repo.
- **Author the shape catalogue** and load it into the reserved RDF4J shapes graph (`http://rdf4j.org/schema/rdf4j#SHACLShapeGraph`):
  - *Provenance invariants*: `msr:PropertyMeasurement` requires `prov:wasDerivedFrom`, `prov:wasGeneratedBy`, `msr:dataLocator`, `msr:forProperty`, `msr:ofSalt`, `msr:hasUnit`, `msr:equationForm` (all minCount 1) — but **not** `msr:citedIn`, which no writer asserts yet (deferred to chunk 7, per the landed chunk 12 `provenance-model` design D3); `msr:Mention` requires `msr:inDocument`, `msr:startOffset`, `msr:endOffset`, `msr:surfaceForm`, `prov:wasDerivedFrom`, `prov:wasGeneratedBy`.
  - *Data-quality invariants*: measurement unit ∈ the QUDT allowlist (`sh:in` derived from `ontology/qudt-units.json`); valid-temperature-range present and `validTempMin ≤ validTempMax`; `msr:linksTo` may only reference an existing target of the expected kind.
- **Wire shapes loading into the bootstrap** so a fresh stack comes up with shapes installed, and **surface validation reports legibly** so a rejected write reports *which* shape failed on *which* focus node, not an opaque 500.
- **Choose and document a bulk-load strategy** (incremental vs. load-then-validate) for the NIST/extraction batch writes, measuring cost against the pinned GraphDB 11.4.2.
- **Add opt-in GraphDB-required integration tests** asserting rejection of malformed/un-provenanced triples, acceptance of valid ones, a shapes-graph load test, and `ensure-repo` idempotency against a SHACL-enabled repo.

## Capabilities

### New Capabilities
- `shacl-validation`: The declarative validation layer — the SHACL shape catalogue (provenance + data-quality invariants), its residence in the reserved shapes graph, commit-time enforcement on the graph write path (rejection with a legible report), and the bulk-load validation strategy.

### Modified Capabilities
- `container-stack`: The "GraphDB repository created idempotently with inference disabled" requirement is extended — the vendored repo config now additionally enables SHACL validation and the bootstrap loads the shapes graph; idempotency and inference-off (D2) are preserved.

## Impact

- **Config / bootstrap**: `deploy/graphdb/msr-repo-config.ttl` (SHACL enablement — surface determined in design D1), `scripts/ensure-repo.sh` (shapes-graph load step + pre-SHACL detection), `docker-compose.yml` (GraphDB 11.4.2 unchanged).
- **New artifacts**: a shapes catalogue (Turtle) under `ontology/` or `deploy/graphdb/`; a shapes-generation step for the QUDT `sh:in` list sourced from `ontology/qudt-units.json`.
- **Write path**: `internal/graph` (`Client.Update`, `Client.PutGraph`) and its callers (`cmd/loader`, extraction writers) now receive commit-time validation errors; error handling/reporting is added, but writer *interfaces* stay stable.
- **Dependency**: requires the provenance vocabulary from chunk 12 `provenance-model` — **now landed and archived**, with every writer emitting `prov:wasDerivedFrom` + `prov:wasGeneratedBy` on measurements and mentions. The 12 → 13 sequence is satisfied, so the provenance-requiring shapes reject-if-absent without blocking valid writes.
- **Tests**: opt-in integration tests gated on a running GraphDB (consistent with existing `*_integration_test.go` in `internal/graph`).
- **Downstream**: P4 pipelines (chunks 7–8) inherit the enforced contract; chunk 9 HITL is reframed (SHACL is the enforcement gate, review is demonstration).
