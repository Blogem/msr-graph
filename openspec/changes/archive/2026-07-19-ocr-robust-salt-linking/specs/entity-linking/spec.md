# entity-linking (delta)

## ADDED Requirements

### Requirement: OCR salt-candidate detection resolves composed mentions to loaded individuals
The pipeline SHALL detect salt-candidate spans written in the corpus OCR forms — comma/period subscripts and `mole %` / `mol %` composition tails — and resolve a composed OCR salt mention to the loaded `MoltenSalt` individual via the formula normalizer, recording the resolving layer as the formula layer (layer 3). On the real ORNL-TM-2316 normalized text, the composed salt anchor MUST resolve to the loaded salt individual, not merely to a vocab concept.

#### Scenario: Real-OCR composed salt resolves to the loaded individual
- **WHEN** the pipeline links the ORNL-TM-2316 segment containing `LiF-BeF, (66-34 mole %)`
- **THEN** the span resolves via the formula normalizer (layer 3) to `msrd:salt-BeF2-LiF-34.0-66.0`

#### Scenario: Anchor over the real corpus links at least one salt individual
- **WHEN** a link run processes the real ORNL-TM-2316 normalized text
- **THEN** at least one mention links to a loaded `MoltenSalt` individual (the formula-layer count is greater than zero)

### Requirement: Bounded fuzzy fallback admits short chemistry tokens
The bounded fuzzy fallback SHALL be eligible for short chemistry formula tokens (e.g. the 3-character `LiF`, `BeF`, `KF`), while retaining a high similarity threshold and linking only to an existing known label; the minimum token length governing fuzzy eligibility MUST remain a configuration value, not a hardcoded constant.

#### Scenario: Short OCR-mangled formula token links above threshold
- **WHEN** a short formula token above the similarity threshold matches a known label
- **THEN** the fuzzy fallback links it to that known label

#### Scenario: Below-threshold short token is not force-linked
- **WHEN** a short formula token's best fuzzy match is below the configured threshold
- **THEN** the fallback does not link it (it proceeds to disambiguation / novel)

### Requirement: Precision harness exercises real-OCR salt forms
The labelled-sample precision harness SHALL include real-OCR-derived composed-salt cases taken from the actual corpus normalized text and expecting the loaded salt IRIs, so the ≥ 0.90 precision gate cannot pass while composed OCR salt mentions go unlinked. Recall MUST continue to be reported but not gated.

#### Scenario: Harness includes real-OCR salt cases
- **WHEN** the precision harness runs
- **THEN** its gold fixture includes composed-salt mentions in the corpus OCR forms (comma subscripts, `mole %`) whose expected targets are loaded salt IRIs

#### Scenario: Gate fails if real-OCR composed salts do not link
- **WHEN** the pipeline fails to link the real-OCR composed-salt cases to their loaded salt IRIs
- **THEN** measured precision/recall on those cases causes the harness to surface the miss (the gate is not green while the anchor is unlinked)
