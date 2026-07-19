# Design: load-nist-structured-data

## Context

Chunk 1 (`bootstrap-graph-infra`) shipped running stores, the `internal/graph` client (core-dataset reads, `Update`, `PutGraph`), `internal/store` (schema init + pinned connection settings), and a `cmd/loader` with `seed` / `init-db` subcommands. `cmd/loader/main.go` already notes that a `nist` subcommand is added by a later task and keeps the switch flat for it. The `measurement_value` table and the `urn:msr:data` graph exist but hold only the hand-authored FLiBe seed A-Box.

This change fills the structured spine. It is bound by the cross-cutting contracts in `docs/ARCHITECTURE.md` → _Runtime contracts_ and `docs/IMPLEMENTATION_PLAN.md` → _Cross-cutting contracts_, and by the row schema / filter / anchor salts in `docs/DATA_SCOPE.md` §1. Key fixed points it must honor:

- **Canonical salt naming** (alphabetized components, lockstep-reordered composition, one-decimal mole %); canonical form used in the IRI, locator, SQLite `salt` column, and `rdfs:label`.
- **Deterministic IRIs, no blank nodes**; the seed A-Box already follows the minting scheme, so re-asserting its salts is a set-semantics no-op.
- **Federation boundary**: numeric coefficients live in SQLite keyed by `dataLocator`; the graph holds salt/constituent/measurement metadata only.
- **SQLite runtime**: `journal_mode=DELETE`, `busy_timeout`, batch writers only — the loader opens through `internal/store`.
- The **QUDT unit-spelling question** from `ONTOLOGY.md` (esp. `unit:S-PER-CentiM`) is this chunk's to settle via a vendored allowlist.

## Goals / Non-Goals

**Goals:**

- Vendor the 4 NIST SRD 27 property CSVs under `data/nist/` and add `loader nist` to ingest them end-to-end.
- Parse + canonicalize salt formula and composition to the contract form; mint IRIs identical to the seed A-Box; write coefficient rows to `measurement_value` (`source='nist'`) and catalog triples to `urn:msr:data`, both idempotent.
- Enforce the fluoride-subset filter (per `DATA_SCOPE.md`) and a vendored QUDT unit allowlist (fail loudly on unknowns).
- Author `testdata/salt-canonicalization.json` as the Go/Python drift guard.
- Record `DATA_SCOPE.md` open items 1–3 (row counts, FLiNaK/FLiBe-coolant presence, equation forms).

**Non-Goals:**

- No text-derived (`source='document'`) values, mentions, or `citedIn` edges beyond what the seed already carries (chunks 6–7).
- No hand-curated role/reactor edges beyond the seed's — the loader cannot derive `hasRole` / `usedIn` from NIST and does not invent them.
- No Python normalizer (chunk 6) — this chunk only authors the shared fixture the Python side must later pass.
- No QUDT ontology import or unit _conversion_ — QUDT IRIs are referenced as values, validated against a flat vendored allowlist, not dereferenced.
- No changes to the `internal/graph` client API or the `measurement_value` schema columns (chunk 1 owns both).

## Decisions

### D1 — `loader nist` emits catalog triples with additive `INSERT DATA`, never `PutGraph`

The subcommand reads the 4 vendored CSVs, filters, parses/canonicalizes, then writes both stores. Catalog triples go to `urn:msr:data` via a SPARQL `INSERT DATA { GRAPH <urn:msr:data> { … } }` through `graph.Update` — **additive**, not graph-replace.

- _Why not `PutGraph`?_ `urn:msr:data` already holds the seed A-Box, including hand-curated `hasRole` / `usedIn` / `citedIn` edges the loader cannot regenerate from NIST. A Graph Store `PUT` replaces the whole graph and would wipe them. `INSERT DATA` re-asserts the seed's salts as a no-op (set semantics + deterministic IRIs) while adding the rest.
- _Why a `PutGraph` method but no `InsertGraph` method?_ The two wrap different HTTP protocols. `PutGraph` uses the SPARQL 1.1 **Graph Store Protocol** (`PUT` a raw `text/turtle` body), which streams a hand-authored `.ttl` seed file verbatim with whole-graph-replace semantics — and, being destructive, earns its own method plus the known-IRI guard. Inserts are ordinary SPARQL **UPDATE** (`INSERT DATA { GRAPH <g> {…} }`), already served by the general `graph.Update`; a dedicated `InsertGraph` would add nothing. (A small typed triple→`INSERT DATA` serializer to spare the loader hand-building SPARQL strings is a possible future ergonomic, not required here.)
- _Bootstrap ordering:_ seed **then** nist (`make load-seed` establishes the hand-curated facts via `PUT`, `make load-nist` adds catalog triples via `INSERT`). Re-running `load-seed` after `load-nist` re-`PUT`s `urn:msr:data` and drops NIST triples, so the documented order is seed→nist and both targets are idempotent; the combined `make load-nist` may depend on `load-seed` so a clean rebuild always chains correctly.
- _Alternative — separate `urn:msr:nist` graph:_ rejected; the contract keeps all core instance data in `urn:msr:data`, and a split would force the agent's core-dataset reads to widen.

### D2 — SQLite writes go through a new `internal/store` upsert (modified capability)

`internal/store` gains a typed `MeasurementRow` and an idempotent upsert (`INSERT … ON CONFLICT(locator) DO UPDATE`, equivalently `INSERT OR REPLACE`) keyed on the `locator` primary key. The loader batches rows in a transaction opened via `store.Open`.

- _Why in `store`, not the loader?_ Schema knowledge stays in one package (the contract says chunk 1 owns the DDL and later chunks extend that surface); chunk 7's Python writer mirrors the same upsert-by-locator semantics, so pinning it as a store requirement documents the shared contract. Keeps `journal_mode=DELETE` / `busy_timeout` enforced in code.
- _Column mapping:_ `c0..c4 ← Data1..5`, `t_min/t_max ← Tmin/Tmax`, `equation_form ←` mapped form label, `uncertainty ←` the Uncertainty column, `source='nist'`, `doc_id` NULL, `salt ←` canonical form, `property ←` property name, `locator ←` contract locator.
- _Denormalization note (deliberate POC simplification):_ `c0..c4` are five fixed positional coefficient slots, filled to the arity of the equation form (`Linear`→c0,c1; `Polynomial3`→c0..c3; `DiscretePoint`→c0=value,c1=temp); unused slots stay NULL. This is a denormalized wide table. A production model would normalize — either one measurement with an ordered child `measurement_coefficient(locator, index, value)` table (n rows per measurement) or a JSON coefficient array — to drop the fixed 5-slot ceiling. The wide table is kept because it is the chunk-1-owned contract schema and is simpler for the POC; the ceiling (max 5 coefficients) is a known constraint, adequate for the NIST forms in scope.

### D3 — Canonicalization: parse → alphabetize → lockstep-reorder → format, with a shared fixture

A pure `internal`-style package (e.g. `cmd/loader` sub-package or `internal/nist`) parses the `Salt` column into component compound tokens and the `Composition range` column into per-component mole-% values, then:

1. sorts components by byte-wise ascending order of the raw formula token (`BeF2` < `LiF`; `KF` < `LiF` < `NaF`),
2. reorders composition values in lockstep with the components,
3. formats each mole-% to one decimal (`34` → `34.0`).

Canonical string form: `BeF2-LiF | 34.0-66.0` (the real vendored row is `BeF2-LiF,34.0-66.0,P1,800,1080,,2.413,-4.88E-4` — components are already byte-canonical, so no reorder is needed); locator form uses `|` (`nist-srd27/density#BeF2-LiF|34.0-66.0`); IRI/slug form replaces `/ # |` with `-` (`msrd:salt-BeF2-LiF-34.0-66.0`, measurement `msrd:m-nist-srd27-density-BeF2-LiF-34.0-66.0`, constituent `{salt-iri}-c-{compound}`) — identical to the seed A-Box.

The raw→canonical cases are frozen in **`testdata/salt-canonicalization.json`** (this chunk authors it). Chunk 6's Python normalizer must pass the same file — the drift guard for the deliberately-duplicated rule. The fixture covers the canonical _string + ordered mole-%_ (what makes Go and Python land on one IRI), not range semantics.

- _Why byte-wise sort?_ Deterministic and reproducible in both Go and Python with no locale/collation dependency; the FLiBe seed (`BeF2-LiF`) and FLiNaK (`KF-LiF-NaF`) fall out correctly.
- _Locator disambiguation:_ a locator of the base form `nist-srd27/{property}#{canonical-salt}` is unique per (property, salt) pair only when the vendored data carries a single measurement for it. Where NIST carries several — e.g. BeF2 electrical conductivity has three DiscretePoint rows (990K, 1030K, 1070K) plus one Arrhenius fit (1090K), all sharing the same base locator — `internal/nist.Process` appends `@<tmin>` (the measurement's `TMin`, or `na` if absent) to every member of the colliding group, sorted by (TMin, EquationForm, original row order); a residual collision (identical TMin and EquationForm) is broken with a further stable `-<index>` suffix. This gives every NIST measurement its own SQLite row and graph node instead of silently collapsing siblings onto one locator. Singletons (the overwhelming majority, including both anchors: FLiBe density, FLiNaK density) keep the exact base locator, unchanged.

### D4 — Positional-vs-range mole-% disambiguation (equation-form code drives interpretation)

Confirmed on the real vendored files: the `Composition range` column's shape is not ambiguous per row — the **NIST `Data type` code** (see D5) tells the loader which interpretation applies, so the loader dispatches on the code rather than guessing from the values:

- **Isotherm codes (`I1`–`I4`)** → the row is a **composition isotherm**: the `Composition range` column carries a per-component range plus the varying component's name, e.g. `0.0-33.3 ZrF4` (trailing token names the varying compound; `0.0-33.3` is its mole-% range). Emit `moleFractionMin`/`moleFractionMax` per constituent — the varying component `0.0`→`0.333`, the complement `0.667`→`1.0` — and set `validTempMin = validTempMax = Tmin` (a single temperature; `Tmax` is empty on isotherm rows). See D5a for the range-composition salt and IRI shape.
- **Every other code** (`P1`–`P4`, `+E`, `E1`, `E2`, `DP`) → the row is **temperature-dependent** with a **positional single composition**: each value is that component's `moleFraction` (as a fraction, `66.0` → `0.66`). Values SHOULD sum to ≈100 within a **±2.0 mol% tolerance** — wide enough to admit the real `26.04-72.96` row (sums to 99.0) without misclassifying it. A positional row that fails the tolerance check is **flagged for manual review and skipped**, not silently dropped.

This replaces the earlier value-shape heuristic (count==components & sum≈100 vs. range) drafted before the real files were inspected: composition ranges turn out to appear only on `I*` rows, so the equation-form code alone disambiguates and the manual-review path is retained purely as a safety net for malformed positional rows.

### D5 — Equation-form mapping, full documented code set, fail-loud only outside it

The vendored fluoride subset turned out to carry more than the originally-assumed 5 codes: `E1` (pure BeF2 viscosity) and `I2`/`I3`/`I4` (KF-ZrF4 / NaF-ZrF4 composition isotherms) also appear. Rather than skip them, this chunk models the **full documented NIST equation-form set** from `molten-salt-data.pdf`, so the TBox and loader cover every code the dataset defines, not just the subset seen in chunk 1's seed. `T` is in Kelvin throughout; the exponential forms carry the `8.31441` gas constant; `C` is the isotherm's independent composition variable (mole % of the named varying component, see D5a):

| NIST code | EquationForm             | Formula                                | Independent variable                       | Coefficients |
| --------- | ------------------------ | --------------------------------------- | ------------------------------------------- | ------------- |
| `DP`      | `msr:DiscretePoint`      | value `D1` at `T = D2` K                | temperature (single point)                  | `c0`=value, `c1`=temperature |
| `+E`      | `msr:Arrhenius`          | `c0·exp(c1/(8.31441·T))`                | temperature                                 | `c0,c1` |
| `E1`      | `msr:ExtendedArrhenius1` | `c0·exp((c1/(8.31441·T)) + c2/T²)`      | temperature                                 | `c0,c1,c2` |
| `E2`      | `msr:ExtendedArrhenius2` | `c0·exp(c1/(8.31441·(T−c2)))`           | temperature                                 | `c0,c1,c2` |
| `P1`      | `msr:Linear`             | `c0 + c1·T`                             | temperature                                 | `c0,c1` |
| `P2`      | `msr:Polynomial2`        | `c0 + c1·T + c2·T²`                     | temperature                                 | `c0..c2` |
| `P3`      | `msr:Polynomial3`        | `c0 + c1·T + c2·T² + c3·T³`             | temperature                                 | `c0..c3` |
| `P4`      | `msr:Polynomial4`        | `c0 + c1·T + c2·T² + c3·T³ + c4·T⁴`     | temperature                                 | `c0..c4` |
| `I1`      | `msr:Isotherm1`          | `c0 + c1·C`                             | composition (mol % of the named component)  | `c0,c1` |
| `I2`      | `msr:Isotherm2`          | `c0 + c1·C + c2·C²`                     | composition                                 | `c0..c2` |
| `I3`      | `msr:Isotherm3`          | `c0 + c1·C + c2·C² + c3·C³`             | composition                                 | `c0..c3` |
| `I4`      | `msr:Isotherm4`          | `c0 + c1·C + c2·C² + c3·C³ + c4·C⁴`     | composition                                 | `c0..c4` |

Note: an earlier draft of this table had `+E → c0·exp(c1/T)`, omitting the `8.31441` gas-constant divisor documented in `molten-salt-data.pdf`; corrected above.

An unrecognized code — one **outside this full 12-entry set** — is a fatal error (genuinely out of the documented contract; previously any code beyond the 5-code subset was treated as unknown, which would have wrongly rejected `E1`/`I2`/`I3`/`I4`). Forms are verified against `molten-salt-data.pdf` on ingest (open item 3).

### D5a — Isotherm rows model as range-composition salts

Composition-isotherm rows (`I1`–`I4`) describe a family of measurements swept across a composition range at a single temperature, not one salt at one composition — so they need their own salt and IRI shape, distinct from point salts:

- **Range-composition salt & constituents**: the varying component's constituent gets `moleFractionMin`/`moleFractionMax` (e.g. `0.0`/`0.333` for `ZrF4` in `KF-ZrF4, 0.0-33.3 ZrF4`), and the complement gets the reciprocal range (`0.667`/`1.0`). The measurement carries `msr:compositionComponent` naming the varying compound, and each `EquationForm` individual carries `msr:independentVariable` (`temperature` or `composition`) so a consumer can tell which axis is swept without inspecting the NIST code. Isotherm measurements set `validTempMin = validTempMax` (the single temperature the sweep was run at); `Tmax` is not populated.
- **Range-salt IRI rule**: canonical form appends the varying component and its range after the formula — `KF-ZrF4 | ZrF4 0.0-33.3` — locator `nist-srd27/{property}#KF-ZrF4|ZrF4=0.0-33.3`, salt IRI `msrd:salt-KF-ZrF4-ZrF4-0.0-33.3`. Same `/ # |` → `-` slugging rule as point salts, extended with the varying-component name and `=`/`-` separators for the range. Only `KF-ZrF4` and `NaF-ZrF4` are in scope for isotherms in the vendored fluoride subset.

### D6 — Fluoride-subset filter

A row is kept iff **every** component parses as a fluoride compound (cation ∈ {Li, Be, Na, K, Zr, U, Th}, formula ends in `F`/`F2`/`F3`/`F4`, no other anion). Distinguish two rejection paths:

- **Out-of-scope** (chloride or mixed-anion salt, recognizable but excluded by scope) → filtered silently but **counted** in the run summary; never written.
- **Unparseable** (unknown cation, malformed formula/composition) → flagged for manual review in the summary.

A test asserts no chloride/mixed-anion rows reach either store.

### D7 — QUDT unit allowlist as the single source, validate every emitted IRI

A flat vendored allowlist — a **committed file at `ontology/qudt-units.json`** — enumerates the permitted `unit:` / `qk:` IRIs and the property→canonical-unit mapping (`density → unit:GM-PER-CentiM3`, `viscosity → unit:MilliPA-SEC`, `surfaceTension → unit:MilliN-PER-M`, `electricalConductivity → unit:S-PER-CentiM`), consistent with the ontology TBox `msr:canonicalUnit`. Every `hasUnit` IRI the loader emits is checked ∈ allowlist; an unknown IRI aborts the run.

- _Why an allowlist and not dereference QUDT?_ The contract references QUDT IRIs as values without importing QUDT; the allowlist is the flat vendored guard that settles the `S-PER-CentiM` spelling for the POC and fails loudly if a typo or a wrong property→unit assignment slips in. Chunk 8 reuses the same allowlist to validate proposed units.
- _Why a flat file and not the graph?_ No hard contract rule forces it, but three reasons: (1) it is an ingest-time **validation guard**, and sourcing it from the graph would make the loader query the graph to validate what it is about to write to the graph — circular and a needless round-trip; (2) it is the human-curated **ground truth** that settles spellings, independent of the TBox's `msr:canonicalUnit` (which is in the graph but could itself carry a typo); (3) `DATA_SCOPE.md` establishes the "reference, don't import" pattern — external catalogs (QUDT/INIS) are flat vendored lists outside the graph — and chunk 8's Python reuse is trivial with a committed file, awkward with a graph query. The loader MAY additionally cross-check the vendored list against `msr:canonicalUnit` in the TBox to catch drift between the two.

### D8 — DATA_SCOPE open items recorded from the real parse

On completion `loader nist` prints a summary: rows read / kept / out-of-scope / flagged per property file, the distinct canonical salts loaded, and the equation forms seen. Items 1–3 in `DATA_SCOPE.md` are updated with the actual numbers (fluoride counts per file, FLiNaK + FLiBe coolant (`BeF2-LiF` 34.0-66.0 mol%) presence confirmed, equation forms verified). An integration test asserts the FLiBe coolant salt and FLiNaK are present.

### D9 — Test strategy

Pure Go table-driven unit tests (no GraphDB): parser/canonicalizer against the shared fixture, positional-vs-range disambiguation (incl. the manual-review flag), equation-form mapping, fluoride filter (rejects chlorides + mixed-anion), unit-allowlist guard. Integration tests reuse chunk 1's `GRAPHDB_REQUIRED`-guarded helper: run `loader nist` against the dockerized GraphDB + a temp SQLite, then assert FLiBe density coefficients (`2.413, -4.88e-4`) in SQLite, a SPARQL FLiBe density `PropertyMeasurement` with a resolvable locator, no chloride rows, and idempotent re-run (triple + row counts identical).

## Risks / Trade-offs

- **Seed `PUT` after nist `INSERT` wipes NIST triples** → loader is strictly additive (`INSERT DATA`, never `PutGraph`); documented seed→nist ordering; combined target chains them; both idempotent so a re-run repairs state.
- **Go/Python canonicalization drift** → shared `testdata/salt-canonicalization.json` both test suites must pass; this chunk authors it, chunk 6 consumes it.
- **NIST composition range encoding — resolved** → the real parse confirmed ranges appear only on isotherm (`I*`) rows as `X-Y COMPONENT`; every other code carries a positional single composition. The ±2.0 mol% tolerance and the manual-review flag remain as a safety net for malformed positional rows (see D4).
- **`unit:S-PER-CentiM` (and peers) may not be a canonical QUDT IRI** → the vendored allowlist is authoritative for the POC (referenced, not dereferenced); a wrong spelling is a one-line fix and the fail-loud guard surfaces mismatches immediately.
- **Invalid / unknown unit at ingest** → **fail loud, by design.** For this chunk fail-loud is the correct terminal behavior: the loader emits a fixed set of 4 known units, so an unknown one is a code bug, not new knowledge. Downstream handling is graded but deliberately never a silent auto-resolve: chunk 7's DeepSeek unit-string→QUDT mapping is validated against this same allowlist and **rejected** on an unknown IRI (the LLM maps *to* known units, cannot invent them); genuinely new units enter only via a **human-reviewed** proposal in the chunks 8→9 evolution loop ("LLM-asserted, reviewer-verified"). An auto-growing alias/alternative-spelling table is explicitly out of scope — expanding the allowlist is a manual vendored edit or a reviewed evolution change.
- **NIST dataset revisions** → pin the DOI (`10.18434/mds2-2298`); the vendored copy under `data/nist/` is the frozen input, so re-runs are reproducible independent of upstream.
- **Positional-vs-range misclassification** → resolved by dispatching on the equation-form code rather than the value shape (D4), so there is no ambiguity to misclassify; the ±2.0 mol% tolerance on positional rows is pinned by tests and misclassified rows either land as review-flagged or are caught by the FLiBe/FLiNaK presence assertions.

## Migration Plan

Additive on top of chunk 1. Bootstrap order becomes `make up` → `make load-seed` → `make load-nist` → `make test`. Rollback: re-run `make load-seed` (re-`PUT`s `urn:msr:data` to the seed-only state) and delete/re-init the SQLite file; everything is re-creatable from the vendored inputs. Root config (`Makefile`) is extended additively per the parallel-execution contract; no `docker-compose.yml` change beyond a possible one-shot `load-nist` invocation reusing the existing `loader` service.

## Open Questions

- **NIST composition range encoding** — _resolved_ by inspecting the real vendored files: ranges are written as `X-Y COMPONENT` (e.g. `0.0-33.3 ZrF4`), and appear only on isotherm rows (`I1`–`I4`); every other equation-form code carries a positional single composition instead. The code (not the value shape) drives the D4 dispatch; the manual-review flag remains for positional rows that fail the sum check.
- **Equation forms** — _resolved_ by inspecting the real vendored files: the fluoride subset uses more than the originally-assumed 5 codes. The full documented set from `molten-salt-data.pdf` is `P1`, `P2`, `P3`, `P4`, `+E`, `E1`, `E2`, `DP`, `I1`, `I2`, `I3`, `I4` (D5); the subset actually seen is `P1`/`P2`/`P3`/`+E`/`E1`/`DP`/`I2`/`I3`/`I4`. Only a code outside the full 12-entry set is now a fatal "unknown code" error.
- **`data/nist/` file names** — upstream serves `density-csv.txt`, `conductivity-csv.txt`, `s-tension-csv.txt`, `viscosity-csv.txt`; confirm exact names/headers when vendoring and pin them in the loader's file manifest.
- **Allowlist location** — _decided:_ `ontology/qudt-units.json`, a **committed vendored file** (not an embedded Go table, not tracked in the graph; see D7). `ontology/` is already committed and sits next to the TBox that declares `msr:canonicalUnit`, and the name is accurate — QUDT reference data reused by chunk 8, not NIST data. No `.gitignore` change is needed since `ontology/` is already tracked.
