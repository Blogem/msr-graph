## 1. Ontology PROV-O slice

- [x] 1.1 Add the PROV-O slice to `ontology/msr.ttl`: declare `prov:Activity` and `prov:Agent` as usable classes and the properties `prov:wasGeneratedBy`, `prov:wasAssociatedWith`, `prov:startedAtTime`, `prov:endedAtTime` (alongside the existing `prov:wasDerivedFrom` and `msr:Document`/`msr:Dataset ⊑ prov:Entity`)
- [x] 1.2 Bump the ontology `owl:versionInfo` so the cached KG-schema prompt rebuilds on next use
- [x] 1.3 Verify `make load-seed` loads the slice into `urn:msr:ontology` (class + property triples present)

## 2. NIST loader retrofit (`cmd/loader/nist.go`)

- [x] 2.1 Add loader constants: the `msrd:nist-srd27` dataset IRI + DOI literal (`doi:10.18434/mds2-2298`), the deterministic Activity IRI `msrd:activity-loader-nist`, and the `agent:loader@<version>` agent IRI (no citing-document constant — see D3)
- [x] 2.2 Emit the self-contained `msr:Dataset` node (with DOI) in `buildInsertData` — the loader is the sole source now that the seed is gone; this defines the `msrd:nist-srd27` IRI the loader's `wasDerivedFrom` already references
- [x] 2.3 In `measurementTriples`, add `prov:wasGeneratedBy msrd:activity-loader-nist` to every measurement (retain existing `prov:wasDerivedFrom`); do **not** emit `msr:citedIn` — NIST SRD-27 has no per-row citation, so a truthful citation is deferred to chunk-7 (D3)
- [x] 2.3b Stamp the catalog individuals too — every emitted `msr:MoltenSalt`, `msr:Constituent`, and `msr:ChemicalCompound` carries `prov:wasGeneratedBy msrd:activity-loader-nist` + `prov:wasDerivedFrom msrd:nist-srd27` (they are asserted from NIST rows; scope is all instance data, not just measurements). Source `Dataset`/`Document` nodes carry their external id only (roots); TBox/vocab untouched
- [x] 2.4 After the `urn:msr:data` write, issue an additive `INSERT DATA { GRAPH <urn:msr:run:loader/<ts>> { … } }` (via `client.Update`, not `PutGraph`) writing the timestamped `Activity` record: `a prov:Activity`, `prov:wasAssociatedWith agent:loader@<version>`, `prov:startedAtTime`/`prov:endedAtTime`, and the ontology `owl:versionInfo`; associate `urn:msr:src:nist-srd27`
- [x] 2.5 Add the `prov:`/`dcterms:` prefixes needed to `insertPrefixes` if missing

## 3. Extraction writers retrofit (`extraction/src/msr_extraction`)

- [x] 3.1 Add a shared provenance helper (run timestamp generated once per CLI invocation; deterministic `msrd:activity-extraction` IRI; `agent:extraction@<version>`) and thread the run timestamp from the CLI (`cli.py`) to both writers
- [x] 3.2 In `mentions.py`, add `prov:wasGeneratedBy msrd:activity-extraction` to each `msr:Mention` triple block (keep IRIs deterministic, no blank nodes)
- [x] 3.3 In `documents.py`, add `prov:wasGeneratedBy msrd:activity-extraction` to each `msr:Document` triple block
- [x] 3.4 Write the timestamped extraction `Activity` record into `urn:msr:run:extraction/<ts>` via additive `INSERT DATA` with an explicit `GRAPH` target (reuse the existing SPARQL-UPDATE helper)

## 4. Agent answer-time enforcement (`internal/agent`)

- [x] 4.1 Add the `EventAnswer` (`"answer"`) event type and its payload (`grounded bool` + aggregated `ProvenanceEvent`) to `events.go`
- [x] 4.2 In `loop.go`, track per-turn whether any `ProvenanceEvent` was emitted and accumulate the union of its locators/citedIn/DOIs
- [x] 4.3 When the model returns its final answer (no tool calls), emit the `answer` stamp (grounded iff any provenance was seen; carrying the aggregated chain) before the terminating `done` event — enforced in the loop, independent of the model

## 5. Agent compute-time locator linkage (`internal/agent`)

- [x] 5.1 In `loop.go`, retain the set of `dataLocator` values surfaced by `sparql_query` this turn (from the emitted `ProvenanceEvent`s)
- [x] 5.2 When a `run_python` script runs, match the script source against that locator set and attach the matched locators to the run (new `DataLocators []string` field on `ScriptRunEvent`), folding them into the turn's aggregated chain
- [x] 5.3 Confirm no locator is attached when the script references none the turn grounded

## 6. Tests

- [x] 6.1 Go loader test (`cmd/loader/nist_test.go`): every emitted `PropertyMeasurement` carries `prov:wasDerivedFrom msrd:nist-srd27` + `prov:wasGeneratedBy msrd:activity-loader-nist` and **no** `msr:citedIn`, and the self-contained `Dataset`+DOI is present when loading into an empty data graph (no seed)
- [x] 6.2 Go loader idempotency test: a second `loader nist` run leaves the `urn:msr:data` triple count and `measurement_value` row count unchanged (deterministic Activity IRI + Dataset node re-assert as no-ops)
- [x] 6.3 Go agent-loop test (`loop_test.go`): a final answer with no provenance event is stamped `grounded: false`; a grounded turn emits an `answer` stamp with the aggregated chain before `done`
- [x] 6.4 Go event-schema test (`events.go`/`loop_test.go`): the `answer` event and the `script_run` `DataLocators` field serialize to the expected JSON shape (chat-API contract)
- [x] 6.5 Go compute-time test: a `run_python` whose script embeds a grounded locator records that locator on its run; a script embedding none records no locator
- [x] 6.6 Extraction pytest (`extraction/tests/test_*.py`): written mentions carry `prov:wasGeneratedBy msrd:activity-extraction`, and exactly one timestamped `Activity` record is written into `urn:msr:run:extraction/<ts>` per run (run via `cd extraction && uv run --extra test python -m pytest`)
- [x] 6.7 Extraction pytest: adding the generation edge keeps the mention write idempotent (same run id → unchanged `urn:msr:data` mention-triple count)

## 7. Validation & docs

- [x] 7.1 Run `go test ./...` and the extraction pytest suite; confirm green (grounding is `linksTo`-based from `ground-demo`, which lands first; this change adds provenance on top and must not regress it)
- [x] 7.2 `openspec validate provenance-model --strict` passes
- [x] 7.3 Update `docs/PROVENANCE_AND_TRUST_DESIGN.md` / `docs/IMPLEMENTATION_PLAN.md` cross-references: the trust sequence is `ground-demo-in-real-docs` → this → `shacl-validation`; note the deterministic-Activity-IRI + timestamped-run-graph decision (design D8) and the seed-already-gone assumption (design D9)
