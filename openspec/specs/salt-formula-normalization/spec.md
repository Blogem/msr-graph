# salt-formula-normalization Specification

## Purpose
TBD - created by archiving change ner-entity-linking. Update Purpose after archive.
## Requirements
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

### Requirement: Parse OCR salt-mention forms against the known catalog
The normalizer SHALL accept OCR salt-mention forms — a comma or period standing in for a subscript digit on a fluoride element token (e.g. `BeF,`/`BeF.` for `BeF2`, `ThF,` for `ThF4`), and `mole %` / `mol %` / `mol.%` compositions in addition to `mol%` — and resolve each element token against the graph's known catalog compounds, producing the SAME canonical form and loader-minted salt IRI as the corresponding clean form. A token whose comma/period-stripped root does NOT correspond to a known catalog compound MUST NOT be reconstructed, and a span with any unresolved component MUST be left unresolved rather than mapped to a partial or guessed salt.

#### Scenario: Comma-subscript composed mention maps to the loaded individual
- **WHEN** the normalizer processes the OCR form `LiF-BeF, (66-34 mole %)` (the MSRE-coolant FLiBe composition)
- **THEN** it maps to the loader-minted salt individual IRI `msrd:salt-BeF2-LiF-34.0-66.0`, identical to the clean-form result

#### Scenario: mole %/mol % compositions accepted
- **WHEN** a composition is written `66-34 mole %` (or `mol %`) rather than `mol%`
- **THEN** the normalizer parses the composition and canonicalizes it identically to the `mol%` form

#### Scenario: Unresolved component yields no link
- **WHEN** an OCR salt form contains a component whose stripped root is not a known catalog compound
- **THEN** the span is left unresolved (no partial or guessed salt IRI is produced)

### Requirement: Canonicalization rule and shared fixture unchanged
OCR-form parsing SHALL be a front-end that feeds the existing, unchanged canonicalization rule (byte-wise alphabetization, lockstep composition reorder, one-decimal mole %). The change MUST NOT modify `testdata/salt-canonicalization.json`, and the Python normalizer MUST continue to pass every case in it.

#### Scenario: Shared drift-guard fixture still passes
- **WHEN** the Python normalizer runs against every case in the unchanged `testdata/salt-canonicalization.json`
- **THEN** each case still produces the fixture's expected canonical string and salt IRI

