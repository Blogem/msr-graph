# Tasks: ingest-archive-documents

## 1. Extraction project setup

- [x] 1.1 Grow the `extraction/` package from the chunk-1 scaffold: add module files for acquisition, manifest, normalizer, segmenter, document-writer, and an ingest CLI umbrella under `extraction/src/msr_extraction/`
- [x] 1.2 Add runtime dependencies to `pyproject.toml` (`pysbd` for segmentation; a minimal HTTP client such as `httpx`/`requests` for SPARQL UPDATE); pin versions
- [x] 1.3 Add a config module: read `GRAPHDB_URL`, corpus paths, and the committed curated-set list from environment/defaults (injectable for tests)
- [x] 1.4 Extend the `extraction/` Dockerfile to install `git` + `git-lfs` (acquisition runs in-container); confirm the image still builds

## 2. Corpus acquisition (`corpus-acquisition`)

- [x] 2.1 Implement `acquire`: `GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 <msr-archive>` into `data/corpus/msr-archive/`; idempotent (skip if the checkout already exists), PDFs left as LFS pointers, all 637 OCR sidecars pulled
- [x] 2.2 Define the committed curated-set list (the 7 DATA_SCOPE anchors) and a helper resolving report# → OCR sidecar path via the manifest

## 3. Manifest parser (`document-manifest`)

- [x] 3.1 Implement `manifest`: parse the checked-out `README.md` markdown table into `{report_number, title, date, ocr_path}` records, offline and pure; skip header/separator/malformed rows with a logged warning

## 4. Curated-set finalization & evolution-target gate (`corpus-acquisition`)

- [x] 4.1 Select the 3–4 additional chemistry/corrosion documents from the manifest (INOR-8 / Hastelloy-N cluster) per the DATA_SCOPE selection criteria; add them to the committed curated-set list
- [x] 4.2 Implement evolution-target detection: scan the curated OCR for a solubility statement with a numeric value + unit and for graphite-as-moderator prose
- [x] 4.3 Verify the targets are present; if absent, swap additions until they are (gate must pass, not hope)
- [x] 4.4 Record the finalized ~12-document curated set and the grep-level evidence (quoted source sentences) in `docs/DATA_SCOPE.md`, marking open items 4 and 5 resolved

## 5. OCR normalization (`corpus-normalization`)

- [x] 5.1 Implement the normalizer as an ordered, deterministic `str -> str`: line-break de-hyphenation (join lowercase–lowercase, keep hyphen for capitalized/numeric neighbors)
- [x] 5.2 Add whitespace normalization + the bounded intra-word OCR-split rejoin (`THERMAL-STRE SS` → `THERMAL-STRESS`) driven by a small fixture table
- [x] 5.3 Add sub/superscript-to-ASCII mapping (`BeF₂` → `BeF2`, `cm⁻³` → `cm-3`) and the conservative OCR-confusion substitution table; ensure equations pass through unchanged

## 6. Segmentation (`corpus-normalization`)

- [x] 6.1 Implement `normalize`: run the normalizer, write `data/corpus/{report#}/normalized.txt`, segment with `pysbd` per paragraph keeping global offsets
- [x] 6.2 Emit `data/corpus/{report#}/segments.jsonl` — one object per sentence `{report, index, text, char_start, char_end}` with absolute offsets into `normalized.txt`

## 7. Document graph writer (`document-graph`)

- [x] 7.1 Implement a Python SPARQL-UPDATE helper posting `INSERT DATA { GRAPH <urn:msr:data> { … } }` to `GRAPHDB_URL` (reusable by chunks 6–8)
- [x] 7.2 Implement `documents`: emit one `msrd:{report#} a msr:Document` node per curated doc with `rdfs:label` (title), `dcterms:identifier` (report#), `dcterms:date` (date); deterministic IRIs, no blank nodes, additive `INSERT DATA`

## 8. Ingest entry point

- [x] 8.1 Implement the `ingest` CLI umbrella running acquire → manifest → normalize/segment → documents in order
- [x] 8.2 Add the `make ingest` target: one-shot Compose run of the `extraction` container invoking `ingest` (additive to the root `Makefile`)

## 9. Tests

- [x] 9.1 Create `extraction/tests/` + `extraction/tests/fixtures/` and wire pytest into the project
- [x] 9.2 Normalizer tests (table-driven): line-break de-hyphenation (join vs. keep-hyphen), the `THERMAL-STRE SS` intra-word-split rejoin, subscript mapping (`BeF₂` → `BeF2`), superscript in-place mapping covering **both** an exponent (`cm⁻³` → `cm-3`) and an isotope mass number (`²³⁵U` → `235U`), OCR-confusion substitutions, and an equation-survives-intact case (`η = 0.084·exp(4340/T)`)
- [x] 9.3 Manifest-parser tests against a committed excerpt of real README rows → expected records; header/separator/malformed rows skipped
- [x] 9.4 Segmenter tests: offset round-trip (`normalized_text[char_start:char_end] == text` for every segment); decimals/abbreviations not over-split
- [x] 9.5 Document-emission tests: a fixed manifest record → the exact expected `INSERT DATA` triples against a fake SPARQL client; deterministic IRI, no blank nodes
- [x] 9.6 Evolution-target gate test: committed fixture excerpts of the actual target sentences (solubility + value + unit; graphite-as-moderator) → detection patterns match, pinning the gate hermetically
- [x] 9.7 Guarded corpus integration (opt-in env flag, mirroring chunk 1's `GRAPHDB_REQUIRED`): after a real `make ingest`, 12 `Document` nodes present, curated OCR contains the target patterns, and a second run leaves `urn:msr:data` triple counts unchanged

## 10. Documentation

- [x] 10.1 Document the ingest step in the README (`make ingest` in the bootstrap order, the two-scope corpus model, and the `data/corpus/` layout: `msr-archive/` checkout vs. `{report#}/` outputs)
