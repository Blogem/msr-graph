# Proposal: ingest-archive-documents

## Why

The unstructured/evolution track (chunks 6–10) needs a clean, segmented corpus with linkable text and `Document` provenance nodes before any NER can run — none of which exists yet. This change acquires the openmsr/msr-archive corpus, prepares the curated core set for extraction, and finalizes the exact document list so the self-evolving-ontology demo has its target statements (solubility values, graphite-as-moderator prose) demonstrably present — the gate that unblocks chunks 8–10.

## What Changes

- **LFS-skip corpus acquisition**: `GIT_LFS_SKIP_SMUDGE=1` clone of openmsr/msr-archive into `data/corpus/` — all 637 OCR `.txt` sidecars land on disk (used later only for corpus-frequency statistics), while only the curated ~12 documents are processed further. PDFs stay as LFS pointers.
- **Curated-set finalization**: pick the 3–4 additional chemistry/corrosion documents per the `DATA_SCOPE.md` selection criteria, verify the curated set actually contains the evolution-demo targets (≥1 solubility statement with a numeric value + unit; graphite-as-moderator prose), record the final list and grep-level evidence in `DATA_SCOPE.md` — closing its open items 4 and 5.
- **Manifest parsing**: parse the msr-archive `README.md` markdown table into structured records (title / report number / date) for the curated set.
- **OCR normalization + segmentation**: an OCR-normalization pre-pass (line-break de-hyphenation, whitespace collapse, sub/superscript and common OCR-confusion handling) followed by sentence/paragraph segmentation, producing `data/corpus/{report#}/normalized.txt` + `segments.jsonl` (sentence text + char offsets) — the input format chunks 6–8 consume.
- **Document provenance nodes**: `msr:Document` nodes keyed by report number, with metadata, written to `urn:msr:data` via SPARQL UPDATE over the GraphDB HTTP endpoint (the language-neutral write path for Python extraction) with deterministic IRIs (idempotent re-runs).
- **Extraction project grows real code**: the `extraction/` Python scaffold from chunk 1 gains its first working pipeline stage (acquisition + normalization) and its pytest suite.

## Capabilities

### New Capabilities

- `corpus-acquisition`: LFS-skip clone of msr-archive into `data/corpus/` (637 sidecars for frequency stats, curated ~12 for processing), curated-set finalization against the `DATA_SCOPE.md` selection criteria, and verification that the evolution-demo targets are present in the curated set — recorded in `DATA_SCOPE.md` (closes open items 4–5; gates chunks 8–10).
- `document-manifest`: parse the msr-archive `README.md` markdown manifest into structured document records (title, report number, date).
- `corpus-normalization`: the OCR-normalization pre-pass and sentence/paragraph segmentation producing `normalized.txt` + `segments.jsonl` with char offsets — the pipeline input format for chunks 6–8.
- `document-graph`: write `Document` + provenance nodes keyed by report number into `urn:msr:data` via SPARQL UPDATE over HTTP, with deterministic IRIs and idempotent re-runs.

### Modified Capabilities

None — this change reads through the existing `core-dataset-access` client and reuses the `container-stack`/`extraction` scaffold without changing their requirements.

## Impact

- **New code**: real pipeline modules in `extraction/src/msr_extraction/` (acquisition, manifest parser, OCR normalizer, segmenter, Document-node writer) plus a `pytest` suite under `extraction/tests/`; the `extraction/` Dockerfile/pyproject gain the runtime dependencies these need.
- **Make targets**: an ingest entry point (one-shot Compose run of the extraction container) added additively to the root `Makefile`.
- **Data**: `data/corpus/` populated by the clone (gitignored per chunk 1); per-document `normalized.txt` + `segments.jsonl` artifacts written under `data/corpus/{report#}/`.
- **Docs**: `docs/DATA_SCOPE.md` updated with the finalized curated set and evolution-target evidence (closes open items 4–5).
- **Graph**: `msr:Document` individuals added to `urn:msr:data` (the seed A-Box already carries `msrd:ORNL-TM-2316`; re-asserting it is a no-op).
- **Depends on**: chunk 1 (`bootstrap-graph-infra`) — the stores, the GraphDB endpoint, and the `extraction/` scaffold. **Downstream**: produces the `segments.jsonl` input format and `Document` nodes consumed by chunks 6 (NER), 7 (relations), and 8 (novelty mining).
