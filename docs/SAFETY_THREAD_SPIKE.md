# `ingest-iaea-safety` (chunk 11) — feasibility spike: one grounded thread, end to end

> **Realized.** This spike's grounded thread (requirement → safety function → property
> → measurement → salt) and the six stakeholder questions below are now implemented by
> the `ingest-iaea-safety` change — the finalized four-source ingested set, section
> scope, and attribution rule are recorded in
> [`docs/DATA_SCOPE.md` §4](DATA_SCOPE.md#4-iaeagifornl-safety-sources-chunk-11-ingest-iaea-safety).

**Question.** Can the safety/requirements ambition be realized by *tying real NIST +
OCR salt-property data to real IAEA safety requirements*, with **nothing fabricated** —
in the same all-real spirit as `ground-demo-in-real-docs`?

**Answer: yes.** One thread is proven end to end below, every node and edge citing a
real source. The join is on entities that **already exist in the graph** (the FLiBe salt
individual + its `PhysicalProperty` measurements), so chunk 11 adds a `Safety` branch and
links it in — it does not invent the connection.

## Sources (cached in `data/safety/`, gitignored; repopulate with `scripts/fetch-safety-sources.sh`)

Full PDFs are © their publishers and are **not** committed (IAEA: all rights reserved,
no substantial verbatim redistribution). Only short attributed quotes appear here.

| Layer | Source | Role |
|-------|--------|------|
| Requirement (IAEA anchor) | **IAEA SRS-123 / PUB2027** — *Applicability of IAEA Safety Standards to Non-Water-Cooled Reactors and SMRs* | §2.1.2.5 MSRs; the three fundamental safety functions |
| Requirement (GIF/function) | **Holcomb, GIF — *MSR Safety Analysis*** (2020) | ties fundamental safety functions to salt thermophysical properties |
| Requirement (coolant criteria) | **ORNL/TM-2006/12** — *Assessment of Candidate Molten Salt Coolants* | coolant selection organised by melting point / vapor pressure / viscosity / thermal conductivity / heat capacity, with LiF-BeF₂ values |
| Bridge (already in corpus) | **ORNL-4658**, **ORNL-TM-0728**, **ORNL-TM-2316**, **NSRDS-NBS-61** | MSRE program requirements ↔ properties; containment / freeze valves / decay-heat systems; measured values |
| Value (structured) | **NIST SRD-27** (`data/nist/`, already loaded) | density, viscosity, conductivity, surface tension |

> A GIF **MSR-specific** Safety Design Criteria (SDC) report is not yet public — GIF has
> published VHTR and LFR SDC only. The Holcomb GIF-MSR safety analysis is the public
> stand-in for the requirement-function layer until an MSR SDC lands.

## The proven thread (all real, nothing invented)

Join key = the real salt individual **FLiBe** = `LiF-BeF₂ (66-34 mole %)`
(canonical `BeF2-LiF | 66.0-34.0`) and its `PhysicalProperty` nodes.

```
IAEA fundamental safety function                     [SRS-123 §2.1.2.5, lines 820, 2137-2139]
  "confinement of radioactive material,
   control of reactivity and heat removal"
        │
        ├─ confinement ── served by ─▶ low vapor pressure / margin to boiling
        │       GIF Holcomb: "Strong inherent retention of radionuclides – Low
        │       pressure! • Large margin to boiling"                    [Holcomb l.277-279]
        │            └─ measured value ─▶ FLiBe vapor pressure          [ORNL-TM-2316 §VAPOR PRESSURE, l.1637]
        │
        ├─ heat removal ─ served by ─▶ heat capacity + viscosity (natural circulation)
        │       GIF Holcomb: "Fuel salt has advantageous combination of heat
        │       capacity, thermal expansion, and viscosity for natural
        │       circulation cooling"                                    [Holcomb l.298-300]
        │            ├─ FLiBe heat capacity = 0.577 cal g⁻¹ °C⁻¹        [ORNL-4658 l.8845]
        │            ├─ FLiBe viscosity (η = A·exp(B/T))                [NIST viscosity-csv, BeF2-LiF 36-64]
        │            └─ FLiBe density = 2.413 − 4.88e-4·T g cm⁻³        [NIST density-csv, BeF2-LiF 34.0-66.0]
        │
        └─ stay-liquid / freeze-valve & drain design                   [ORNL-TM-0728: Freeze Valves,
                └─ requires ─▶ liquidus below coolant-selection limit    Decay Heat Removal System, Containment]
                        ORNL/TM-2006/12 coolant criteria: melting point / liquidus a
                        primary selection factor
                        └─ FLiBe liquidus = 434 °C  ✓ (well below the ~500 °C
                           preference)                                  [ORNL-4658 l.657]
```

The one honest caveat: **no single sentence** says "requirement R needs property P of salt
S." The thread is a **cross-document join on shared salt+property entities** — legitimate
for a KG digital thread *because each edge is individually grounded* in the citations above.
Per `PROVENANCE_AND_TRUST_DESIGN.md` §6, the safety→property edges are opportunistic
(`rdfs:seeAlso` / evidence-style), asserted only where the text supports them; no direct
requirement→numeric-value edge is asserted (none is stated in any source).

## Real-data grounding check (FLiBe exists in enough real sources)

Verified against the **source data we load**, not pipeline-generated files:

- **NIST SRD-27** (`data/nist/*.txt`): `BeF2-LiF` binary present in all four property files
  — density `34.0-66.0` (`2.413, -4.88E-4`), conductivity `34.0-66.0`, viscosity `36-64`
  (≈FLiBe), surface tension `33-67` (≈FLiBe).
- **ORNL-4658** (raw OCR): `LiF-BeF, (66-34 mole %)` named repeatedly; liquidus 434 °C;
  heat capacity 0.577 cal g⁻¹ °C⁻¹; property table (density/viscosity/heat capacity/thermal
  conductivity); l.3227 ties "properties of greatest significance … in response to MSRE
  **program requirements** … for reactor performance evaluations."
- **ORNL-TM-2316** (raw OCR): dedicated Vapor Pressure and Heat Capacity sections; FLiBe as
  flush/fuel-solvent salt.
- **ORNL-TM-0728**: containment, freeze valves, decay-heat-removal system (the safety-function
  structure).

## What chunk 11 would build on top of this (not built here)

1. Ingest the `data/safety/` sources as a **second NER genre** (reuse chunks 5–7 pipeline).
2. Mine a `Safety` branch — `SafetyFunction`, `Confinement`, `DefenceInDepth`, `DesignBasis`,
   `Requirement` — via the chunk-8 evolution loop (grown from text, not hand-authored).
3. Link `SafetyFunction`/`Requirement` → existing `PhysicalProperty` (and thereby to the
   FLiBe measurements) with evidence-bearing edges, inheriting P3.5 provenance + SHACL.

This document + `scripts/fetch-safety-sources.sh` are the durable artifacts of the spike.

## Questions the landed safety data could answer

These are the payoff of the thread: questions a regulator/licensing reviewer or an MSR
design engineer actually cares about, each **answerable by the chunk-4 grounded agent over
the graph** once the `Safety` branch lands — and each showcasing something a bare LLM
*cannot* do faithfully (traverse an auditable evidence chain, detect a real data gap,
compare on real measured values). All are grounded in data we already hold; none require
fabricating a value or a requirement.

### Regulator / licensing-reviewer facing

1. **"Show me the evidence chain behind a safety claim."**
   *For the confinement safety function, what measured salt-property evidence supports it,
   and where did each value come from?*
   Traverses `SafetyFunction(confinement) → servedBy → PhysicalProperty(vapor pressure) →
   PropertyMeasurement → prov:wasDerivedFrom` (ORNL-TM-2316 + dataset DOI). This is the
   digital-thread query: every hop is resolvable and auditable — the P3.5 provenance
   contract is what makes the answer defensible rather than asserted.

2. **"Where are the evidence gaps?"**
   *Which safety-relevant salt properties have no measured value, or only high-uncertainty
   values, in the cited sources?*
   Surfaces e.g. thermal conductivity (ORNL/TM-2006/12 flags it as the highest-uncertainty,
   hardest-to-measure property) and the decay-heat modelling gap Holcomb calls the "most
   significant experimental hole." A safety function whose supporting property is data-poor
   is exactly the kind of finding SRS-123 itself is built to raise — the graph makes it a
   query, not a manual literature review.

3. **"Is this requirement met, and with what margin?"**
   *Does the FLiBe coolant satisfy the liquidus selection criterion, and by how much?*
   FLiBe liquidus 434 °C vs the ~500 °C preference (ORNL/TM-2006/12) → **66 °C margin**.
   Caveat surfaced in the answer: the 500 °C figure is a *coolant-selection preference*, not
   a licensing limit — the agent should report it as such, not as a pass/fail against a
   regulatory threshold.

4. **"Does the evidence cover the operating (and accident) envelope?"**
   *Over what temperature range is FLiBe's supporting property evidence valid, and does it
   span the reactor's operating range?*
   Uses each measurement's `validTempMin/Max` (NIST rows carry them; the agent already
   refuses silent extrapolation, chunk 4). Evidence that stops below the accident-relevant
   range is a red flag a reviewer wants flagged automatically.

### Design-engineer facing

5. **"Which candidate salt is best for a given safety function?"**
   *Among the fluoride coolants we have data for, which gives the best natural-circulation
   decay-heat performance?*
   Aggregates heat capacity + viscosity + density across salts (NIST + OCR) — the exact
   combination Holcomb names for the heat-removal function — and ranks them via a sandbox
   script (chunk 4's comparative-query path). Grounded trade-off, not an LLM guess.

6. **"What's the safety cost of a design change?"**
   *If the coolant composition shifts (e.g. more BeF₂), how do the safety-relevant properties
   move?*
   NIST holds the full LiF-BeF₂ composition series (viscosity climbs steeply from 36-64 to
   90-10, surface tension across 15-85…67-33), so the agent can show how a composition change
   trades viscosity (heat removal) against other properties — each point a real measured row.

Each question is a candidate acceptance criterion / demo script for chunk 11. Questions 1
and 2 are the strongest headline demos: they show the KG doing what a regulator values most
— **traceable evidence** and **honest gap disclosure** — on entirely real data.
