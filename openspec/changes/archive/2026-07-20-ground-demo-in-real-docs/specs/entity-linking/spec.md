# entity-linking (delta)

## MODIFIED Requirements

### Requirement: Layered matching over segmented text
The pipeline SHALL link entities over the chunk-5 `data/corpus/{report#}/segments.jsonl` sentences using an ordered, precision-biased layer sequence — expanded exact matching, the chemical-formula normalizer, then a bounded fuzzy fallback — recording for each recognized span which layer resolved it and the target's kind (concept / class / salt individual). Layer 1 OCR normalization is chunk 5's pre-pass and is not repeated here.

#### Scenario: Anchor entities link to the correct targets
- **WHEN** the pipeline runs over ORNL-TM-2316 segments containing `LiF-BeF2`, `viscosity`, and `MSRE`
- **THEN** each links to its correct target (concept, class, or salt individual) with the resolving layer and target kind recorded

#### Scenario: FLiBe nickname is not an anchor (not attested in the curated corpus)
- **WHEN** the anchor set for the finalized 11-doc curated corpus is defined
- **THEN** the bare nickname `FLiBe` is excluded — `ground-demo-in-real-docs`'s design work found it does not appear in the curated document text (only in non-curated archive files), so no real mention of it could ever resolve; the composed salt mention (`LiF-BeF2`, including its OCR form `LiF-BeF, (66-34 mole %)`) remains attested and is covered by the "Salt mention resolves to the loaded individual" scenario below

#### Scenario: Salt mention resolves to the loaded individual
- **WHEN** a `LiF-BeF2` mention with a composition is linked
- **THEN** it resolves to the loaded `MoltenSalt` individual (via the formula normalizer), not merely to a vocab concept
