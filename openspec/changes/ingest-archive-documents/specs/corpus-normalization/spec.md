## ADDED Requirements

### Requirement: OCR normalization pre-pass
The system SHALL apply a deterministic, precision-biased OCR-normalization pre-pass to each curated document's OCR text, covering: line-break de-hyphenation, whitespace normalization including bounded intra-word OCR-split rejoining, sub/superscript normalization to ASCII, and a conservative set of common OCR-confusion substitutions. Normalization MUST NOT rewrite numeric values or equation operators — equations MUST survive intact.

#### Scenario: Line-break hyphenation is de-hyphenated
- **WHEN** the OCR text contains a soft-hyphenated word split across a line break (lowercase on both sides, e.g. `prop-\nerties`)
- **THEN** the normalizer joins it into a single word (`properties`)

#### Scenario: Real compound hyphens are preserved
- **WHEN** the OCR text contains a hyphen between a formula/capitalized/numeric neighbor (e.g. `LiF-\nBeF2`)
- **THEN** the normalizer keeps the hyphen rather than merging the tokens

#### Scenario: Intra-word OCR split is rejoined
- **WHEN** the OCR text contains an intra-word split such as `THERMAL-STRE SS`
- **THEN** the normalizer rejoins it to `THERMAL-STRESS`

#### Scenario: Sub/superscripts normalized to ASCII in place
- **WHEN** the OCR text contains Unicode sub/superscripts as exponents or isotope mass numbers (e.g. `BeF₂`, `cm⁻³`, `²³⁵U`)
- **THEN** they are normalized to a deterministic in-place ASCII form (`BeF2`, `cm-3`, `235U`) — never caret-wrapped, so isotope mass numbers are not corrupted

#### Scenario: Equations survive normalization
- **WHEN** the OCR text contains an equation such as `η = 0.084·exp(4340/T)`
- **THEN** the equation's numeric values and operators are unchanged after normalization

### Requirement: Sentence segmentation with char offsets
The system SHALL segment each document's normalized text into sentences and write, per curated document, `data/corpus/{report#}/normalized.txt` and `data/corpus/{report#}/segments.jsonl`. Each JSONL record MUST contain the sentence text and its absolute character offsets into `normalized.txt`. Offsets MUST satisfy `normalized_text[char_start:char_end] == text` for every segment.

#### Scenario: Segments carry round-tripping offsets
- **WHEN** a curated document is segmented
- **THEN** for every segment record, slicing `normalized.txt` by its `char_start`/`char_end` yields exactly that segment's text

#### Scenario: Pipeline input artifacts produced for ORNL-TM-2316
- **WHEN** the normalization/segmentation step runs on ORNL-TM-2316
- **THEN** `data/corpus/ORNL-TM-2316/normalized.txt` and `data/corpus/ORNL-TM-2316/segments.jsonl` exist and are consumable as the chunk 6–8 input format

#### Scenario: Scientific text is not over-split
- **WHEN** a sentence contains decimals or abbreviations (e.g. `0.084`, `approx.`)
- **THEN** the segmenter does not split the sentence at those internal periods
