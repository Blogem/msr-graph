# salt-formula-normalization (delta)

## ADDED Requirements

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
