# unit-qudt-mapping Specification

## Purpose

Define the Python mapper that turns an extracted unit surface form into a canonical QUDT
`unit:` IRI and validates it against the vendored `ontology/qudt-units.json` allowlist
authored by chunk 2 — so a text-derived measurement carries exactly the same unit IRIs as
the NIST rows, and an unmappable or out-of-allowlist unit fails loudly rather than writing
an unvalidated unit.

## Requirements

### Requirement: Map unit surface forms to canonical QUDT IRIs
The mapper SHALL translate common unit surface forms found in the corpus to the canonical
QUDT `unit:` IRI for the corresponding property, consistent with the chunk-2
property→canonical-unit mapping: viscosity `cP`/`mPa·s` → `unit:MilliPA-SEC`, density
`g/cm³` → `unit:GM-PER-CentiM3`, surface tension `mN/m` → `unit:MilliN-PER-M`, electrical
conductivity `S/cm` → `unit:S-PER-CentiM`. The mapping SHALL be driven by the vendored
`ontology/qudt-units.json`, not hardcoded magic IRIs.

#### Scenario: A viscosity surface form maps to the canonical unit
- **WHEN** the mapper is given the extracted unit `cP` (or `mPa·s`) for a viscosity measurement
- **THEN** it returns `unit:MilliPA-SEC`

#### Scenario: A density surface form maps to the canonical unit
- **WHEN** the mapper is given the extracted unit `g/cm³` for a density measurement
- **THEN** it returns `unit:GM-PER-CentiM3`

### Requirement: Validate every mapped IRI against the vendored allowlist
The mapper SHALL validate the mapped `unit:` IRI against the vendored allowlist and SHALL
reject the relation when the surface form is unmappable or the resulting IRI is absent from
the allowlist, rather than writing an unvalidated unit — mirroring chunk 2's fail-loud unit
guard on the Python side.

#### Scenario: A known unit passes
- **WHEN** the mapped IRI is present in `ontology/qudt-units.json`
- **THEN** the unit is accepted and the measurement may be written

#### Scenario: An unmappable unit rejects the relation
- **WHEN** the extracted unit surface form has no mapping or maps to an IRI absent from the allowlist
- **THEN** the relation is rejected and no unit triple or row is written

### Requirement: Unit must be dimensionally consistent with the property
The mapper SHALL use the property→canonical-unit map to reject a relation whose extracted
unit is inconsistent with the extracted property (a unit that is not the property's
canonical unit family), so a value quoted in the wrong dimension is not admitted.

#### Scenario: A dimensionally inconsistent unit is rejected
- **WHEN** a `density` measurement is extracted with a unit that maps to the viscosity family (e.g. `mPa·s`)
- **THEN** the relation is rejected as dimensionally inconsistent with the property
