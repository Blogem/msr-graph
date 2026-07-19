# Proposal: ocr-robust-salt-linking

## Why

The manual acceptance run (chunk 6 / `ner-entity-linking` task 11.1) revealed that on the **real** ORNL-TM-2316 OCR, **zero** text mentions link to any of the 185 loaded `MoltenSalt` individuals (`layer3=0`). The corpus OCR renders chemical subscripts as commas/periods (`BeF2`→`BeF,`, `ThF4`→`ThF,`, `UF4`→`UF,`, e.g. `"LiF-BeF,-ThF,-UF, (65-28-5-1-1 mole %)"`) and writes compositions as `mole %` (29×), never `mol%` (0×). The lexical layers built to catch salts all miss these forms, so the M3 anchor criterion — `LiF-BeF2` → the loaded salt individual — is unmet and the salt catalog goes unused. The chunk-6 precision gate passed only because its gold fixture used clean synthetic text; this change closes the gap between the synthetic fixture and the real corpus so the change can actually pass its own manual gate.

## What Changes

- **OCR-variant seeding for known formulas**: the matcher-seeding step generates surface variants that model the OCR subscript artifact — a trailing comma/period standing in for a subscript digit on a known compound/salt token (`BeF2`→`BeF,`/`BeF.`, `ThF4`→`ThF,`, `LiF-BeF2`→`LiF-BeF,`). Variants are generated **only from the graph's known catalog formulas** (compounds + `MoltenSalt` labels), so matching stays precision-safe — it can only recognize OCR forms of entities that actually exist, never invent one.
- **OCR-tolerant composition parsing**: the formula normalizer and the linker's salt-candidate detection accept `mole %` and `mol %` (with the intervening `e`/space) in addition to `mol%`, and treat a comma/period after a fluoride element as a possible subscript when reconstructing a candidate formula for lookup against the catalog.
- **Fuzzy fallback tuned for short chemistry tokens**: revisit `fuzzy_min_token_length` so genuine short formula tokens (`LiF`, `BeF`, `KF`, 3 chars) are eligible for the bounded fuzzy layer, without loosening precision (still a high threshold, still links only to existing labels).
- **Real-OCR test fixtures**: add fixtures derived from the actual `data/corpus/ORNL-TM-2316/normalized.txt` salt forms (comma-subscript, `mole %`, ternary/quaternary mixtures) to the matcher/linker tests and the precision harness, so the suite exercises the forms the corpus really contains — and re-run the M3 anchor.

## Capabilities

### New Capabilities

None — this change enhances existing chunk-6 capabilities; it introduces no new capability.

### Modified Capabilities

- `entity-ruler-seeding`: pattern-variant generation additionally emits OCR-subscript variants (comma/period for a subscript digit) for the graph's known compound/salt formulas, so the seeded matcher recognizes the corpus's OCR forms.
- `salt-formula-normalization`: the normalizer parses OCR salt forms — comma/period-as-subscript and `mole %`/`mol %` compositions — mapping them to the same canonical form and loader-minted salt IRI as the clean forms.
- `entity-linking`: the layered pipeline detects OCR salt-candidate spans (comma-subscript formulas, `mole %` tails) and the bounded fuzzy fallback admits short chemistry tokens; a real-OCR-derived sample is added to the precision harness and the anchor mentions resolve to the loaded salt individuals.

## Impact

- **Code** (chunk-6 `extraction/src/msr_extraction/`): `variants.py` (or `seeding.py`) OCR-variant generation from catalog formulas; `formula.py` OCR-form parsing (comma/period subscript, `mole %`); `linker.py` candidate regex (`_FORMULA_CANDIDATE_RE`, `_COMPOSITION_TAIL`) + fuzzy min-token handling; `config.py` if the fuzzy min-token knob changes.
- **Tests**: real-OCR fixtures added to the matcher/linker tests, the formula tests, and the precision harness (`extraction/tests/`), plus the guarded integration/anchor assertions.
- **No graph, schema, or loader changes**; reads through the existing `core-dataset-access` contract; consumes chunk-5 `normalized.txt`/`segments.jsonl` **unchanged** (subscript restoration is done at match time against the known catalog, not by re-normalizing the corpus — kept out of `corpus-normalization` to stay precision-safe and avoid ambiguous comma-vs-punctuation rewriting).
- **Depends on**: `ner-entity-linking` (chunk 6 — the capabilities this modifies); that change should be archived before, or together with, this one. No new runtime dependencies.
