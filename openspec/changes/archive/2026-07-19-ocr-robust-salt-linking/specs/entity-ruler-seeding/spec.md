# entity-ruler-seeding (delta)

## ADDED Requirements

### Requirement: OCR-subscript surface variants for known formulas
Pattern-variant generation SHALL additionally emit surface variants that model the corpus OCR subscript artifact — a comma or a period standing in for a subscript digit — for each known catalog compound and `MoltenSalt` formula token that carries a subscript digit, so the seeded matcher recognizes the OCR forms of entities that actually exist. Variant generation MUST remain a pure, deterministic function of its input and MUST derive OCR variants ONLY from the graph's known formulas — it MUST NOT invent a formula the catalog has not loaded.

#### Scenario: Comma and period subscript variants are generated
- **WHEN** OCR-variant generation runs on a known compound formula such as `BeF2`
- **THEN** it yields the comma and period subscript forms (`BeF,`, `BeF.`) as additional exact patterns for the same target

#### Scenario: Multi-component salt formula OCR variants
- **WHEN** OCR-variant generation runs on a multi-component formula such as `LiF-BeF2`
- **THEN** it yields the per-component comma/period subscript form (e.g. `LiF-BeF,`) for the same target

#### Scenario: OCR variants derive only from known formulas
- **WHEN** a formula token is not among the graph's loaded compounds/salts
- **THEN** no OCR-subscript variant is seeded for it (matching stays anchored to known entities)
