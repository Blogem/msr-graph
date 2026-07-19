# Tasks: ocr-robust-salt-linking

## 1. OCR-variant seeding (`entity-ruler-seeding`)

- [x] 1.1 Extend pattern-variant generation to emit OCR-subscript variants (a comma or period standing in for a subscript digit) for a formula token carrying a subscript, e.g. `BeF2`→`BeF,`/`BeF.`, `LiF-BeF2`→`LiF-BeF,`; keep it a pure, deterministic function
- [x] 1.2 Generate OCR variants only from the graph's known catalog compound/salt formulas and wire them into the matcher seeding (never invent a non-catalog formula)

## 2. OCR-tolerant formula normalization (`salt-formula-normalization`)

- [x] 2.1 Parse comma/period-as-subscript element tokens, resolving each stripped root against the known catalog compound set (`BeF,`→`BeF2` only when `BeF2` is loaded); leave an unknown root unresolved
- [x] 2.2 Accept `mole %` / `mol %` / `mol.%` composition tails in addition to `mol%` (formula inline-composition parsing)
- [x] 2.3 Feed the reconstructed `(components, composition)` through the unchanged canonicalization rule so an OCR form yields the same canonical string + `msrd:salt-…` IRI as the clean form; do not modify `testdata/salt-canonicalization.json`

## 3. OCR-robust layered linker (`entity-linking`)

- [x] 3.1 Extend the linker salt-candidate detection (`_FORMULA_CANDIDATE_RE` / `_COMPOSITION_TAIL`) to match comma/period-subscript formulas and `mole %` tails, and resolve composed OCR salt spans to the loaded individual via the normalizer (layer 3), preserving the composed-salt-beats-concept precedence
- [x] 3.2 Make the bounded fuzzy fallback eligible for short chemistry tokens (e.g. 3-char `LiF`/`BeF`) while keeping the high threshold and existing-label-only rule

## 4. Config

- [x] 4.1 Introduce/adjust the fuzzy minimum-token-length as an injectable config value (if 3.2 needs it), keeping it test-pinned rather than hardcoded

## 5. Tests

- [x] 5.1 Pattern-variant tests: known formula → expected OCR-subscript variants; a non-catalog formula yields no OCR variant
- [x] 5.2 Formula-normalizer tests: `LiF-BeF, (66-34 mole %)` → `msrd:salt-BeF2-LiF-34.0-66.0`; `mole %`/`mol %` parsing; unknown-component form → unresolved; the shared `testdata/salt-canonicalization.json` still passes unchanged
- [x] 5.3 Matcher/linker tests on real-OCR fixture sentences (comma-subscript compounds → concept, e.g. `BeF,`→beryllium-fluorides; composed OCR salt → loaded individual at layer 3; ternary/quaternary `LiF-BeF,-ThF,-UF,`; precedence preserved)
- [x] 5.4 Bounded-fuzzy tests for short chemistry tokens: accept-above-threshold / no-link-below-threshold
- [x] 5.5 Precision harness: add real-OCR-derived composed-salt cases drawn from MULTIPLE curated docs (e.g. `LiF-BeF, (66-34 mol %)`, `LiF-BeF,-ThF, (72-16-12 mol %)`, `LiF-UF, (73-27 mol %)`, `NaF-ZrF, (53-47 mol %)`) expecting the loaded salt IRIs; precision ≥ 0.90 gate holds, recall reported not gated
- [x] 5.6 Regression: full chunk-6 extraction suite stays green with the real-OCR salt cases now covered

## 6. Manual acceptance re-run

- [ ] 6.1 Rebuild the extraction image and re-run `link` over the full curated corpus; confirm `layer3 > 0` in every document (currently 0 corpus-wide), the anchor `LiF-BeF2` (OCR `LiF-BeF, … mol %`) resolves to `msrd:salt-BeF2-LiF-34.0-66.0`, spot-check `mentions.jsonl` + the `msr:Mention` triples in `urn:msr:data`, and confirm re-run idempotency — then re-check `ner-entity-linking` task 11.1
