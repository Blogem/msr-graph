# MSR Seed Ontology — Draft (Phase B)

Status: **approved & materialized (2026-07-16); updated for real-data grounding
(`ground-demo-in-real-docs`).** This is the seed T-Box that NER populates and the
self-evolution loop extends. It reuses DIAMOND *labels* (aligned by `rdfs:seeAlso`) but
keeps its own structure, and it adds the `PropertyMeasurement` pattern — the join that
lets a NIST row attach to a salt. The Turtle below is materialized and rdflib-validated
as **`ontology/msr.ttl`** (T-Box). **There is no seed A-Box:** the earlier worked-example
Turtle file was a hand-curated FLiBe salt/measurement duplicate plus fabricated
`skos:closeMatch`/`hasRole`/`usedIn` facts, and it has been deleted entirely
(`ground-demo-in-real-docs`) — `urn:msr:data` is populated exclusively by the real NIST
loader (chunk 2) and the extraction pipeline (chunks 5/6), never by hand. IRIs still
follow the pipeline minting contract below (deterministic, no blank nodes, components
alphabetized); it's just the loader and extraction writers that mint them now, not a
checked-in Turtle file.

## Three design decisions (my picks — react to these)

1. **Salt composition → reified constituents.** A `MoltenSalt` links to `Constituent`
   nodes each carrying `ofCompound` + `moleFraction`. *Chosen over* a flat composition
   string, because it makes composition queryable ("salts with >30 mol% BeF2") and maps
   1:1 onto NIST's `Salt` + `Composition range` columns. NIST composition *ranges* are
   supported with optional `moleFractionMin/Max`.
2. **Property-vs-temperature → store the correlation, not materialized points.** A
   measurement records an `equationForm` (Linear / Polynomial / Arrhenius / DiscretePoint)
   + validity range; the **coefficients live in the external table**, and each
   `EquationForm` carries a `msr:formula` so the analysis layer knows how to evaluate.
   *Chosen over* pre-computing discrete points (lossy, bulky) — and evaluating on demand
   is itself a nice "AI uses the model to compute" demo.
3. **QUDT → reference, don't import.** We use QUDT `QuantityKind` and `Unit` IRIs as
   values (standards-aligned, upgradeable to full unit conversion later) but do **not**
   load the large QUDT ontology into GraphDB. *Chosen over* full import (weight) or plain
   unit strings (no alignment).

## What lives where (the federation boundary)

| In the graph (triples) | In the external table (SQLite) |
|------------------------|-------------------------------|
| salt, its constituents + mole fractions | the numeric coefficients `c0..c4` |
| which property, unit (QUDT), validity temp range, equation form, uncertainty | keyed by `dataLocator` |
| provenance (NIST dataset DOI, ORNL citation), mentions/`linksTo` | — |

(Salt functional role and reactor association — `hasRole`/`usedIn` — are real,
extractable facts, not modeled in the current TBox; see *Reactor & role layer* below.)

The graph answers *what/how/where-from*; the table holds the *numbers*. This is the
"connect structured data without loading it" intent from the data scope.

## Class hierarchy

```
Substance
  ├─ ChemicalCompound            (pure: LiF, BeF2, …)
  └─ MoltenSalt                  ≈ diamond:MoltenSalt (we do NOT inherit its LiquidFuel parent)
Constituent                      (reifies compound + mole fraction inside a MoltenSalt)
PhysicalProperty                 8 individuals: density, viscosity, surfaceTension, electricalConductivity (NIST);
                                 thermalConductivity, specificHeat, vaporPressure, meltingPoint (documents)
PropertyMeasurement              (salt × property × source correlation; coefficients external)
EquationForm                     individuals: Linear, Polynomial2, Polynomial3, Arrhenius, DiscretePoint
Document / Dataset               (prov:Entity — provenance)
Mention                          (report# + char-offset span; msr:linksTo a concept or a MoltenSalt individual)
```

`MoltenSaltReactor`/`SaltRole` (and DIAMOND's `MoltenSaltReactor`/`Coolant` alignment) are
**not currently in the TBox** — see *Reactor & role layer*, below.

## T-Box (Turtle)

```turtle
@prefix msr:     <https://w3id.org/msr-kg/ontology#> .   # this ontology (placeholder IRI)
@prefix msrd:    <https://w3id.org/msr-kg/data#> .        # instance data
@prefix voc:     <https://w3id.org/msr-kg/vocab#> .       # SKOS concepts (built in Phase C)
@prefix qudt:    <http://qudt.org/schema/qudt/> .
@prefix qk:      <http://qudt.org/vocab/quantitykind/> .
@prefix unit:    <http://qudt.org/vocab/unit/> .
@prefix prov:    <http://www.w3.org/ns/prov#> .
@prefix skos:    <http://www.w3.org/2004/02/skos/core#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix owl:     <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:    <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:     <http://www.w3.org/2001/XMLSchema#> .
@prefix nuclear: <nuclear:> .   # DIAMOND opaque class IRIs — non-dereferenceable, alignment only

### Substance layer
msr:Substance a owl:Class .
msr:ChemicalCompound a owl:Class ; rdfs:subClassOf msr:Substance ;
    rdfs:comment "A pure chemical compound, e.g. LiF, BeF2." .
msr:MoltenSalt a owl:Class ; rdfs:subClassOf msr:Substance ;
    rdfs:label "MoltenSalt" ;
    rdfs:comment "A molten-salt melt at a defined composition; pure or a mixture." ;
    rdfs:seeAlso nuclear:000258 .   # DIAMOND MoltenSalt (⊂ LiquidFuel — intentionally NOT inherited)

msr:Constituent a owl:Class ;
    rdfs:comment "Reifies 'compound X at mole fraction f' within a MoltenSalt." .
msr:hasConstituent a owl:ObjectProperty ; rdfs:domain msr:MoltenSalt ; rdfs:range msr:Constituent .
msr:ofCompound     a owl:ObjectProperty ; rdfs:domain msr:Constituent ; rdfs:range msr:ChemicalCompound .
msr:moleFraction   a owl:DatatypeProperty ; rdfs:domain msr:Constituent ; rdfs:range xsd:decimal .
msr:moleFractionMin a owl:DatatypeProperty ; rdfs:domain msr:Constituent ; rdfs:range xsd:decimal .
msr:moleFractionMax a owl:DatatypeProperty ; rdfs:domain msr:Constituent ; rdfs:range xsd:decimal .

### Property layer  (8 seed properties: 4 NIST-sourced + 4 document-sourced)
msr:PhysicalProperty a owl:Class .
msr:quantityKind  a owl:ObjectProperty ; rdfs:range qudt:QuantityKind .
msr:canonicalUnit a owl:ObjectProperty ; rdfs:range qudt:Unit .

msr:density a msr:PhysicalProperty ;
    rdfs:label "density" ; msr:quantityKind qk:Density ; msr:canonicalUnit unit:GM-PER-CentiM3 ;
    rdfs:seeAlso nuclear:000242 .
msr:viscosity a msr:PhysicalProperty ;
    rdfs:label "viscosity" ; msr:quantityKind qk:DynamicViscosity ; msr:canonicalUnit unit:MilliPA-SEC ;
    rdfs:seeAlso nuclear:000243 .
msr:surfaceTension a msr:PhysicalProperty ;
    rdfs:label "surface tension" ; msr:quantityKind qk:SurfaceTension ; msr:canonicalUnit unit:MilliN-PER-M ;
    rdfs:seeAlso nuclear:000158 .   # DIAMOND InterfacialTension
msr:electricalConductivity a msr:PhysicalProperty ;
    rdfs:label "electrical conductivity" ; msr:quantityKind qk:ElectricConductivity ; msr:canonicalUnit unit:S-PER-CentiM ;
    rdfs:comment "No DIAMOND equivalent — this seed fills the gap." .
# document-sourced properties (values come from the archive, not NIST)
msr:thermalConductivity a msr:PhysicalProperty ;
    rdfs:label "thermal conductivity" ; msr:quantityKind qk:ThermalConductivity ; msr:canonicalUnit unit:W-PER-M-K .
msr:specificHeat a msr:PhysicalProperty ;
    rdfs:label "specific heat" ; msr:quantityKind qk:SpecificHeatCapacity ; msr:canonicalUnit unit:J-PER-KiloGM-K .
msr:vaporPressure a msr:PhysicalProperty ;
    rdfs:label "vapor pressure" ; msr:quantityKind qk:VaporPressure ; msr:canonicalUnit unit:PA .
msr:meltingPoint a msr:PhysicalProperty ;
    rdfs:label "melting point" ; msr:quantityKind qk:Temperature ; msr:canonicalUnit unit:K .

# Grounding note: a query term resolves to one of these individuals by matching its own
# rdfs:label above — not via a skos:closeMatch hop to a voc:* concept (that direction is a
# SKOS-range abuse: msr:PhysicalProperty individuals are not skos:Concepts). See "How the
# AI analysis uses it", below.

### Measurement layer
msr:PropertyMeasurement a owl:Class ;
    rdfs:comment "One salt × property × source correlation. Numeric coefficients are external (see dataLocator)." .
msr:ofSalt       a owl:ObjectProperty ; rdfs:domain msr:PropertyMeasurement ; rdfs:range msr:MoltenSalt .
msr:forProperty  a owl:ObjectProperty ; rdfs:domain msr:PropertyMeasurement ; rdfs:range msr:PhysicalProperty .
msr:hasUnit      a owl:ObjectProperty ; rdfs:domain msr:PropertyMeasurement ; rdfs:range qudt:Unit .
msr:equationForm a owl:ObjectProperty ; rdfs:domain msr:PropertyMeasurement ; rdfs:range msr:EquationForm .
msr:validTempMin a owl:DatatypeProperty ; rdfs:range xsd:decimal ; rdfs:comment "Kelvin." .
msr:validTempMax a owl:DatatypeProperty ; rdfs:range xsd:decimal ; rdfs:comment "Kelvin." .
msr:uncertainty  a owl:DatatypeProperty ; rdfs:range xsd:string .
msr:dataLocator  a owl:DatatypeProperty ; rdfs:range xsd:string ;
    rdfs:comment "Resolves to the coefficient row in the external NIST table. Federation pointer." .

msr:EquationForm a owl:Class .
msr:formula a owl:DatatypeProperty ; rdfs:domain msr:EquationForm ; rdfs:range xsd:string .
msr:Linear        a msr:EquationForm ; msr:formula "c0 + c1*T" .
msr:Polynomial2   a msr:EquationForm ; msr:formula "c0 + c1*T + c2*T^2" .
msr:Polynomial3   a msr:EquationForm ; msr:formula "c0 + c1*T + c2*T^2 + c3*T^3" .
msr:Arrhenius     a msr:EquationForm ; msr:formula "c0 * exp(c1 / T)" .   # NIST '+E'
msr:DiscretePoint a msr:EquationForm ; msr:formula "value at single T (c0 at T=c1)" .

### Provenance layer
msr:Document a owl:Class ; rdfs:subClassOf prov:Entity .
msr:Dataset  a owl:Class ; rdfs:subClassOf prov:Entity .
msr:citedIn  a owl:ObjectProperty ; rdfs:domain msr:PropertyMeasurement ; rdfs:range msr:Document .

### Mention / grounding layer (written by the linker, chunk 6)
msr:Mention a owl:Class ; rdfs:comment "A recognized text span; report# + char offsets are its identity." .
msr:surfaceForm a owl:DatatypeProperty ; rdfs:domain msr:Mention ; rdfs:range xsd:string .
msr:inDocument  a owl:ObjectProperty ;   rdfs:domain msr:Mention ; rdfs:range msr:Document .
msr:linksTo     a owl:ObjectProperty ;   rdfs:domain msr:Mention ;
    rdfs:comment "Resolves a mention to its target: a skos:Concept (bare name) or a msr:MoltenSalt individual (composed formula)." .
```

### Reactor & role layer — removed, deferred to chunk-7

`msr:MoltenSaltReactor`/`msr:usedIn` and `msr:SaltRole`/`msr:hasRole`
(`FuelSalt`/`CoolantSalt`/`FlushSalt`) previously existed here, populated only by the
deleted hand-curated seed A-Box. They are **real, extractable facts** —
`ORNL-TM-2316` line 371 states the 66-34 melt "has been used in the MSRE as the coolant and
as [flush]" — but nothing in the current pipeline derives them from text, so per the
project's "defer capabilities without a real source" principle the layer is removed for
now and returns in chunk-7 (`extract-property-relations`) once relation extraction can
populate it with real, provenanced facts. The vocabulary (`vocab.ttl`) keeps the
corresponding SKOS concepts (`voc:molten-salt-reactors`, `voc:fuel-salt`,
`voc:coolant-salt`, `voc:flush-salt`, `voc:msre-reactor`) so NER can still recognize the
surface forms today; they just don't resolve to a role/reactor individual until chunk-7.

## A-Box — no seed file; minted at runtime by the real pipeline

There is **no** checked-in A-Box (the earlier hand-curated worked-example Turtle file has
been deleted — see the removed *Reactor & role layer* note above). `urn:msr:data` is
populated only by:

1. `make load-nist` — the Go loader parses the vendored NIST fluoride CSVs and mints salt /
   constituent / `PropertyMeasurement` triples directly, with the numeric coefficients kept
   in SQLite.
2. `make ingest` — the extraction pipeline writes `msr:Document` provenance nodes per
   curated report.
3. `make link` — the linker writes `msr:Mention` triples for recognized spans in the
   curated documents' text.

IRIs still follow the **pipeline minting contract** (ARCHITECTURE.md → Runtime contracts):
salt components are alphabetized with composition values reordered in lockstep
(`LiF-BeF2,34.0-66.0` → canonical `BeF2-LiF | 34.0-66.0`), constituents get deterministic
IRIs instead of blank nodes, and measurement IRIs are slugged locators — so re-running the
loader is a set-semantics no-op. The real NIST FLiBe/MSRE-coolant row (`BeF2-LiF,34.0-66.0`,
already byte-sorted) mints the salt `msrd:salt-BeF2-LiF-34.0-66.0` and a density measurement
`msrd:m-nist-srd27-density-BeF2-LiF-34.0-66.0` (locator
`nist-srd27/density#BeF2-LiF|34.0-66.0`, coefficients `c0=2.413, c1=-4.88e-4` in SQLite).
That measurement's `msr:citedIn msrd:ORNL-TM-2316` is real: the document's OCR text contains
the composed mention `"LiF-BeF, (66-34 mole %)"` (OCR noise for `BeF2`), which the linker
resolves via `msr:linksTo` to this exact salt — the real, provenanced grounding edge the
agent uses (see *How the AI analysis uses it*, below). No role/reactor edges are minted for
this salt (deferred to chunk-7, above), and no `skos:closeMatch` is minted anywhere.

## How the AI analysis uses it (worked query)

Question: *"What is the density of the LiF-BeF2 (66-34 mol%) melt at 900 K?"*

1. **Ground the salt** — no `skos:closeMatch`, no seed A-Box: match a real `msr:Mention`
   whose `msr:surfaceForm` corresponds to the query's salt reference (tolerant of OCR noise
   — component-token + composition-digit containment) and follow its `msr:linksTo` to the
   `msr:MoltenSalt` individual. The matched Mention's `msr:inDocument` is the grounding
   evidence (here, `ORNL-TM-2316`).
2. **SPARQL the graph** → from that salt, find the measurement: property `density`, unit
   `g·cm⁻³`, form `Linear` (`c0 + c1*T`), valid 800–1080 K (900 K is in range ✓),
   locator `nist-srd27/density#BeF2-LiF|34.0-66.0`.
3. **Resolve the locator** in SQLite → `c0=2.413, c1=-4.88e-4`.
4. **Evaluate** `2.413 + (-4.88e-4)(900) = 1.974 g·cm⁻³`.

The graph supplied the *meaning, method, and grounding evidence*; the table supplied the
*numbers*; the answer is grounded in both, traceable end to end to a real document mention.
A property reference (e.g. "density") resolves the same way as step 2's `?prop` binding
below — by matching the query term against a `msr:PhysicalProperty`'s own `rdfs:label`, no
concept hop required.

```sparql
# Step 1 — ground the salt via the real mention (surface-form match tolerant of OCR noise)
SELECT ?salt ?doc WHERE {
  ?m a msr:Mention ; msr:surfaceForm ?sf ; msr:linksTo ?salt ; msr:inDocument ?doc .
  ?salt a msr:MoltenSalt .
  FILTER(CONTAINS(LCASE(?sf), "bef") && CONTAINS(?sf, "66") && CONTAINS(?sf, "34"))
}

# Step 2 — from the grounded salt, the measurement (?salt bound from step 1)
SELECT ?prop ?unit ?form ?tmin ?tmax ?locator WHERE {
  ?meas msr:ofSalt ?salt ;
        msr:forProperty ?prop ; msr:hasUnit ?unit ;
        msr:equationForm/msr:formula ?form ;
        msr:validTempMin ?tmin ; msr:validTempMax ?tmax ;
        msr:dataLocator ?locator .
  ?prop rdfs:label ?propLabel .
}
```

## Self-evolution hook

The property layer is deliberately shallow so growth is cheap: adding a new property =
**one** `msr:PhysicalProperty` individual + its `quantityKind` + `canonicalUnit`. The seed
carries eight properties (all mirrored in the vocabulary); the self-evolution worked
example discovers a *ninth* — `solubility` (280 corpus docs, an INIS descriptor, absent
from the seed) — plus a new material/moderator branch from `graphite`. See ARCHITECTURE.md.

## Open items / notes

- DIAMOND alignment IRIs are real (`nuclear:000258` MoltenSalt, `000242` Density,
  `000243` Viscosity, `000158` InterfacialTension) but are non-dereferenceable opaque
  URIs; `seeAlso` is nominal alignment only. (`000364` MoltenSaltReactor and `000223`
  Coolant were the reactor/role layer's DIAMOND targets; they're not in the live TBox
  currently — see the *Reactor & role layer* removal note above — and return with that
  layer in chunk-7.)
- QUDT unit IRIs shown are the intended targets; verify exact spellings at build time
  (esp. `unit:S-PER-CentiM` for S/cm — may need `unit:S-PER-M` + a conversion note).
  **Assigned to chunk 2** (`load-nist-structured-data`): the loader validates every unit
  IRI it emits against the vendored QUDT allowlist and fails loudly on unknowns.
- ~~`voc:*` SKOS targets are dangling until Phase C builds the vocabulary scheme.~~
  Resolved: `ontology/vocab.ttl` is built and validated (Phase C, 2026-07-17).
- ~~`voc:*` concepts cross-link to their `msr:` ontology term via `skos:closeMatch`.~~
  Removed (`ground-demo-in-real-docs`): that direction is a SKOS-range abuse (the target is
  an OWL class/individual/property, not a `skos:Concept`); grounding uses `msr:linksTo`
  (salts) and `rdfs:label` matching (properties) instead — see *How the AI analysis uses
  it*, above. The vocab concepts themselves are unaffected and still seed NER.
- Salt role / reactor association (`hasRole`/`usedIn`, and the role-reification question a
  salt used in two reactors with two roles would eventually raise) is deferred along with
  the rest of the *Reactor & role layer* to chunk-7 relation extraction — not modeled in the
  current TBox, see above.
