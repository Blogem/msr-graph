# Proposal: load-nist-structured-data

## Why

The stores are live but empty of real measurements: only the hand-authored FLiBe A-Box seed exists. The grounded-analysis demo (chunk 4) needs the fluoride subset of the NIST Molten Salts DB (SRD 27) as queryable catalog triples plus resolvable coefficient rows, and chunk 6's NER must link text mentions to loaded salt individuals. This change lands that structured spine and pins the canonical salt-naming contract that both the Go loader and chunk 6's Python normalizer must honor.

## What Changes

- **Vendor the 4 NIST SRD 27 CSVs** (`density`, `conductivity`, `s-tension`, `viscosity`) into `data/nist/` (committed; already gitignore-excepted), with the dataset DOI recorded.
- **Add a `loader nist` subcommand** that ingests those files end-to-end: parse rows, apply the fluoride-subset filter, canonicalize salt formula + composition, write coefficient rows to SQLite (`source='nist'`), and emit `MoltenSalt` / `Constituent` / `PropertyMeasurement` catalog triples to `urn:msr:data` via `internal/graph`. Numbers stay in SQLite; the graph holds metadata + `dataLocator`.
- **Canonical salt naming (Go implementation)**: a formula + composition parser producing the contract's canonical form (components alphabetized, composition values reordered in lockstep, one-decimal mole %, e.g. `LiF-BeF2,34.0-66.0` → `BeF2-LiF | 66.0-34.0`), including positional-vs-range mole-% disambiguation and equation-form mapping (`P1/P2/P3/+E/DP`).
- **Author the shared canonicalization fixture** `testdata/salt-canonicalization.json` (raw → canonical cases) that chunk 6's Python normalizer must also pass — the drift guard for the deliberately-duplicated rule.
- **Vendor a QUDT unit/quantity-kind allowlist** and validate every emitted unit IRI against it, failing loudly on unknowns (settles the `unit:S-PER-CentiM` spelling question from `ONTOLOGY.md`).
- **Deterministic IRIs, no blank nodes, idempotent re-runs**: salt/constituent/measurement IRIs mint identically to the seed A-Box, so re-asserting seed salts is a no-op and SQLite writes are upsert-by-locator.
- **Answer DATA_SCOPE open items 1–3**: record fluoride row counts per property file, confirm FLiNaK + MSRE-coolant FLiBe row presence, and verify equation forms.

## Capabilities

### New Capabilities

- `nist-structured-loading`: the `loader nist` subcommand — vendored NIST CSV ingest, fluoride-subset filter, equation-form mapping, coefficient rows written to `measurement_value` (`source='nist'`, contract locator), and `MoltenSalt`/`Constituent`/`PropertyMeasurement` catalog triples emitted to `urn:msr:data`; idempotent across re-runs.
- `salt-canonicalization`: the Go salt formula + composition parser and canonical-form normalizer (alphabetized components, lockstep-reordered compositions, one-decimal mole %, positional-vs-range disambiguation, deterministic IRI minting) plus the authored shared fixture `testdata/salt-canonicalization.json`.
- `qudt-unit-allowlist`: the vendored QUDT unit/quantity-kind allowlist and the loader's validate-or-fail guard applied to every emitted unit IRI.

### Modified Capabilities

- `measurement-store`: adds an idempotent upsert-by-locator write path (`INSERT OR REPLACE` on the `locator` primary key) so the loader (and later chunk 7) writes rows through `internal/store` rather than ad-hoc SQL. Chunk 1 created only schema + connection settings.

## Impact

- **New code**: `cmd/loader/nist.go` (+ parser/canonicalizer/filter/allowlist units), `internal/store` upsert path, wiring into `cmd/loader` dispatch and the `make` targets.
- **New data**: `data/nist/*.txt` (4 vendored CSVs), the vendored QUDT allowlist `ontology/qudt-units.json`, `testdata/salt-canonicalization.json`.
- **Stores**: `measurement_value` gains `source='nist'` rows; `urn:msr:data` gains catalog triples (re-asserting the seed FLiBe salts as a no-op).
- **Dependencies**: none new — Go stdlib CSV + existing `internal/graph` / `internal/store`; no LLM access.
- **Downstream**: produces the rows + triples chunk 4 reads, the salt individuals chunk 6 links mentions against and the fixture its normalizer must pass, and the QUDT allowlist chunk 8 reuses for proposal validation. Depends on chunk 1 (`bootstrap-graph-infra`).
