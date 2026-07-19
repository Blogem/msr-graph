# Tasks: load-nist-structured-data

## 1. Vendor source data

- [ ] 1.1 Download the four NIST SRD 27 property files (`density-csv.txt`, `conductivity-csv.txt`, `s-tension-csv.txt`, `viscosity-csv.txt`) and commit them under `data/nist/`; confirm exact file names + 13-column headers on parse
- [ ] 1.2 Record the dataset DOI (`10.18434/mds2-2298`) and public-domain provenance alongside the vendored files
- [ ] 1.3 Vendor the QUDT unit/quantity-kind allowlist (permitted `unit:`/`qk:` IRIs + property→canonical-unit mapping consistent with the ontology TBox) as the committed file `ontology/qudt-units.json`, reusable cross-language by chunk 8
- [ ] 1.4 Extend `ontology/msr.ttl` with the full NIST equation-form vocabulary (`Polynomial4`, `ExtendedArrhenius1`=E1, `ExtendedArrhenius2`=E2, `Isotherm1`–`Isotherm4`), an `msr:independentVariable` marker, and `msr:compositionComponent`; correct `msr:Arrhenius` to include the `8.31441` gas constant
- [ ] 1.5 Consolidate `ontology/example-flibe.ttl` so the FLiBe density measurement attaches to the coolant salt `msrd:salt-BeF2-LiF-34.0-66.0` (canonical `BeF2-LiF | 34.0-66.0`); remove the orphaned `salt-BeF2-LiF-66.0-34.0`; update the FLiBe constants in `internal/graph/seed_integration_test.go`

## 2. Salt canonicalization (`salt-canonicalization`)

- [ ] 2.1 Implement the salt formula + composition parser: split the `Salt` column into component compound tokens and the `Composition range` column into per-component mole-% values
- [ ] 2.2 Implement canonicalization: byte-wise ascending component sort, lockstep composition reorder, one-decimal mole-% formatting → canonical string (lockstep-reorder demonstration: raw `LiF-BeF2,34.0-66.0` → `BeF2-LiF | 66.0-34.0`; the real NIST FLiBe row `BeF2-LiF,34.0-66.0` is already sorted and canonicalizes unchanged to `BeF2-LiF | 34.0-66.0`)
- [ ] 2.3 Implement positional-vs-range disambiguation (count==components & sum≈100 → positional `moleFraction`; per-component min–max → `moleFractionMin/Max`; neither → flag for manual review, skip)
- [ ] 2.4 Implement deterministic IRI minting (salt `msrd:salt-{formula}-{composition}`, constituent `{salt-iri}-c-{compound}`, measurement `msrd:m-{locator-slug}`; no blank nodes; matches the seed A-Box)
- [ ] 2.5 Author the shared fixture `testdata/salt-canonicalization.json` (raw→canonical string + ordered mole-%), covering the FLiBe case and a ternary reordering case
- [ ] 2.6 Parse and canonicalize composition-isotherm (`I*`) rows as range-composition salts (`moleFractionMin/Max`), including the `X-Y COMPONENT` composition-range format and the range-salt IRI rule (`msrd:salt-KF-ZrF4-ZrF4-0.0-33.3`)

## 3. NIST row mapping (`nist-structured-loading`)

- [ ] 3.1 Implement equation-form mapping (`P1→Linear`, `P2→Polynomial2`, `P3→Polynomial3`, `+E→Arrhenius`, `DP→DiscretePoint`); fail loudly on unknown codes
- [ ] 3.2 Implement the fluoride-subset filter (every component a fluoride of a cation in {Li,Be,Na,K,Zr,U,Th}); count out-of-scope (chloride/mixed-anion) rows and flag unparseable ones — never write either
- [ ] 3.3 Map kept rows to the `measurement_value` column layout (`c0..c4 ← Data1..5`, `t_min/t_max`, `equation_form`, `uncertainty`, `source='nist'`, canonical `salt`, `property`, locator `nist-srd27/{property}#{canonical-salt}`)
- [ ] 3.4 Map the full documented equation-form set (`P1 P2 P3 P4 +E E1 E2 DP I1 I2 I3 I4`); only a code outside this set is a fatal unknown-code error

## 4. QUDT unit allowlist guard (`qudt-unit-allowlist`)

- [ ] 4.1 Load the vendored allowlist and resolve each property's canonical unit through it
- [ ] 4.2 Validate every emitted `hasUnit` IRI against the allowlist; abort the run with an error naming any IRI not present

## 5. Measurement store upsert (`measurement-store`)

- [ ] 5.1 Add a typed `MeasurementRow` and an idempotent upsert (`INSERT … ON CONFLICT(locator) DO UPDATE`) to `internal/store`, writing through `store.Open` (pinned `journal_mode=DELETE` / `busy_timeout`)
- [ ] 5.2 Batch rows in a single transaction; ensure re-upsert of identical locators leaves row count and values unchanged

## 6. `loader nist` orchestration (`nist-structured-loading`)

- [ ] 6.1 Add the `nist` subcommand to `cmd/loader` dispatch (alongside `seed` / `init-db`) with config for `data/nist/` and the SQLite path
- [ ] 6.2 Wire the pipeline: read files → filter → parse/canonicalize → upsert SQLite rows → emit catalog triples
- [ ] 6.3 Emit `MoltenSalt` / `Constituent` / `PropertyMeasurement` triples (`ofSalt`, `forProperty`, `hasUnit`, `equationForm`, `validTempMin/Max`, `dataLocator`, `prov:wasDerivedFrom`) into `urn:msr:data` via additive SPARQL `INSERT DATA` through `internal/graph` (never `PutGraph`)
- [ ] 6.4 Print the completion run summary (per file: read / kept / out-of-scope / flagged; distinct canonical salts; equation forms seen)

## 7. Wiring & docs

- [ ] 7.1 Add a `make load-nist` target (one-shot `loader nist` run; chained after `load-seed` so a clean rebuild is seed→nist); update the README bootstrap order
- [ ] 7.2 Record `DATA_SCOPE.md` open items 1–3 from the real parse (fluoride row counts per file; FLiNaK + MSRE-coolant FLiBe presence; equation forms verified against `molten-salt-data.pdf`)

## 8. Tests

- [ ] 8.1 Table-driven canonicalization tests driven by `testdata/salt-canonicalization.json` (Go must pass every case) plus pure canonicalizer/parser cases (pure salt, ternary reorder)
- [ ] 8.2 Positional-vs-range disambiguation tests, including the manual-review flag path
- [ ] 8.3 Equation-form mapping tests (`P1/P2/P3/+E/DP`; unknown code → error)
- [ ] 8.4 Fluoride-filter tests (rejects chlorides + mixed-anion salts; counts out-of-scope; flags unparseable)
- [ ] 8.5 QUDT unit-allowlist guard tests (known unit passes; unknown IRI aborts with a naming error)
- [ ] 8.6 `internal/store` upsert tests (insert, re-upsert no-op on count, update-in-place on changed value)
- [ ] 8.7 Integration test (reuse chunk 1's `GRAPHDB_REQUIRED` helper): run `loader nist` against dockerized GraphDB + temp SQLite → FLiBe density `c0=2.413, c1=-4.88e-4` in SQLite; SPARQL returns the FLiBe density `PropertyMeasurement` with a resolvable locator; no chloride rows; seed `hasRole`/`usedIn` edges preserved
- [ ] 8.8 Loader idempotency integration test (second run → identical `urn:msr:data` triple count and `measurement_value` row count; anchor salts FLiBe-coolant + FLiNaK present)
- [ ] 8.9 Isotherm/range-composition tests: `I*` code → `Isotherm{n}` mapping, `X-Y COMPONENT` parsing, range-salt canonicalization + IRI, `moleFractionMin/Max` constituents
