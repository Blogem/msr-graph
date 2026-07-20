## 1. Enable SHACL on the `msr` repository

- [ ] 1.1 Rewrite `deploy/graphdb/msr-repo-config.ttl` per design D1: wrap the sail as `sail:sailType "graphdb:ShaclSail"`, move the existing `graphdb:Sail` config (incl. `graphdb:ruleset "empty"` — D2) verbatim under `sail:delegate [ … ]`, and add the `sail-shacl:` params (`validationEnabled true`, `shapesGraph <http://rdf4j.org/schema/rdf4j#SHACLShapeGraph>`, `parallelValidation`, `serializableValidation`, `logValidationViolations true`, `undefinedTargetValidatesAllSubjects false`, `rdfsSubClassReasoning false`, `transactionalValidationLimit "500000"^^xsd:long`). Update the header comment to explain the SHACL block.
- [ ] 1.2 Confirm the sail-type literal against GraphDB 11.4.2: create a throwaway SHACL repo via the workbench UI, download its config, and diff the sail type (`graphdb:ShaclSail` vs `rdf4j:ShaclSail`) and property names against 1.1 — no guessing.
- [ ] 1.3 Confirm `scripts/ensure-repo.sh` still creates the repo idempotently from the updated config (check-then-create unchanged).
- [ ] 1.4 Add the D7 pre-SHACL detection to `ensure-repo.sh`: when `msr` already exists, inspect its config (`GET /rest/repositories/msr`) for the `graphdb:ShaclSail` sail type / `sail-shacl:validationEnabled`; if absent, fail with guidance to drop the `graphdb-data` volume and recreate.

## 2. Author the shape catalogue

- [ ] 2.1 Create the shapes artifact (`deploy/graphdb/msr-shapes.ttl`) with the `msr:PropertyMeasurement` provenance+completeness shape (`prov:wasDerivedFrom`, `prov:wasGeneratedBy`, `msr:dataLocator`, `msr:forProperty`, `msr:ofSalt`, `msr:hasUnit`, `msr:equationForm` — minCount 1 each). Do **not** require `msr:citedIn`: no writer asserts a per-row citation yet (deferred to chunk 7 per the landed chunk 12 design D3), so requiring it would reject every real measurement.
- [ ] 2.2 Add the `msr:Mention` shape (`msr:inDocument`, `msr:startOffset`, `msr:endOffset`, `msr:surfaceForm`, `prov:wasDerivedFrom`, `prov:wasGeneratedBy` — minCount 1 each; every mention writer already emits all six per the landed `provenance-model`).
- [ ] 2.3 Add the valid-temperature-range shape via a `sh:sparql` constraint whose `SELECT` filters `validTempMin > validTempMax` (and flags a half-populated range) — per D4, a filter inside `sh:sparql`, not an unsupported pairwise-comparison component.
- [ ] 2.4 Add the `msr:linksTo` target-kind shape: prefer Core `sh:class`/`sh:nodeKind` (matches explicit `rdf:type`, since inference is off — D4); use `sh:sparql` (confirmed supported) for the existence/expected-kind check where Core cannot express it.
- [ ] 2.5 Add the catalog-individual provenance shape targeting `msr:MoltenSalt`, `msr:Constituent`, and `msr:ChemicalCompound` (each requires `prov:wasGeneratedBy` + `prov:wasDerivedFrom`, minCount 1). The NIST loader — the only writer of these — emits both edges on every such individual per the landed `provenance-model`, so this enforces the invariant without rejecting valid writes.

## 3. Unit allowlist shape from single source of truth

- [ ] 3.1 Add a generation step that reads `ontology/qudt-units.json` and emits the `sh:in (...)` unit list into the shapes artifact (or a companion fragment loaded alongside it) so the shape and loader share one allowlist.
- [ ] 3.2 Wire the generation into the build/bootstrap so a stale hand-edited list cannot drift.

## 4. Install shapes during bootstrap

- [ ] 4.1 Add an idempotent shapes-load step to `scripts/ensure-repo.sh` that loads the catalogue into the reserved shapes graph (`http://rdf4j.org/schema/rdf4j#SHACLShapeGraph`) after the repo is healthy, via a Graph Store Protocol PUT (replace semantics ⇒ idempotent re-run); `DROP GRAPH`+`INSERT` fallback if PUT to the reserved graph misbehaves on 11.4.2.
- [ ] 4.2 Ensure `make up` runs the shapes-load step so a fresh stack enforces shapes without a manual step; document the volume-drop needed to upgrade an existing pre-SHACL volume.

## 5. Write-path validation reporting

- [ ] 5.1 In `internal/graph`, detect SHACL rejection responses (RDF4J `sh:ValidationReport` on commit failure) in `Client.Update` and `Client.PutGraph` and return a distinguishable validation error carrying the failing constraint(s) and focus node(s); keep writer interfaces stable.
- [ ] 5.2 Update `cmd/loader` (and note for extraction writers) to log/report a validation rejection legibly, distinct from other write failures.

## 6. Bulk-load strategy

- [ ] 6.1 Confirm per-transaction (incremental) validation is used (D6): sanity-check that a full seed + NIST + extraction load stays well under `transactionalValidationLimit` (500000) so it never falls back to whole-repository validation; note the observed transaction sizes in design.md. (Load-then-validate remains a documented fallback only.)

## 7. Tests

- [ ] 7.1 Opt-in GraphDB integration test: a `PropertyMeasurement` missing a required provenance/completeness property is rejected on commit with a validation report; a complete one is accepted.
- [ ] 7.2 Opt-in integration test: a `Mention` missing `inDocument` is rejected; a complete one is accepted.
- [ ] 7.3 Opt-in integration test: a non-allowlist `hasUnit` is rejected; an allowlisted unit is accepted (fixture derived from `qudt-units.json`).
- [ ] 7.4 Opt-in integration test: an inverted `validTempMin`/`validTempMax` is rejected; a well-ordered range is accepted.
- [ ] 7.5 Opt-in integration test: a dangling/wrong-kind `linksTo` is rejected; a well-formed link is accepted.
- [ ] 7.6 Test: shapes-graph load installs the catalogue into the reserved graph and is idempotent on re-run.
- [ ] 7.7 Test: `ensure-repo.sh` idempotently creates a SHACL-enabled repo (no-op on an already-SHACL-enabled repo) and fails with guidance when the existing repo is not SHACL-enabled (D7).
- [ ] 7.8 Unit test for the allowlist-generation step (3.1): the emitted `sh:in` list matches the IRIs in `ontology/qudt-units.json`.
- [ ] 7.9 Go test for the write-path validation-error typing (5.1): a simulated `sh:ValidationReport` response is classified as a validation error with constraint/focus-node detail.
- [ ] 7.10 Opt-in integration test: a `msr:MoltenSalt` / `msr:Constituent` / `msr:ChemicalCompound` missing `prov:wasGeneratedBy` or `prov:wasDerivedFrom` is rejected; a fully-provenanced one is accepted.

## 8. Documentation

- [ ] 8.1 Update `README.md` / relevant docs: SHACL is enforced on commit, how to read a rejection, and the volume-drop upgrade step.
- [ ] 8.2 Cross-check `docs/PROVENANCE_AND_TRUST_DESIGN.md` §2 and `docs/IMPLEMENTATION_PLAN.md` chunk 13 acceptance against the delivered shapes; note the resolved bulk-load decision.
