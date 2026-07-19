# corpus-acquisition Specification

## Purpose

Define acquisition of the openmsr/msr-archive corpus: an idempotent LFS-skip clone that keeps PDFs as pointers while pulling OCR sidecars, a two-scope model separating the full 637-document statistics set from the curated processing set, and finalization of the curated set with verified evolution-demo targets.

## Requirements

### Requirement: Corpus acquired via LFS-skip clone
The system SHALL acquire the openmsr/msr-archive corpus with `GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1` into `data/corpus/msr-archive/`, leaving PDFs as Git-LFS pointers and pulling the OCR `.txt` sidecars. Acquisition MUST be idempotent: if the checkout already exists, the clone is skipped and no error is raised.

#### Scenario: All OCR sidecars present after acquisition
- **WHEN** the acquisition step runs against a clean `data/corpus/`
- **THEN** all 637 OCR `.txt` sidecars from the archive are on disk under the checkout, and the PDFs remain LFS pointers (not smudged binaries)

#### Scenario: Re-running acquisition is a no-op
- **WHEN** the acquisition step runs a second time with the checkout already present
- **THEN** it skips the clone without error and leaves the existing files unchanged

### Requirement: Two-scope corpus model
The system SHALL keep the full 637-document OCR set on disk for later corpus-frequency statistics (chunk 8) while designating only the curated set for further processing (normalization, segmentation, `Document` nodes). The curated set of report numbers SHALL be a committed, reviewable list in the extraction package.

#### Scenario: Only curated documents are processed
- **WHEN** the ingest pipeline runs
- **THEN** normalization, segmentation, and `Document`-node writing operate on exactly the curated set, and the non-curated sidecars are left on disk untouched

### Requirement: Curated set finalized and evolution targets verified
The system SHALL finalize the curated document set — the confirmed DATA_SCOPE anchors plus 3–4 chemistry/corrosion additions selected per the DATA_SCOPE selection criteria — and SHALL verify that the curated set contains the evolution-demo targets: at least one solubility statement carrying a numeric value + unit, and graphite-as-moderator prose. The finalized list and grep-level evidence (quoted source sentences) MUST be recorded in `docs/DATA_SCOPE.md`, closing its open items 4 and 5.

#### Scenario: Solubility target present in the curated set
- **WHEN** the finalized curated set's OCR text is checked for the evolution targets
- **THEN** at least one solubility statement with a numeric value and a physical unit is found, and the evidence sentence is recorded in `docs/DATA_SCOPE.md`

#### Scenario: Graphite-as-moderator target present in the curated set
- **WHEN** the finalized curated set's OCR text is checked for the evolution targets
- **THEN** graphite-as-moderator prose is found, and the evidence sentence is recorded in `docs/DATA_SCOPE.md`

#### Scenario: DATA_SCOPE open items closed
- **WHEN** finalization completes
- **THEN** `docs/DATA_SCOPE.md` lists the final ~12-document curated set and marks open items 4 and 5 as resolved with recorded evidence
