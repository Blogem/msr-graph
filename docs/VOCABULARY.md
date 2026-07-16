# MSR Controlled Vocabulary — Candidate Concepts

Status: **Phase A orientation pass — core set APPROVED 2026-07-16.** The ~29-concept
recommended core is adopted; the optional context facet is deferred (not dropped —
revisit if the pipeline needs more NER surface area). This "learn the vocabulary"
deliverable fed seed-ontology design (Phase B); the finalized SKOS scheme is now built
and rdflib-validated as `ontology/vocab.ttl` (Phase C, 2026-07-17).

## Method (how this was derived, not invented)

- **Structure** taken from the IAEA **INIS thesaurus** (2018 English ed.) — extracted
  the MSR branch and the fluoride/property sub-trees directly from the PDF. INIS
  `BT/NT/RT/UF/SF` map to SKOS `broader/narrower/related/altLabel`.
- **Salience** measured as **document frequency across the 637-doc msr-archive OCR
  corpus** (how many documents mention the concept). This is why each concept is here.
- **Two concept sources:** `INIS` = a real INIS descriptor (reuse its label + links);
  `minted` = no INIS descriptor exists but the concept is load-bearing in the corpus
  (we define it in a local namespace). Minted concepts are flagged.

### Evidence caveats (honest read of the numbers)

- Two corpus counts are noisy and were **discarded/discounted**: an `ARE/ANP` probe
  hit 627 docs but that was the English word "are" — the *Aircraft Reactor Experiment*
  is therefore **not** included on false-positive grounds. `density` (471) includes
  non-fluid senses (density of states, flux/power density); mass density still clearly
  dominant.
- INIS's controlled reactor-subtype phrases barely occur verbatim: `molten salt cooled
  reactors` = 0 docs, `molten salt fueled reactors` = 2. They stay as **structural**
  concepts (they organize the hierarchy and carry the cooled-vs-fuelled distinction)
  but they are **not NER surface targets** — the corpus expresses the distinction as
  MSRE / MSBR / single- vs two-fluid instead.

## Recommended core (~29 concepts)

### A. Reactor frame

| prefLabel | src | altLabels / surface forms | docs | broader | why |
|-----------|-----|---------------------------|-----:|---------|-----|
| Molten salt reactors | INIS | MSR | 347 | reactors | Domain root; the reactor family the POC is about. → DIAMOND `MoltenSaltReactor`. |
| Molten salt cooled reactors | INIS | — | 0* | Molten salt reactors | Structural: salt = coolant only (solid-fuel MSR). Parent of MSRE. |
| Molten salt fueled reactors | INIS | liquid-fuel MSR | 2* | Molten salt reactors; fluid fueled reactors | Structural: fissile dissolved in salt (the liquid-fuel line). |
| MSRE reactor | INIS | MSRE, molten salt reactor experiment | 270 | Molten salt cooled reactors | The specific reactor ORNL-TM-2316/0728 describe; primary instance anchor. |

### B. Salts & fluoride compounds (the NIST bridge)

| prefLabel | src | altLabels / surface forms | docs | broader | why |
|-----------|-----|---------------------------|-----:|---------|-----|
| Molten salts | INIS | fused salts, ionic liquids, molten salt coolants | 475 | salts | Substance root; RT coolants. → DIAMOND `MoltenSalt`. |
| FLiBe | INIS | LiF-BeF2, LiF-BeF₂ eutectic | 223 | Molten salts | Primary MSRE coolant/flush salt; the one mixture INIS names; the structured↔unstructured anchor. |
| FLiNaK | **minted** | LiF-NaF-KF | 63 | Molten salts | Common MSR coolant eutectic; INIS has no term (contrast with FLiBe) → minted-concept example. |
| Fluorides | INIS | — | 443 | halides | Compound family; parent of the 7 salt components below. |
| Lithium fluorides | INIS | LiF | 343 | Fluorides | Component of FLiBe / FLiNaK / fuel salt. |
| Beryllium fluorides | INIS | BeF2 | 312 | Fluorides | Component of FLiBe; key viscosity driver. |
| Uranium fluorides | INIS | UF4 | 237 | Fluorides | Fissile carrier in the fuel salt. |
| Zirconium fluorides | INIS | ZrF4 | 167 | Fluorides | MSRE fuel-salt component. |
| Thorium fluorides | INIS | ThF4 | 145 | Fluorides | Fertile component (breeding). |
| Sodium fluorides | INIS | NaF | 287 | Fluorides | FLiNaK / coolant systems. |
| Potassium fluorides | INIS | KF | 186 | Fluorides | FLiNaK component. |

### C. Salt functional roles (minted — the ORNL-TM-2316 triad)

| prefLabel | src | altLabels | docs | related | why |
|-----------|-----|-----------|-----:|---------|-----|
| Fuel salt | **minted** | fuel-bearing salt | 301 | Molten salt fueled reactors; INIS `molten salt fuels` (closeMatch) | ORNL-TM-2316 category; salt as fissile carrier. |
| Coolant salt | **minted** | secondary salt | 153 | Molten salt cooled reactors; Coolants | ORNL-TM-2316 category; secondary heat-transfer salt. |
| Flush salt | **minted** | flushing salt | 111 | MSRE reactor | ORNL-TM-2316 category; cleaning salt. |

### D. Physical properties

Core four (the NIST structured columns):

| prefLabel | src | altLabels | docs | broader | why |
|-----------|-----|-----------|-----:|---------|-----|
| Density | INIS | mass density | 471 | — | NIST property. (INIS `DENSITY` is physics-flavored; closest match — flag for ontology alignment.) → DIAMOND `Density`. |
| Viscosity | INIS | dynamic viscosity | 262 | — | NIST property. → DIAMOND `Viscosity`. |
| Electric conductivity | INIS | electrical conductivity, electrical conductance | 87 | — | NIST property. INIS preferred label is `ELECTRIC CONDUCTIVITY`; DIAMOND lacks this class (new). |
| Surface tension | INIS | interfacial tension | 99 | surface properties | NIST property. INIS `SF interfacial tension` → DIAMOND `InterfacialTension`. |

Extended four (in the corpus, **not** in NIST — these are the seed-ontology-evolution candidates):

| prefLabel | src | altLabels | docs | broader | why |
|-----------|-----|-----------|-----:|---------|-----|
| Melting point | INIS (`MELTING POINTS`) | freezing point, liquidus | 337 | transition temperature | Bounds the molten range → bounds NIST validity-T; strong evolution candidate. |
| Specific heat | INIS | heat capacity | 277 | thermodynamic properties | Heat-balance property; INIS folds "heat capacity" into `SPECIFIC HEAT`. |
| Thermal conductivity | INIS | — | 240 | thermodynamic properties | Heat-transfer property common in the archive. |
| Vapor pressure | INIS | vapour pressure | 230 | thermodynamic properties | Volatility/containment relevance. |

### E. Processes & materials context

| prefLabel | src | altLabels | docs | broader / related | why |
|-----------|-----|-----------|-----:|---------|-----|
| Corrosion | INIS | — | 403 | chemical reactions | Dominant archive theme; salt–alloy compatibility. |
| Nickel base alloys | INIS | Hastelloy-N, INOR-8 | 309 | — | The MSRE structural alloy; INIS has no "Hastelloy" term (→ altLabels). |
| Reductive extraction | INIS | — | 62 | extraction; RT Molten salt reactors | Fuel-salt reprocessing chemistry. |

## Optional (context expansion — approve to include)

| prefLabel | src | docs | facet | why it's optional |
|-----------|-----|-----:|-------|-------------------|
| Molten salt breeder reactor | **minted** (MSBR) | 191 | reactor | Big archive theme but beyond the MSRE core; INIS has no term. |
| Coolants | INIS | 358 | engineering | Generic; keep only for the coolant-salt linkage. |
| Heat exchangers | INIS | 353 | engineering | Plant component; peripheral to a properties graph. |
| Metal transfer process | INIS | 53 | process | Specific reprocessing step; RT molten salt reactors. |
| Graphite | INIS | 388 | neutronics | MSRE moderator; broad. |
| Breeding | INIS | 386 | fuel cycle | Th/U-233 cycle context. |
| Fission products | INIS | 378 | chemistry | ORNL-TM-3884 topic. |
| Thorium | INIS | 296 | fuel cycle | Fertile element. |
| Eutectics | INIS | 213 | phys-chem | Explains fixed salt compositions. |
| Uranium-233 | INIS | 161 | fuel cycle | Bred fissile. |
| Phase diagrams | INIS | 156 | phys-chem | Composition/temperature relationships. |

## Label & scheme decisions (applied above)

1. **Use INIS preferred labels**, not the popular variant: `Electric conductivity`
   (not "electrical"), `Specific heat` (subsumes heat capacity), `Melting point`
   (subsumes freezing point). Popular variants + chemical formulas become `skos:altLabel`
   — those are what NER matches; the concept is what it links to.
2. **Chemical formulas are altLabels** (LiF, BeF2, LiF-BeF2, INOR-8…), because that's
   how the corpus and the NIST `Salt` column actually write them.
3. **Fluorides only** — chlorides (220 docs) are excluded per the data scope.
4. **Minted concepts** get a local namespace + `skos:scopeNote` recording why INIS has
   no term. This set (FLiNaK, the fuel/coolant/flush triad, Hastelloy-N labels, optional
   MSBR) is itself a small demo of vocabulary evolution.
5. Every concept carries a `skos:scopeNote` and provenance (`INIS:<date>` or `minted`).

## Resolution (2026-07-16)

- **Adopted: recommended core (~29 concepts).** The optional context facet is deferred,
  not dropped — revisit if the NER pipeline needs more surface area.
- No concept drops or additional altLabels requested at this stage.
- **Seed vs evolution (2026-07-17):** all 29 concepts load as the seed vocabulary
  (`ontology/vocab.ttl`); the self-evolution demo targets are chosen *outside* the vocab
  (`solubility` for a property, `graphite`/moderators for a class) so the demo starts from
  genuine ignorance. Consequently the seed ontology now carries all 8 vocab properties.
- **Built (Phase C):** `ontology/vocab.ttl` — 29 SKOS concepts, `closeMatch`-aligned to
  the ontology, rdflib-validated (248 triples; all references resolve).
