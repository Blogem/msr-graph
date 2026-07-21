# MSR Knowledge Graph POC — Data Scope

Status: **confirmed 2026-07-16**. This document defines the exact data boundary the
POC runs on. Everything downstream (ontology, ingestion, NER, analysis) references
this scope, not ad-hoc choices.

## Scope decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Salt chemistry | **Fluoride systems only** | MSRE-faithful; tightest structured↔unstructured join (443 fluoride vs 220 chloride docs in the archive). |
| Ontology strategy | **Custom OWL ontology that reuses DIAMOND labels** + a QUDT-style quantity pattern | DIAMOND is archived/alpha, has no unit/value machinery and no `Conductivity` class. We borrow its class names (alignment credit) but own a model that can actually store measured values. |
| IAEA safety (PUB2027) | **Stretch goal** | Land the salt-properties spine first; add the safety branch as a second NER genre once the core works. MSR safety content in PUB2027 is thin (design + safeguards only). |

## The spine

The POC is anchored on the **MSRE fluoride salts, FLiBe first**. The same physical
facts exist in both a structured table and an unstructured document, which is what
makes the "grounded AI analysis" demo airtight:

- **Structured:** NIST carries FLiBe (`LiF-BeF2`) and the MSRE fuel/coolant systems
  with density, viscosity, conductivity, surface tension — as equation coefficients.
- **Unstructured:** `ORNL-TM-2316 — "Physical Properties of Molten-Salt Reactor Fuel,
  Coolant, and Flush Salts" (Cantor, 1968)` describes the *same salts* and the *same
  four properties* in prose + equations. `NSRDS-NBS-61-4` is an NBS→NIST molten-salts
  compilation — literal lineage to the structured DB.

An LLM learns *that* FLiBe is the MSRE coolant and *that* its viscosity is Arrhenius
in T from the document, then pulls the coefficients from NIST to compute a number.

## 1. Structured data — NIST Properties of Molten Salts (SRD 27)

- **Source:** https://data.nist.gov/od/id/mds2-2298 (DOI `10.18434/mds2-2298`).
  Files served as `.txt`: `density-csv.txt`, `conductivity-csv.txt`,
  `s-tension-csv.txt`, `viscosity-csv.txt`.
- **Row schema (identical across all 4 files), 13 columns:**
  `Salt, Composition range, Data type, T min (K), T max (K), Uncertainty, Data 1..5,
  Comment, Formatting comment`.
  - `Salt` = chemical formula only (no names/CAS). Mixtures hyphenated (`LiF-BeF2`).
  - `Composition range` = mole %, positional to the formula (`100` = pure).
  - `Data type` = equation form: `P1/P2/P3` (polynomial `A+B·T+…`), `+E`
    (Arrhenius `A·exp(B/T)`), `DP` (discrete point: Data1=value, Data2=temperature).
  - `Data 1..5` = the coefficients. `T min/max` = validity range in K.
  - **No per-row citation column** — provenance is only the dataset DOI.
- **Units:** density g·cm⁻³ · conductivity Ω⁻¹·cm⁻¹ (S/cm) · surface tension mN·m⁻¹ ·
  viscosity mN·s·m⁻² (= mPa·s / cP).

### POC filter

Keep only rows whose salt is a **pure or mixed fluoride** built from cations
{Li, Be, Na, K, Zr, U, Th} (every component ends in `F`). Confirmed on parse
(see "Open items to verify on ingestion" below): **284 fluoride measurements
kept across the 4 property files, 185 distinct canonical salts**; not every
salt has all four properties:

- **Pure:** `LiF`, `BeF2`, `NaF`, `KF` (and `ZrF4`/`UF4`/`ThF4` where present — these
  appear mainly inside mixtures).
- **Binary:** `LiF-BeF2` (FLiBe, multiple compositions across the range), plus
  `LiF-NaF`, `NaF-ZrF4`, `LiF-ThF4`, `LiF-UF4` if present.
- **Ternary:** `LiF-NaF-KF` (FLiNaK — verify presence), `BeF2-LiF-ZrF4`,
  `LiF-BeF2-ThF4`, `LiF-BeF2-UF4`.
- **Quaternary:** `BeF2-LiF-UF4-ZrF4` (the MSRE fuel system — confirmed present).

Estimated tens of rows per file → a small, tractable structured set.

### Demo anchor salts (map onto specific NIST rows)

- **MSRE fuel salt** ≈ LiF-BeF2-ZrF4-UF4 (`~65-29-5-<1` mol%) — NIST row
  `BeF2-LiF-UF4-ZrF4,30.0-64.8-0.2-5.0`.
- **MSRE coolant / flush salt** = FLiBe, LiF-BeF2 ~66-34 mol% (from the `LiF-BeF2`
  composition series).

### Handling

Structured values **stay in a tabular store (SQLite/CSV) — not loaded as triples.**
The graph holds one `MoltenSalt` node per salt + a `PropertyMeasurement` node that
points to the source row and records property, unit, temperature range, and equation
form. The analysis layer queries the table for actual numbers. (Matches the original
intent: "connect structured data to the graph — does not have to be loaded in it.")

### Licensing

NIST open / US-Government work — effectively public domain, attribution to the DOI
expected. No EULA. Safe to ingest and redistribute derivatives.

## 2. Unstructured data — openmsr/msr-archive

- **Source:** https://github.com/openmsr/msr-archive — 637 historical ORNL-centric
  MSR documents, each a scanned PDF **plus a paired OCR `.txt` sidecar** (`ocr/*.txt`,
  ~97 MB total). **No OCR work required.** OCR is good-but-noisy; numeric property
  data and equations survive (e.g. `η = 0.084·exp(4340/T)` in ORNL-TM-2316).
- **Manifest:** the repo `README.md` is a parseable markdown table —
  `| [Title](pdf) | Report-Number | Date | [txt](ocr/<id>.txt) |`. No CSV/JSON catalog.
- **Acquisition:** `GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 …` → ~139 MB on disk,
  leaves PDFs as LFS pointers, pulls the OCR text we need. Fetch individual PDFs on
  demand only if page images are wanted.
- **Two uses, two scopes:** the full 637-doc OCR set stays on disk and is used **only
  for corpus-frequency statistics** (vocabulary salience, novelty scoring — cheap text
  scans); NER/relation extraction runs on the curated core set alone. This keeps the
  processing scope small while keeping frequency evidence (e.g. "solubility: 280/637
  docs") real.

### POC core document set (~10–12 docs)

Confirmed anchors:

| Report | Title | Role |
|--------|-------|------|
| `ORNL-TM-2316` | Physical Properties of MSR Fuel, Coolant, Flush Salts (Cantor, 1968) | **Primary property↔NIST bridge** |
| `ORNL-TM-0728` | MSRE Design and Operations Report Part I: Reactor Design (1965) | Reactor + components |
| `ORNL-CF-63-9-20` | Literature Survey: Thermal & Physical Properties of Molten Fluoride/Chloride Salts (1963) | Properties survey |
| `ORNL-2150` | Physical Property Summary for ANP Fluoride Mixtures (1956) | Properties |
| `NSRDS-NBS-61` (pt. 4) | Physical Properties Data Compilations — IV. Molten Salts (1988) | NBS→NIST lineage |
| `ORNL-TM-3884` | Migration of Fission Products (Noble Metals) in the MSRE | Chemistry (drives new concepts) |
| `ORNL-TM-0078` | Thermal-Stress/Strain-Fatigue of MSRE Fuel & Coolant Pump Tanks | Component + property |

Expand to ~10–12 by adding 3–4 from the MSRE chemistry/corrosion cluster
(INOR-8 / Hastelloy-N appears in 163 docs) selected from the manifest — these feed
the self-evolving-ontology demo with genuinely new concepts.

**Selection criteria for the 3–4 additions** (the evolution demo depends on its target
mentions existing in the *curated set*, not just corpus-wide): at least one report with
**solubility statements carrying numeric values + units** (the fuel-salt-chemistry /
PuF₃-and-fission-product-solubility-in-LiF-BeF₂ cluster), and the set must contain
**graphite-as-moderator statements in prose** (ORNL-TM-0728, the MSRE design report, is
expected to cover this — verify on ingest).

### Finalized curated set (2026-07-19)

Finalized against a real clone of `openmsr/msr-archive` (`git clone --depth 1`, 631
manifest records, 637 OCR sidecars on disk) — task 4.1/4.3/4.4, closes open items 4 & 5
below. `CURATED_REPORTS` in `extraction/src/msr_extraction/curated.py` is this exact
11-report list; every report number resolves via the real README manifest
(`resolve_ocr_path`) **and** has an OCR sidecar file that actually exists on disk.

**Two anchor reconciliations against the real manifest/checkout:**

1. `NSRDS-NBS-61-4` → **`NSRDS-NBS-61-p4`**. The provisional anchor name didn't match the
   real manifest token; the actual README row is
   `Physical Properties Data Compilations Relevant to Energy Storage - IV. Molten Salts...`
   with report number `NSRDS-NBS-61-p4` (`ocr/NSRDS-NBS-61-p4.txt`).
2. `ORNL-CF-63-9-20` → **`ORNL-3293`** ("Thermodynamic Properties of Molten-Salt
   Solutions", 1962). The original anchor's README row parses fine and its link target
   (`ocr/ORNL-CF-63-9-20.txt`) resolves through `resolve_ocr_path`, but that OCR sidecar
   file **does not exist** in the real msr-archive git tree — confirmed with
   `git ls-tree -r HEAD` on the clone (empty result) and by direct filesystem check. This
   is a genuinely broken upstream link, not an LFS/smudge artifact (only `*.pdf` is
   LFS-tracked in `.gitattributes`; `.txt` sidecars are plain git blobs). `ORNL-3293`
   fills the same "properties survey" role with real, present OCR text.

**Finalized 11-document curated set:**

| Report | Title | Role |
|--------|-------|------|
| `ORNL-TM-2316` | Physical Properties of MSR Fuel, Coolant, Flush Salts (Cantor, 1968) | **Primary property↔NIST bridge** |
| `ORNL-TM-0728` | MSRE Design and Operations Report Part I: Reactor Design (1965) | Reactor + components; **graphite-as-moderator evidence** |
| `ORNL-3293` | Thermodynamic Properties of Molten-Salt Solutions (1962) | Properties survey (substitutes `ORNL-CF-63-9-20`; see above) |
| `ORNL-2150` | Physical Property Summary for ANP Fluoride Mixtures (1956) | Properties |
| `NSRDS-NBS-61-p4` | Physical Properties Data Compilations — IV. Molten Salts (1988) | NBS→NIST lineage (reconciled report#; see above) |
| `ORNL-TM-3884` | Migration of Fission Products (Noble Metals) in the MSRE | Chemistry (drives new concepts) |
| `ORNL-TM-0078` | Thermal-Stress/Strain-Fatigue of MSRE Fuel & Coolant Pump Tanks | Component + property |
| `ORNL-TM-2256` | Chemical Feasibility of Fueling Molten-Salt Reactors with PuF3 (1968) | Chemistry addition; **solubility-with-unit evidence** |
| `ORNL-4658` | Chemical Aspects of MSRE Operations (1971) | Chemistry/corrosion addition |
| `ORNL-4829` | Intergranular Cracking of INOR-8 in the MSRE (1972) | Corrosion addition (INOR-8/Hastelloy-N cluster) |
| `ORNL-3124` | INOR-8-Graphite-Fused Salt Compatibility Test (1961) | Corrosion addition (INOR-8/Hastelloy-N cluster) |

**Evolution-demo target evidence** (`detect_evolution_targets`, run against the real OCR
text of every report above — full gate output: `GATE PASSED`):

- **Solubility statement with numeric value + unit** — report `ORNL-TM-2256`,
  `ocr/ORNL-TM-2256.txt` lines 357–360 (quoted verbatim, OCR noise included):

  > "1. LiF-BeF,: The solubility of PuF; in LiF-Bel, solvents was measured by Bart0n6 for
  > compositions ranging in BeF, from 28.7 to 48.3 mole % and from 450 to 650°C.
  > Solubilities of PuF; in LiF-BeF, solvents are compared with those for CeF; in..."

  (`PuF;` = OCR mis-render of `PuF3`; `Bel,`/`BeF,` = `BeF2`; value+unit = "28.7 to 48.3
  mole %"). `ORNL-TM-2316` also independently trips the solubility detector (a noisy
  isotope table), and `ORNL-4658`/`NSRDS-NBS-61-p4` carry additional solubility+unit
  prose — the target is not a single-document fluke.

- **Graphite-as-moderator prose** — report `ORNL-TM-0728`, `ocr/ORNL-TM-0728.txt` line
  2738 (quoted verbatim):

  > "The Molten-Salt Reactor Experiment (MSRE) is a single-region, un-clad,
  > graphite-moderated, fluid-fuel type of reactor with a design heat generation rate of
  > 10 Mw."

  Also present, independently, in `ORNL-TM-3884`, `ORNL-TM-2256`, `ORNL-4658`,
  `ORNL-4829`, and `ORNL-3124` — 6 of the 11 curated documents carry
  graphite-as-moderator prose, not just the one anchor.

Both fixtures above are pinned verbatim (with report#/line provenance as a comment
header) in `extraction/tests/fixtures/target_solubility.txt` and
`extraction/tests/fixtures/target_graphite.txt`.

### Licensing

Repo is GPL-3.0 (a code license, applied awkwardly to documents); underlying ORNL/AEC
reports are US-government works, generally public domain in the US. OCR text + manifest
are the project's own contribution. Low risk for a POC; cite ORNL as primary source.

## 3. Ontology & vocabulary

Custom OWL ontology (RDF, loadable into GraphDB) with three layers:

- **Substance:** `MoltenSalt` (reuse DIAMOND label), `SaltComponent` (compound +
  mole fraction), individuals per salt (`flibe`, MSRE fuel, …).
- **Property + measurement (QUDT-style quantity pattern):** `Density`, `Viscosity`,
  `SurfaceTension` (reuse DIAMOND labels; DIAMOND calls surface tension
  `InterfacialTension`), plus `ElectricalConductivity` (**DIAMOND lacks this — new**).
  A `PropertyMeasurement` node carries `ofSalt`, `forProperty`, `hasUnit` (qudt:Unit),
  `validTempMin/Max`, `equationForm`, `uncertainty`, and a `dataLocator` pointing at the
  coefficient row in SQLite (the numbers stay external); provenance via
  `prov:wasDerivedFrom` / `citedIn`. Units via QUDT (`GM-PER-CentiM3`, `S-PER-CentiM`,
  `mN-PER-M`, `MilliPA-SEC`) — see `ONTOLOGY.md` for the materialized T-Box.
- **Reactor (deferred to chunk-7):** `MoltenSaltReactor` (reuse DIAMOND), an `MSRE`
  individual, salt roles `FuelSalt`/`CoolantSalt`/`FlushSalt`, and reactor components
  (`ReactorCore`, `Coolant`, `HeatExchanger`, `Pump`) are real, extractable facts —
  `ORNL-TM-2316` states the 66-34 melt "has been used in the MSRE as the coolant" — but
  nothing writes them into the graph until chunk-7 relation extraction derives them from
  real text. The POC ontology does not carry a hand-curated reactor/role layer in the
  meantime; the vocabulary still seeds NER with the corresponding SKOS concepts.
- **Provenance (PROV-style):** `Document` nodes per ORNL report; entities/measurements
  link via `citedIn` / `wasDerivedFrom`.

DIAMOND alignment is by `rdfs:seeAlso` to the DIAMOND IRIs (namespace
`https://github.com/idaholab/DIAMOND/`, opaque `nuclear:NNNNNN` classes) — we do **not**
import `diamond.owl` (615 mostly-LWR classes, no unit layer).

### Controlled vocabulary (SKOS)

~25–30 `skos:Concept`s for the MSR neighborhood. **Curated by Claude, not the user**
(no domain expertise required from the user): concepts and their broader/narrower/
related links are taken from the INIS thesaurus's own MSR branch and cross-checked
against term frequencies in the msr-archive corpus, so the selection is evidence-based
rather than invented. (No open machine-readable IAEA release exists; the OSTI Semantic
Thesaurus RDF/SKOS derivative is a fallback.) **Deferred — build during the vocabulary
phase.** Seed concepts: `MOLTEN SALT REACTORS`
(→ `molten salt cooled reactors` → `MSRE REACTOR`; → `molten salt fueled reactors`),
`MOLTEN SALTS` (→ `flibe`), `molten salt fuels`, `metal transfer process`,
`reductive extraction`, `coolants`, `fluorides`, + the four property terms. Concepts
carry the friendly names (`skos:prefLabel`/`skos:altLabel`, e.g. "FLiBe") that seed the
NER matcher; a recognized mention links to its resolved target (a concept, or — for a
composed salt formula — the `msr:MoltenSalt` individual itself) via `msr:linksTo` on the
`msr:Mention`, not via `skos:closeMatch`.

## 4. IAEA/GIF/ORNL safety sources (chunk 11, `ingest-iaea-safety`)

Finalized, no longer a stretch/deferred item. The feasibility spike in
[`docs/SAFETY_THREAD_SPIKE.md`](SAFETY_THREAD_SPIKE.md) proved one grounded thread —
requirement → safety function → property → measurement → salt — end to end on real
sources, nothing fabricated; the `ingest-iaea-safety` change realizes that thread (the
`Safety` ontology branch, the digital-thread linking edges, and the six stakeholder
questions the spike identifies). See that doc for the full thread and questions; this
section records the finalized data scope.

**Finalized ingested set — four sources:**

| Source | Role | Section scope |
|---|---|---|
| **IAEA SRS-123 / PUB2027** — *Applicability of IAEA Safety Standards to Non-Water Cooled Reactors and SMRs* | requirement anchor: the three fundamental safety functions (confinement of radioactive material, control of reactivity, heat removal) | §2.1.2.5 (MSRs) / §3.2 (Design) / §5.1.8 (safeguards) only — not the full 292 pp |
| **GIF (Holcomb) — *Molten Salt Reactor Safety Analysis - A U.S. Perspective*** (2020) | ties the fundamental safety functions to salt thermophysical properties | whole document (32 pp, entirely MSR-specific; the public stand-in for a not-yet-published GIF MSR-specific Safety Design Criteria report) |
| **ORNL/TM-2006/12** — *Assessment of Candidate Molten Salt Coolants for the Advanced High-Temperature Reactor (AHTR)* | coolant-selection criteria organized by melting point / vapor pressure / viscosity / thermal conductivity / heat capacity | whole document |
| **ORNL — *Molten Salt Reactor Technical and Safety Considerations Outside of Guidance Documents*** | secondary requirement-layer context | whole document |

The exact page ranges backing each scope (and how they were located in the cached PDF)
are recorded as the tracked, structured manifest in
`extraction/src/msr_extraction/safety_manifest.py`.

Drives the `Safety` ontology branch (`SafetyFunction`, `Confinement`, `DefenceInDepth`,
`DesignBasis`, `Requirement`) **grown, not seeded** — mined as change proposals from the
safety genre through the same chunk-8/chunk-9 evolution loop that grows the chemistry
branch, then linked to the existing `PhysicalProperty` individuals (`vaporPressure`,
`specificHeat`, `thermalConductivity`, `meltingPoint`) already in the seed T-Box via
evidence-bearing `msr:servedByProperty` (`SafetyFunction → PhysicalProperty`) and
`msr:addressesFunction` (`Requirement → SafetyFunction`) edges. No safety→salt or
safety→numeric-value edge is asserted directly — the tie to a salt is transitive through
the shared `PhysicalProperty`, since no source states a direct requirement→value link.
This is the headline self-evolving-ontology demo on a second, higher-stakes genre.

**Attribution & rights:** IAEA SRS-123 is © all rights reserved; the GIF and ORNL sources
are public/US-government works. No PDF or full extracted text is committed for any of
the four sources — only `scripts/fetch-safety-sources.sh` (reproduces the gitignored
`data/safety/` cache) and the attributed manifest above (source id, title, publisher,
rights statement, `dcterms:source` URL, date, and the exact ingested section/page scope)
are tracked. Every safety `msr:Document` node additionally carries
`dcterms:publisher`/`dcterms:rights`/`dcterms:source`, so any evidence quote the agent
surfaces is attributable back to its licensed source.

The out-of-scope notes below (in particular the INIS-thesaurus exclusion, which
preserves the novelty-mining demo the safety branch also depends on) are unchanged and
apply to the safety genre too.

## Out of scope

- Chloride salts and fast-spectrum MSR chemistry.
- Full NIST dataset (~4,300 salts/mixtures) — fluoride subset only.
- Full 637-doc archive — curated core set only.
- Loading `diamond.owl` wholesale.
- INIS thesaurus beyond the ~30-concept MSR neighborhood. Three reasons, beyond focus:
  (a) no machine-readable release exists — the full ~30k-descriptor thesaurus is a
  PDF-parsing project in itself; (b) it would flood the NER surface and the cached
  KG-schema prompt with off-domain concepts; (c) it would **kill the evolution demo** —
  `SOLUBILITY` and `GRAPHITE` are INIS descriptors, so a fully-loaded thesaurus makes
  them "known" and the novelty miner never fires. If INIS grounding validation is ever
  wanted, the shape is a flat vendored term list outside the graph (like the QUDT unit
  allowlist), not loaded concepts.

## Open items to verify on ingestion

Each item is owned by an implementation chunk (see `IMPLEMENTATION_PLAN.md`) and appears
in that chunk's acceptance criteria.

1. **RESOLVED** on ingest (2026-07-19). Exact fluoride row counts per property file
   (rows read → fluoride kept; 0 flagged for manual review in all four files):

   | File | rows read | fluoride kept | out-of-scope (non-fluoride) |
   |------|-----------|---------------|------------------------------|
   | density | 3608 | 95 | 3513 |
   | conductivity | 4085 | 85 | 4000 |
   | s-tension | 1677 | 47 | 1630 |
   | viscosity | 1414 | 57 | 1357 |

   Totals: **284 measurements kept, 185 distinct canonical salts, 0 flagged**.
   FLiNaK is **present** — `KF-LiF-NaF` at `42.0-46.5-11.5 mol%` (density, `P1`).
   → **chunk 2** (`load-nist-structured-data`)
2. **RESOLVED** on ingest (2026-07-19). The MSRE coolant FLiBe row is **present**:
   NIST row `BeF2-LiF,34.0-66.0,P1,800,1080,,2.413,-4.88E-4` → canonical
   `BeF2-LiF | 34.0-66.0`, salt `msrd:salt-BeF2-LiF-34.0-66.0`. Note: the raw file
   already lists components byte-sorted as `BeF2-LiF` with BeF2=34/LiF=66 — the
   earlier assumption above of a `LiF-BeF2,34.0-66.0` row is corrected against the
   real data (composition is BeF2-major at this range, not LiF-major). → **chunk 2**
3. **RESOLVED** on ingest (2026-07-19). Verified the equation forms actually present
   in the fluoride subset against `molten-salt-data.pdf`, all now modeled in the
   TBox: **Linear** (`P1`) = 130, **Arrhenius** (`+E`) = 131, **DiscretePoint**
   (`DP`) = 16, **ExtendedArrhenius1** (`E1`) = 2, **Isotherm2** (`I2`) = 1,
   **Isotherm3** (`I3`) = 2, **Isotherm4** (`I4`) = 2. The `I*` isotherm forms
   (property-vs-composition at fixed T, e.g. `KF-ZrF4, 0.0-33.3 ZrF4`) and `E1`
   are ingested as first-class measurements (range-composition salts for
   isotherms), not skipped. (`P2`/`P3` do not occur in the fluoride subset — only
   `P1` polynomials appear.) → **chunk 2**
4. Finalize the 3–4 additional chemistry/corrosion docs from the manifest.
   → **chunk 5** (`ingest-archive-documents`). **RESOLVED (2026-07-19):** 4 additions
   picked (`ORNL-TM-2256`, `ORNL-4658`, `ORNL-4829`, `ORNL-3124`); 2 of the original 7
   DATA_SCOPE anchors reconciled against the real manifest/checkout
   (`NSRDS-NBS-61-4`→`NSRDS-NBS-61-p4`, `ORNL-CF-63-9-20`→`ORNL-3293`). Final 11-doc list
   is `CURATED_REPORTS` in `extraction/src/msr_extraction/curated.py`; full detail in
   "Finalized curated set (2026-07-19)" above.
5. Confirm the final curated set actually contains the evolution-demo targets —
   solubility statements with numeric values/units, and graphite-as-moderator prose.
   (Corpus-wide salience counts don't guarantee presence in the 12.) → **chunk 5**;
   **RESOLVED (2026-07-19):** verified with `detect_evolution_targets` against the real
   OCR text of all 11 curated documents — `GATE PASSED`. Solubility-with-unit evidence in
   `ORNL-TM-2256` ("...28.7 to 48.3 mole %..."); graphite-as-moderator evidence in
   `ORNL-TM-0728` ("...graphite-moderated..."). Both quoted verbatim, with line-number
   provenance, in "Finalized curated set (2026-07-19)" above and pinned in
   `extraction/tests/fixtures/target_solubility.txt` /
   `extraction/tests/fixtures/target_graphite.txt`. Gates chunks 8–10.
