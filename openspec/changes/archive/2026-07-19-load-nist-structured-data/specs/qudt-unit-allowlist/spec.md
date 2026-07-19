# Spec: qudt-unit-allowlist

## ADDED Requirements

### Requirement: Vendored QUDT unit allowlist
The system SHALL vendor a flat allowlist of the permitted QUDT `unit:` and `qk:` IRIs together with the property→canonical-unit mapping (density→`unit:GM-PER-CentiM3`, viscosity→`unit:MilliPA-SEC`, surfaceTension→`unit:MilliN-PER-M`, electricalConductivity→`unit:S-PER-CentiM`), consistent with the ontology TBox `msr:canonicalUnit`. The allowlist SHALL be a committed file at `ontology/qudt-units.json` (a tracked path, so it is available to every checkout and reusable cross-language by chunk 8), not embedded in code and not tracked in the graph. QUDT is referenced as values only — the allowlist is not dereferenced against the QUDT ontology.

#### Scenario: Property maps to its canonical unit
- **WHEN** the loader needs the unit for a density measurement
- **THEN** it resolves `unit:GM-PER-CentiM3` from the vendored property→unit mapping

#### Scenario: Allowlist settles the S/cm spelling
- **WHEN** the electrical-conductivity unit is emitted
- **THEN** its IRI is the exact spelling pinned in the vendored allowlist (`unit:S-PER-CentiM`), resolving the open ONTOLOGY.md spelling question for the POC

### Requirement: Validate every emitted unit IRI
The loader SHALL validate every `hasUnit` IRI it emits against the vendored allowlist and SHALL abort the run with a loud error when an IRI is not present, rather than writing an unvalidated unit into the graph.

#### Scenario: Known unit passes
- **WHEN** the loader emits a unit IRI that is present in the allowlist
- **THEN** the triple is written and the run proceeds

#### Scenario: Unknown unit aborts the run
- **WHEN** the loader would emit a unit IRI absent from the allowlist
- **THEN** the run aborts with an error naming the offending IRI and no unvalidated unit triple is written
