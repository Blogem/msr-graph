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
{Li, Be, Na, K, Zr, U, Th} (every component ends in `F`). Expected target set (exact
rows to be confirmed on parse; not every salt has all four properties):

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
  A `PropertyMeasurement` node carries `ofSalt`, `hasProperty`, `hasUnit`
  (qudt:Unit), `tempRangeMin/Max`, `equationForm`, `coefficients`, `sourceDataset`,
  `sourceRow`. Units via QUDT (`GM-PER-CentiM3`, `S-PER-CentiM`, `mN-PER-M`, `MilliPA-SEC`).
- **Reactor:** `MoltenSaltReactor` (reuse DIAMOND), `MSRE` individual; components
  `ReactorCore`, `Coolant`, `HeatExchanger`, `Pump`; salt roles `FuelSalt`,
  `CoolantSalt`, `FlushSalt`.
- **Provenance (PROV-style):** `Document` nodes per ORNL report; entities/measurements
  link via `citedIn` / `wasDerivedFrom`.

DIAMOND alignment is by `rdfs:seeAlso` / `skos:closeMatch` to the DIAMOND IRIs
(namespace `https://github.com/idaholab/DIAMOND/`, opaque `nuclear:NNNNNN` classes) —
we do **not** import `diamond.owl` (615 mostly-LWR classes, no unit layer).

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
`reductive extraction`, `coolants`, `fluorides`, + the four property terms. NER
entities link to these via `skos:closeMatch`.

## 4. Stretch — IAEA safety (PUB2027)

Deferred, not in the core build. When added: ingest only the MSR-relevant sections of
*Safety Reports Series No. 123 / PUB2027* — §2.1.2.5 (MSR types), §3.2 (Design), §5.1.8
(safeguards). Machine-readable text-layer PDF, 292 pp. Drives a new `Safety` ontology
branch (`SafetyFunction`, `Confinement`, `DefenceInDepth`, `DesignBasis`, `Requirement`)
as the headline self-evolving-ontology demo. Licensing: © IAEA, all rights reserved —
fine to ingest/quote with attribution for a non-commercial POC; do not redistribute
substantial verbatim text.

## Out of scope

- Chloride salts and fast-spectrum MSR chemistry.
- Full NIST dataset (~4,300 salts/mixtures) — fluoride subset only.
- Full 637-doc archive — curated core set only.
- Loading `diamond.owl` wholesale.
- INIS thesaurus beyond the ~30-concept MSR neighborhood.

## Open items to verify on ingestion

1. Exact fluoride row counts per property file; confirm FLiNaK (`LiF-NaF-KF`) presence.
2. Confirm the MSRE coolant FLiBe (~66-34 `LiF-BeF2`) row exists.
3. Verify the `+E`, `P2`, `P3`, `DP` equation forms against `molten-salt-data.pdf`.
4. Finalize the 3–4 additional chemistry/corrosion docs from the manifest.
