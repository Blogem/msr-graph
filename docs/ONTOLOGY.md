# MSR Seed Ontology — Draft (Phase B)

Status: **approved & materialized (2026-07-16).** This is the seed T-Box that NER
populates and the self-evolution loop extends. It reuses DIAMOND *labels* (aligned by
`rdfs:seeAlso`) but keeps its own structure, and it adds the `PropertyMeasurement`
pattern — the join that lets a NIST row attach to a salt. The Turtle below is
materialized and rdflib-validated as **`ontology/msr.ttl`** (T-Box, 145 triples) and
**`ontology/example-flibe.ttl`** (worked A-Box, 51 triples — IRIs follow the pipeline
minting contract: deterministic, no blank nodes, components alphabetized).

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
| salt, its constituents + mole fractions, role, reactor | the numeric coefficients `c0..c4` |
| which property, unit (QUDT), validity temp range, equation form, uncertainty | keyed by `dataLocator` |
| provenance (NIST dataset DOI, ORNL citation), SKOS links | — |

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
MoltenSaltReactor                ≈ diamond:MoltenSaltReactor (we do NOT inherit its FastNeutronReactor parent)
SaltRole                         individuals: FuelSalt, CoolantSalt(≈diamond:Coolant), FlushSalt
Document / Dataset               (prov:Entity — provenance)
```

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
    rdfs:seeAlso nuclear:000258 ;   # DIAMOND MoltenSalt (⊂ LiquidFuel — intentionally NOT inherited)
    skos:closeMatch voc:molten-salts .

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
    rdfs:seeAlso nuclear:000242 ; skos:closeMatch voc:density .
msr:viscosity a msr:PhysicalProperty ;
    rdfs:label "viscosity" ; msr:quantityKind qk:DynamicViscosity ; msr:canonicalUnit unit:MilliPA-SEC ;
    rdfs:seeAlso nuclear:000243 ; skos:closeMatch voc:viscosity .
msr:surfaceTension a msr:PhysicalProperty ;
    rdfs:label "surface tension" ; msr:quantityKind qk:SurfaceTension ; msr:canonicalUnit unit:MilliN-PER-M ;
    rdfs:seeAlso nuclear:000158 ; skos:closeMatch voc:surface-tension .   # DIAMOND InterfacialTension
msr:electricalConductivity a msr:PhysicalProperty ;
    rdfs:label "electrical conductivity" ; msr:quantityKind qk:ElectricConductivity ; msr:canonicalUnit unit:S-PER-CentiM ;
    rdfs:comment "No DIAMOND equivalent — this seed fills the gap." ; skos:closeMatch voc:electric-conductivity .
# document-sourced properties (values come from the archive, not NIST)
msr:thermalConductivity a msr:PhysicalProperty ;
    rdfs:label "thermal conductivity" ; msr:quantityKind qk:ThermalConductivity ; msr:canonicalUnit unit:W-PER-M-K ;
    skos:closeMatch voc:thermal-conductivity .
msr:specificHeat a msr:PhysicalProperty ;
    rdfs:label "specific heat" ; msr:quantityKind qk:SpecificHeatCapacity ; msr:canonicalUnit unit:J-PER-KiloGM-K ;
    skos:closeMatch voc:specific-heat .
msr:vaporPressure a msr:PhysicalProperty ;
    rdfs:label "vapor pressure" ; msr:quantityKind qk:VaporPressure ; msr:canonicalUnit unit:PA ;
    skos:closeMatch voc:vapor-pressure .
msr:meltingPoint a msr:PhysicalProperty ;
    rdfs:label "melting point" ; msr:quantityKind qk:Temperature ; msr:canonicalUnit unit:K ;
    skos:closeMatch voc:melting-point .

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

### Reactor & role layer
msr:MoltenSaltReactor a owl:Class ;
    rdfs:label "MoltenSaltReactor" ;
    rdfs:seeAlso nuclear:000364 ;   # DIAMOND MoltenSaltReactor (⊂ FastNeutronReactor — intentionally NOT inherited; MSRE was thermal)
    skos:closeMatch voc:molten-salt-reactors .
msr:usedIn a owl:ObjectProperty ; rdfs:domain msr:MoltenSalt ; rdfs:range msr:MoltenSaltReactor .

msr:SaltRole a owl:Class ;
    rdfs:comment "The functional role a salt plays (ORNL-TM-2316 triad). Modeled as a role, not baked into the class." .
msr:hasRole a owl:ObjectProperty ; rdfs:domain msr:MoltenSalt ; rdfs:range msr:SaltRole .
msr:FuelSalt    a msr:SaltRole ; skos:closeMatch voc:fuel-salt .
msr:CoolantSalt a msr:SaltRole ; rdfs:seeAlso nuclear:000223 ; skos:closeMatch voc:coolant-salt .   # DIAMOND Coolant
msr:FlushSalt   a msr:SaltRole ; skos:closeMatch voc:flush-salt .

### Provenance layer
msr:Document a owl:Class ; rdfs:subClassOf prov:Entity .
msr:Dataset  a owl:Class ; rdfs:subClassOf prov:Entity .
msr:citedIn  a owl:ObjectProperty ; rdfs:domain msr:PropertyMeasurement ; rdfs:range msr:Document .
```

## A-Box — worked FLiBe example (real NIST row)

IRIs follow the **pipeline minting contract** (ARCHITECTURE.md → Runtime contracts):
salt components are alphabetized with composition values reordered in lockstep
(`LiF-BeF2,34.0-66.0` → canonical `BeF2-LiF | 66.0-34.0`), constituents get
deterministic IRIs instead of blank nodes, and measurement IRIs are slugged locators.
The chunk-2 loader mints identical IRIs, so re-asserting these salts is a
set-semantics no-op; the role/reactor edges are hand-curated facts the loader
cannot derive from NIST.

```turtle
# pure compounds
msrd:LiF  a msr:ChemicalCompound ; rdfs:label "LiF"  ; skos:closeMatch voc:lithium-fluorides .
msrd:BeF2 a msr:ChemicalCompound ; rdfs:label "BeF2" ; skos:closeMatch voc:beryllium-fluorides .

# LiF-BeF2 melt, 34 mol% LiF / 66 mol% BeF2 — canonical BeF2-LiF | 66.0-34.0
# (verified NIST density row `LiF-BeF2,34.0-66.0,P1,800,1080,,2.413,-4.88E-4` → ρ(T)=2.413 − 4.88e-4·T)
msrd:salt-BeF2-LiF-66.0-34.0 a msr:MoltenSalt ;
    rdfs:label "BeF2-LiF (66.0-34.0 mol%)" ;
    msr:hasConstituent msrd:salt-BeF2-LiF-66.0-34.0-c-BeF2 ,
                       msrd:salt-BeF2-LiF-66.0-34.0-c-LiF ;
    skos:closeMatch voc:flibe .
msrd:salt-BeF2-LiF-66.0-34.0-c-BeF2 a msr:Constituent ;
    msr:ofCompound msrd:BeF2 ; msr:moleFraction 0.66 .
msrd:salt-BeF2-LiF-66.0-34.0-c-LiF a msr:Constituent ;
    msr:ofCompound msrd:LiF ; msr:moleFraction 0.34 .

msrd:m-nist-srd27-density-BeF2-LiF-66.0-34.0 a msr:PropertyMeasurement ;
    msr:ofSalt msrd:salt-BeF2-LiF-66.0-34.0 ;
    msr:forProperty msr:density ;
    msr:hasUnit unit:GM-PER-CentiM3 ;
    msr:equationForm msr:Linear ;
    msr:validTempMin 800.0 ; msr:validTempMax 1080.0 ;
    msr:dataLocator "nist-srd27/density#BeF2-LiF|66.0-34.0" ;
    prov:wasDerivedFrom msrd:nist-srd27 ;
    msr:citedIn msrd:ORNL-TM-2316 .

# MSRE and its coolant salt — canonical FLiBe (66 mol% LiF / 34 mol% BeF2 → BeF2-LiF | 34.0-66.0)
msrd:MSRE a msr:MoltenSaltReactor ; rdfs:label "MSRE" ; skos:closeMatch voc:msre-reactor .
msrd:salt-BeF2-LiF-34.0-66.0 a msr:MoltenSalt ;
    rdfs:label "BeF2-LiF (34.0-66.0 mol%)" ;
    rdfs:comment "MSRE coolant salt — FLiBe (LiF-BeF2 66-34)." ;
    msr:hasConstituent msrd:salt-BeF2-LiF-34.0-66.0-c-BeF2 ,
                       msrd:salt-BeF2-LiF-34.0-66.0-c-LiF ;
    msr:hasRole msr:CoolantSalt ; msr:usedIn msrd:MSRE ;
    skos:closeMatch voc:flibe , voc:coolant-salt .
msrd:salt-BeF2-LiF-34.0-66.0-c-BeF2 a msr:Constituent ;
    msr:ofCompound msrd:BeF2 ; msr:moleFraction 0.34 .
msrd:salt-BeF2-LiF-34.0-66.0-c-LiF a msr:Constituent ;
    msr:ofCompound msrd:LiF ; msr:moleFraction 0.66 .

# provenance
msrd:nist-srd27   a msr:Dataset  ; rdfs:label "NIST Molten Salts DB (SRD 27)" ; dcterms:identifier "doi:10.18434/mds2-2298" .
msrd:ORNL-TM-2316 a msr:Document ; rdfs:label "Physical Properties of MSR Fuel, Coolant, and Flush Salts (Cantor, 1968)" ; dcterms:identifier "ORNL-TM-2316" .
```

Companion external table (SQLite) — the coefficients the graph does **not** hold:

| dataLocator | c0 | c1 | c2 | c3 |
|-------------|----|----|----|----|
| `nist-srd27/density#BeF2-LiF\|66.0-34.0` | 2.413 | -4.88e-4 | | |

## How the AI analysis uses it (worked query)

Question: *"What is the density of this LiF-BeF2 melt at 900 K?"*

1. **SPARQL the graph** → find the measurement for the salt: property `density`, unit
   `g·cm⁻³`, form `Linear` (`c0 + c1*T`), valid 800–1080 K (900 K is in range ✓),
   locator `nist-srd27/density#BeF2-LiF|66.0-34.0`.
2. **Resolve the locator** in SQLite → `c0=2.413, c1=-4.88e-4`.
3. **Evaluate** `2.413 + (-4.88e-4)(900) = 1.974 g·cm⁻³`.

The graph supplied the *meaning and method*; the table supplied the *numbers*; the answer
is grounded in both. The same salt is described qualitatively in ORNL-TM-2316 (via
`msr:citedIn`), which is where the NER-populated unstructured side connects.

```sparql
SELECT ?prop ?unit ?form ?tmin ?tmax ?locator WHERE {
  ?m msr:ofSalt msrd:salt-BeF2-LiF-66.0-34.0 ;
     msr:forProperty ?prop ; msr:hasUnit ?unit ;
     msr:equationForm/msr:formula ?form ;
     msr:validTempMin ?tmin ; msr:validTempMax ?tmax ;
     msr:dataLocator ?locator .
}
```

## Self-evolution hook

The property layer is deliberately shallow so growth is cheap: adding a new property =
**one** `msr:PhysicalProperty` individual + its `quantityKind` + `canonicalUnit`. The seed
carries eight properties (all mirrored in the vocabulary); the self-evolution worked
example discovers a *ninth* — `solubility` (280 corpus docs, an INIS descriptor, absent
from the seed) — plus a new material/moderator branch from `graphite`. See ARCHITECTURE.md.

## Open items / notes

- DIAMOND alignment IRIs are real (`nuclear:000258` MoltenSalt, `000364` MoltenSaltReactor,
  `000242` Density, `000243` Viscosity, `000158` InterfacialTension, `000223` Coolant) but
  are non-dereferenceable opaque URIs; `seeAlso` is nominal alignment only.
- QUDT unit IRIs shown are the intended targets; verify exact spellings at build time
  (esp. `unit:S-PER-CentiM` for S/cm — may need `unit:S-PER-M` + a conversion note).
  **Assigned to chunk 2** (`load-nist-structured-data`): the loader validates every unit
  IRI it emits against the vendored QUDT allowlist and fails loudly on unknowns.
- ~~`voc:*` SKOS targets are dangling until Phase C builds the vocabulary scheme.~~
  Resolved: `ontology/vocab.ttl` is built and validated (Phase C, 2026-07-17).
- Role is attached to a salt-in-reactor-context individual (POC simplification); a salt
  used in two reactors with two roles would need role reification later.
