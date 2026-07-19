# salt-formula-normalization Specification

## Purpose

Define the Python chemical-formula normalizer that unifies salt-mention surface variants to the contract's canonical form and maps them to the loader-minted salt IRIs, so text mentions and NIST rows meet at exactly one IRI. This is the Python half of the deliberately-duplicated canonicalization rule, guarded against drift from the Go half by a shared fixture.

## ADDED Requirements

### Requirement: Canonicalize salt mentions to the contract form
The normalizer SHALL parse a salt mention into (compound, mole-fraction) structure and produce the canonical form defined by the salt-naming contract: components byte-wise alphabetized, composition values reordered in lockstep, mole percentages formatted to one decimal (e.g. `LiF-BeF2, 34-66` → `BeF2-LiF | 66.0-34.0`). Order and spacing variants of the same salt MUST normalize to one canonical form.

#### Scenario: Order variants unify
- **WHEN** the normalizer processes `BeF2-LiF` and `LiF-BeF2` at the same composition
- **THEN** both produce the identical canonical string

#### Scenario: Subscript and separator variants unify
- **WHEN** the normalizer processes surface variants such as `LiF·BeF₂` or `LiF-BeF2` (subscript/`·`/hyphen forms)
- **THEN** they normalize to the same canonical form as the plain formula

### Requirement: Map canonical form to the loader-minted salt IRI
For a salt mention that carries an explicit composition, the normalizer SHALL map the canonical form to the deterministic salt IRI minted by the chunk-2 loader (`msrd:salt-{formula}-{composition}`), so the mention links to the loaded `MoltenSalt` individual. A bare-formula mention carrying no composition SHALL resolve to the salt concept/compound family rather than guessing a specific composed individual.

#### Scenario: Composed mention resolves to the loaded individual
- **WHEN** a mention `LiF-BeF2 (66-34 mol%)` (the MSRE-coolant FLiBe composition) is normalized
- **THEN** it maps to the loader-minted salt individual IRI `msrd:salt-BeF2-LiF-34.0-66.0`

#### Scenario: Bare formula resolves to the concept, not a guessed composition
- **WHEN** a mention `LiF-BeF2` appears with no composition in context
- **THEN** it links to the salt concept (e.g. `voc:flibe`) and does not fabricate a specific composed-salt IRI

### Requirement: Pass the shared canonicalization fixture
The normalizer's test suite SHALL load the shared `testdata/salt-canonicalization.json` fixture authored by chunk 2 and pass every case in it — covering both fixed-composition cases (`is_range:false`, canonical string + ordered mole-% + salt IRI) and isotherm/composition-range cases (`is_range:true`, e.g. `KF-ZrF4 | ZrF4 0.0-33.3`) — pinning that the Go and Python canonicalization rules cannot drift. The change MUST NOT modify the fixture.

#### Scenario: Every fixed-composition case passes
- **WHEN** the Python normalizer runs against each `is_range:false` case in `testdata/salt-canonicalization.json`
- **THEN** each raw input produces the fixture's expected canonical string, ordered mole-%, and salt IRI

#### Scenario: Isotherm-range cases canonicalize identically to Go
- **WHEN** the Python normalizer runs against an `is_range:true` case (e.g. `KF-ZrF4` varying `ZrF4 0.0-33.3`)
- **THEN** it produces the fixture's expected range canonical form and salt IRI, matching the Go loader
