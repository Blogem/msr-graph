# entity-linking Specification

## Purpose

Define the layered, precision-biased linking pipeline that consumes chunk-5 `segments.jsonl`, resolves recognized spans to vocab concepts, ontology classes, and loaded salt individuals, and emits a per-span classification (linked vs. novel/unresolved). Precision is the gated quality metric; recall is reported but not gated.

## ADDED Requirements

### Requirement: Layered matching over segmented text
The pipeline SHALL link entities over the chunk-5 `data/corpus/{report#}/segments.jsonl` sentences using an ordered, precision-biased layer sequence — expanded exact matching, the chemical-formula normalizer, then a bounded fuzzy fallback — recording for each recognized span which layer resolved it and the target's kind (concept / class / salt individual). Layer 1 OCR normalization is chunk 5's pre-pass and is not repeated here.

#### Scenario: Anchor entities link to the correct targets
- **WHEN** the pipeline runs over ORNL-TM-2316 segments containing `LiF-BeF2`, `FLiBe`, `viscosity`, and `MSRE`
- **THEN** each links to its correct target (concept, class, or salt individual) with the resolving layer and target kind recorded

#### Scenario: Salt mention resolves to the loaded individual
- **WHEN** a `LiF-BeF2` mention with a composition is linked
- **THEN** it resolves to the loaded `MoltenSalt` individual (via the formula normalizer), not merely to a vocab concept

### Requirement: Bounded fuzzy fallback
The pipeline SHALL include a bounded `rapidfuzz` fallback with a configurable high similarity threshold and a minimum token length, applied only to spans unresolved by exact matching and the formula normalizer. The fallback MUST only link to an existing known label and MUST NOT create a novelty candidate; the threshold MUST be a configuration value, not hardcoded.

#### Scenario: OCR-mangled multi-word term links, not spawns novelty
- **WHEN** an OCR-mangled multi-word term above the similarity threshold is encountered
- **THEN** it links to the matching known concept rather than being surfaced as a novel term

#### Scenario: Below-threshold span is not force-linked
- **WHEN** a span's best fuzzy match is below the configured threshold
- **THEN** the fallback does not link it (the span proceeds to the disambiguation layer / novel)

### Requirement: Per-span classification emitted as the mention/miss artifact
The pipeline SHALL emit `data/corpus/{report#}/mentions.jsonl` — one record per recognized span with its offsets, surface form, `status` (`linked` or `novel`), target IRI, target kind, resolving layer, and score. `status:"novel"` records constitute the miss output consumed by chunk 8; the artifact MUST be regenerated deterministically per run.

#### Scenario: Linked and novel spans both recorded
- **WHEN** a run links some spans and leaves others unresolved/novel
- **THEN** `mentions.jsonl` contains a `linked` record (with target IRI and kind) for each linked span and a `novel` record for each unresolved span

#### Scenario: Deterministic regeneration
- **WHEN** the pipeline is re-run over the same inputs
- **THEN** it produces an identical `mentions.jsonl` (same records, same order)

### Requirement: Linking precision is gated at ≥ 0.90
A labelled-sample precision harness SHALL evaluate the pipeline against a committed gold fixture of ≥ 50 mentions from ORNL-TM-2316 and compute precision = correct links / total links emitted; the suite MUST fail when precision falls below 0.90. Recall MUST be computed and reported but MUST NOT gate the suite. The harness MUST run with a stubbed disambiguation model for determinism.

#### Scenario: Precision below the gate fails the suite
- **WHEN** the harness measures linking precision under 0.90 on the labelled sample
- **THEN** the test suite fails

#### Scenario: Recall reported, not gated
- **WHEN** the harness completes
- **THEN** it reports recall as an informational metric without failing on it
