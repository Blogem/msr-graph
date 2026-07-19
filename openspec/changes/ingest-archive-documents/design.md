# Design: ingest-archive-documents

## Context

Chunk 1 (`bootstrap-graph-infra`) landed the running stores, the seed A-Box (which already
carries `msrd:ORNL-TM-2316` as an `msr:Document`), and the `extraction/` Python scaffold — a
pyproject with an empty package proving the image builds. Nothing acquires or prepares text yet.

The unstructured/evolution track (chunks 6–10) is built on a curated document corpus with:

- linkable, OCR-cleaned text (chunk 6's spaCy pipeline needs sentences with stable char offsets),
- `Document` provenance nodes keyed by report number (measurements `citedIn` them; chunk 7 attaches
  values to them), and
- a curated set that **demonstrably contains** the self-evolving-ontology demo's targets —
  solubility statements with numeric values + units, and graphite-as-moderator prose. Corpus-wide
  salience counts (chunk 8) don't guarantee those sentences are in the processed ~12; this chunk is
  the gate that pins their presence and unblocks chunks 8–10.

Binding contracts (from `docs/ARCHITECTURE.md` and `docs/DATA_SCOPE.md`):

- **Source & acquisition** — openmsr/msr-archive: 637 scanned PDFs each with a paired OCR `.txt`
  sidecar (`ocr/<id>.txt`, ~97 MB). `GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1` leaves PDFs as LFS
  pointers and pulls the OCR text. The repo `README.md` is the only manifest — a markdown table
  `| [Title](pdf) | Report-Number | Date | [txt](ocr/<id>.txt) |`. No CSV/JSON catalog.
- **Two scopes** — the full 637-doc OCR set stays on disk for corpus-frequency statistics only
  (chunk 8); NER/relation extraction (chunks 6–7) runs on the curated ~12 alone.
- **Output format (the chunk 6–8 input contract)** — `data/corpus/{report#}/normalized.txt` +
  `segments.jsonl` (one JSON object per sentence: text + char offsets).
- **Write path** — Python extraction writes the graph **directly via SPARQL UPDATE over the GraphDB
  HTTP endpoint** (language-neutral; the Go `internal/graph` client is the read-side FROM-injection
  enforcement, not a shared write library across languages). Writers name an explicit `GRAPH` target.
- **Deterministic IRIs, no blank nodes** — pipeline-written data mints IRIs deterministically so
  re-runs are RDF-set-semantics no-ops. `Document` IRI = `msrd:{report#}`.
- **Run model** — one-shot extraction runs behind a `make` target, in the `extraction` container
  (network-enabled, unlike the sandboxes); `data/` is a host bind mount, gitignored except vendored
  inputs.

## Goals / Non-Goals

**Goals:**

- A `make` target acquires the corpus (LFS-skip clone) idempotently: all 637 OCR sidecars on disk,
  PDFs left as pointers.
- Finalize the curated set (7 confirmed anchors + 3–4 selected chemistry/corrosion additions), verify
  the evolution-demo targets are present in it, and record the final list + grep-level evidence in
  `docs/DATA_SCOPE.md` (closing open items 4–5).
- Parse the msr-archive `README.md` manifest into structured records (title, report#, date).
- OCR-normalize + segment each curated document into `normalized.txt` + `segments.jsonl` with char
  offsets consistent within the normalized artifact.
- Write the 12 `Document` provenance nodes (keyed by report#) into `urn:msr:data`, idempotently.
- pytest suite covering the normalizer, manifest parser, segmenter offsets, Document emission, and the
  evolution-target gate.

**Non-Goals:**

- No NER, entity linking, or the salt/formula normalizer (chunk 6) — this chunk stops at clean,
  segmented text + `Document` nodes.
- No relation/measurement extraction or SQLite writes (chunk 7); no novelty mining or frequency
  scoring (chunk 8) — the full 637 sidecars are only _staged on disk_ here, not scanned.
- No re-OCR of PDFs — OCR sidecars are consumed as-is (the source is "good-but-noisy" by design).
- No IAEA/PUB2027 safety corpus (stretch chunk 11).
- No changes to the seed ontology/vocabulary; `msr:Document`, `dcterms:`, and `prov:` already exist
  in the seed T-Box.

## Decisions

### D1 — Acquisition: LFS-skip clone into a raw checkout dir, processed artifacts alongside

`GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 <msr-archive> data/corpus/msr-archive/` places the raw
checkout (`ocr/*.txt` + `README.md`) under `data/corpus/msr-archive/`; the pipeline writes processed
per-document artifacts to `data/corpus/{report#}/`. Separating the raw checkout from processed output
avoids a layout collision (the clone brings a whole repo tree; our outputs are per-report dirs) while
still satisfying the contract that the sidecars and the `{report#}/` outputs both live under
`data/corpus/`. Acquisition is idempotent: if `data/corpus/msr-archive/.git` already exists, skip the
clone (a POC does not chase upstream updates).

- The clone runs **inside the `extraction` container**, whose image gains `git` + `git-lfs`. The
  extraction container is not a sandbox — it has network and GraphDB access (per the write-path
  contract), so containerizing acquisition keeps the whole ingest behind one reproducible `make`
  target and writes into the bind-mounted `data/corpus/` as the fixed non-root UID chunk 1 pinned.
- _Alternative — host-side `git clone` in the Makefile:_ rejected to keep the run model containerized
  and reproducible across dev/CI; the only cost is `git`/`git-lfs` in the extraction image.

### D2 — Curated set as committed config; finalization is a recorded, test-enforced gate

The curated set is a committed list of report numbers in the extraction package (the 7 DATA_SCOPE
anchors + the 3–4 additions selected at implementation time from the INOR-8/Hastelloy-N chemistry
/corrosion cluster in the manifest). Finalization has two recorded outputs:

1. The final ~12-document list written into `docs/DATA_SCOPE.md` (open item 4).
2. Grep-level evidence that the curated set contains the demo targets — ≥1 solubility statement with a
   numeric value + unit, and graphite-as-moderator prose — with the source sentences quoted in
   `docs/DATA_SCOPE.md` (open item 5).

The gate is enforced by a test (D8) so it cannot silently regress: chunks 8–10 depend on these
sentences existing in the processed set, not merely corpus-wide.

- _Why a committed list, not "top-N by frequency"?_ Selection is judgment (demo-target coverage),
  done once; a frozen list makes the processed scope deterministic and reviewable.

### D3 — Manifest parser: pure-Python markdown-table parse, no network

Parse the checked-out `README.md` markdown table into records `{report_number, title, date,
ocr_path}` using a line-oriented table parser (split rows on `|`, extract link text/targets with a
small regex). No markdown library and no network — the README is already on disk from D1. The parser
is the single source of the OCR sidecar path per report# and of `Document` metadata (title, date).
Rows that don't match the expected 4-column shape are skipped with a logged warning (the README has
header/separator rows and possibly malformed entries).

- _Alternative — a full markdown/AST library:_ unnecessary for one known table shape; a targeted
  parser is smaller, dependency-free, and directly testable against real README rows.

### D4 — OCR normalization: conservative, deterministic, equation-preserving

The normalizer is a pure function `str -> str` applying an ordered, fixture-pinned set of transforms,
biased toward precision (under-correct rather than corrupt real data):

1. **Line-break de-hyphenation** — join `word-\nword` → `wordword` when both sides are lowercase
   alphabetic (a soft-hyphenated word break); keep the hyphen for capitalized/numeric neighbors
   (`LiF-\nBeF2` stays hyphenated — it is a real compound hyphen).
2. **Whitespace normalization** — collapse runs of spaces/newlines to single separators for `.txt`
   output while segmentation keeps paragraph boundaries (D5); a bounded heuristic rejoins obvious
   intra-word OCR splits in all-caps runs (`THERMAL-STRE SS` → `THERMAL-STRESS`) from a small
   fixture-driven table, not a general "remove spaces" rule.
3. **Sub/superscript normalization** — map Unicode subscript digits to ASCII inline
   (`BeF₂` → `BeF2`) so chunk 6's formula normalizer sees plain formulas; map superscript
   digits/minus to ASCII **in place** (`cm⁻³` → `cm-3`), *not* caret-wrapped (`cm^-3`). The in-place
   form is chosen deliberately because superscripts here serve two roles — exponents (`cm⁻³`) and
   isotope mass numbers (`²³⁵U` → `235U`, `⁶Li` → `6Li`) — and a caret rule would corrupt the isotope
   case into `^235U`. Exponent-vs-not is resolved downstream by chunk 7's unit parser (unit context +
   its QUDT lookup table), so the glyph need not encode "to the power of". Pinned by normalizer
   fixtures covering both an exponent and an isotope case.
4. **Common OCR confusions** — a small, documented substitution table (e.g. stray control chars,
   ligatures) applied conservatively.

Equations such as `η = 0.084·exp(4340/T)` must survive intact — no numeric or operator rewriting.

- _Why not aggressive correction (spellcheck, dictionary rejoin)?_ Over-fuzzy cleanup corrupts numeric
  data and floods chunk 8's novelty queue with artifacts. The architecture pins "high-precision
  linking with bounded fuzziness"; this pre-pass removes cheap fuzz only, leaving real fuzziness to
  chunk 6's layered matcher.
- This normalizer is document-text cleanup and is **distinct** from chunk 6's salt-formula/mention
  normalizer (which unifies `BeF2-LiF` ≡ `LiF-BeF2` against the canonical form); they are not the
  duplicated-on-purpose pair — that pair is chunk 2 (Go) ↔ chunk 6 (Python).

### D5 — Segmentation: pure-Python sentence splitter; offsets into the normalized text

Segment `normalized.txt` into sentences with `pysbd` (Python Sentence Boundary Disambiguation, a
pure-Python, model-free splitter that handles decimals, abbreviations, and scientific text) and emit
`segments.jsonl` — one object per sentence: `{"report": "...", "index": n, "text": "...",
"char_start": s, "char_end": e}`. Offsets are **absolute character offsets into `normalized.txt`**,
so chunk 6 can mint deterministic mention IRIs (`mention-{report#}-{start}-{end}`) directly against
the same artifact it reads. Paragraph boundaries are preserved by segmenting per paragraph and keeping
offsets global.

- _Why `pysbd`, not spaCy's sentencizer?_ spaCy is chunk 6's dependency (with its model); front-loading
  it here for plain sentence splitting adds a heavy dependency + model download to a chunk that does no
  NER. `pysbd` is small, deterministic, and scientific-text-aware.
- _Offset semantics:_ offsets are into the _normalized_ text only — the POC's provenance is
  document-granular (`citedIn` a `Document`), so no raw-OCR offset map is kept. Recovering raw offsets
  would need a normalization offset map — explicitly out of scope.

### D6 — Document nodes via SPARQL UPDATE over HTTP, deterministic IRIs, idempotent

A small Python graph-write helper (reused by chunks 6–8) sends `INSERT DATA { GRAPH <urn:msr:data>
{ … } }` to the GraphDB SPARQL UPDATE endpoint (`GRAPHDB_URL` from config). Per curated document it
emits, keyed by report number:

```
msrd:{report#} a msr:Document ;
    rdfs:label "{title}" ;
    dcterms:identifier "{report#}" ;
    dcterms:date "{date}" .
```

`msr:Document`, `dcterms:`, and `prov:` are already in the seed T-Box. IRIs are deterministic
(`msrd:{report#}`, report numbers are already IRI-safe tokens) and there are no blank nodes, so
`INSERT DATA` of the same triples is a set-semantics no-op — re-running the ingest yields identical
triple counts, and re-asserting the seed's `msrd:ORNL-TM-2316` changes nothing.

- _Why `INSERT DATA` per document, not a `PUT` of the whole graph?_ `urn:msr:data` also holds the seed
  A-Box and (later) chunk-2 catalog triples and chunk-6/7 mention/measurement triples; a graph-replace
  `PUT` would clobber them. Additive `INSERT DATA` with deterministic IRIs is the correct idempotency
  model for a shared graph.
- _Why not go through the Go loader?_ The write is Python-side data with no Go counterpart; the GraphDB
  HTTP endpoint is language-neutral (per the architecture), so a thin Python UPDATE client is correct
  and becomes the shared write path for chunks 6–8.

### D7 — Package layout and CLI

The `extraction` package grows real modules and a subcommand CLI (extending the chunk-1 `--help`
scaffold): `acquire` (D1), `manifest` (D3), `normalize` (D4+D5, writes the per-report artifacts),
`documents` (D6), and an `ingest` umbrella that runs them in order. `make ingest` is a one-shot Compose
run of the extraction container invoking `ingest`. Config (GraphDB URL, corpus paths, curated list) is
read from environment/defaults, injected for tests.

### D8 — Test strategy: hermetic pytest units + a guarded corpus integration

pytest suite in `extraction/tests/`, committed fixtures in `extraction/tests/fixtures/` (the raw
`data/corpus/` tree is gitignored):

- **Normalizer** (table-driven): line-break de-hyphenation (join vs. keep-hyphen cases), the
  `THERMAL-STRE SS` intra-word-split rejoin, sub/superscript mapping, OCR-confusion substitutions, and
  an equation-survives-intact case.
- **Manifest parser**: real README rows (a committed excerpt) → expected records; malformed/header
  rows skipped.
- **Segmenter**: offsets round-trip — for every emitted segment, `normalized_text[char_start:char_end]
== text`; decimal/abbreviation sentences don't over-split.
- **Document emission**: a fixed manifest record → the exact expected `INSERT DATA` triples (against a
  fake SPARQL client); idempotent shape (no blank nodes, deterministic IRI).
- **Evolution-target gate**: committed fixture excerpts of the actual target sentences (solubility +
  value + unit; graphite-as-moderator) → the detection patterns match, pinning the gate hermetically
  and version-controlling the evidence quoted in `DATA_SCOPE.md`.
- **Guarded corpus integration** (opt-in via an env flag, mirroring chunk 1's `GRAPHDB_REQUIRED`):
  after a real `make ingest`, assert 12 `Document` nodes are present via the graph, the curated OCR
  actually contains the target patterns, and a second ingest run leaves triple counts unchanged.

## Risks / Trade-offs

- **Evolution targets may not exist in the initially-chosen additions** — the demo depends on them. →
  Mitigation: finalization (D2) is verify-then-record; if the first picks lack a clean
  solubility-with-unit or graphite-moderator sentence, swap additions until the gate test passes. The
  gate is a hard test, not a hope.
- **Over-aggressive OCR normalization corrupts numeric/equation data** feeding chunks 7–8. →
  Mitigation: conservative, fixture-pinned rules (D4); an explicit equation-survival test; no numeric
  rewriting.
- **Offsets defined against normalized (not raw) text** — provenance can't point at raw-OCR spans. →
  Accepted: POC provenance is document-granular; a raw-offset map is out of scope and cleanly addable
  later.
- **Manifest table shape drift** (upstream README format changes) breaks parsing. → Mitigation: parser
  skips non-conforming rows with warnings and is pinned by a real-row fixture; the depth-1 clone
  freezes a known state for the POC.
- **`git`/`git-lfs` added to the extraction image** enlarges it and needs network at ingest time. →
  Accepted: the extraction container is already network-enabled for GraphDB writes; acquisition is a
  one-shot, not a runtime path.
- **`INSERT DATA` into the shared `urn:msr:data` graph** must not clobber seed/catalog triples. →
  Mitigation: additive `INSERT DATA` with deterministic IRIs and no blank nodes (D6); idempotency
  pinned by the integration test.

## Migration Plan

Additive, greenfield for this track. Order: `make up` + `make load-seed` (chunk 1) must be green, then
`make ingest` runs acquire → manifest → normalize/segment → documents. Re-running `make ingest` is
idempotent (skips the existing clone; `INSERT DATA` no-ops). Rollback = delete `data/corpus/` contents
and the added `msr:Document` triples (or `docker compose down -v` + re-bootstrap); nothing outside
`data/corpus/`, the graph's `urn:msr:data`, and the finalized `DATA_SCOPE.md` edits is touched. Root
`Makefile` gains the `ingest` target additively per the parallel-execution contract.

## Open Questions

_All resolved (2026-07-19)._

- **Superscript rendering** — **Resolved: in-place ASCII mapping (`cm⁻³` → `cm-3`), not caret
  (`cm^-3`).** The in-place form also renders isotope mass numbers correctly (`²³⁵U` → `235U`) instead
  of corrupting them to `^235U`; exponent recognition is chunk 7's job via unit context + its QUDT
  lookup, so the glyph need not encode "power of". Pinned by normalizer fixtures (an exponent case and
  an isotope case). See D4.
- **The 3–4 additional documents** — **Resolved: selected at implementation** from the manifest's
  chemistry/corrosion cluster, constrained by the D2 gate and recorded in `docs/DATA_SCOPE.md`
  (tasks 4.1–4.4).
- **`pysbd` vs. a hand-rolled splitter** — **Resolved: use `pysbd`,** falling back to a small
  rule-based splitter only if it mis-splits on OCR artifacts; the segmenter interface (offsets into
  normalized text) is unchanged either way. See D5.
