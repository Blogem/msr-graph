# MSR Knowledge-Graph POC

A proof-of-concept knowledge graph for molten-salt reactor (MSR) chemistry: a
seed ontology, SKOS vocabulary, and A-Box instances load into a local GraphDB
store alongside a SQLite value store, accessed through the shared
`internal/graph` core-dataset client. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
for the full design.

## Prerequisites

- Docker + Docker Compose
- Go 1.26

## One-time setup: GraphDB license

Since GraphDB 11.0, even the Free edition requires a requested license file —
the license-less "built-in free license" was removed upstream. Before running
anything:

1. Request a free GraphDB license from the GraphDB product page:
   [https://www.ontotext.com/products/graphdb/](https://www.ontotext.com/products/graphdb/)
   (look for the GraphDB Free / "Request license" download call-to-action; see
   also the official
   [license setup instructions](https://graphdb.ontotext.com/documentation/11.3/set-up-your-license.html)).
   The license is emailed to you as a `.license` file.
2. Place the file at `graphdb.license` in the repo root.

**This file is gitignored and must never be committed** — it is issued
per-registrant. `make up` preflights its existence and fails fast with a
pointer back to this section if it is missing.

## Bootstrap order

Run these in order on a fresh clone:

```bash
make up         # preflight the license, bring up GraphDB + the server scaffold,
                # build the extraction and sandbox base images, wait for GraphDB
                # to be healthy, and ensure the `msr` repository exists
                # (inference disabled)

make load-seed  # initialize the SQLite measurement_value schema and load the
                # three seed graphs (graph-replace, idempotent):
                #   ontology/msr.ttl          -> urn:msr:ontology
                #   ontology/vocab.ttl        -> urn:msr:vocab
                #   ontology/example-flibe.ttl -> urn:msr:data
                # and ensure urn:msr:staging exists

make ingest     # one-shot Compose run of the extraction container: acquire ->
                # manifest -> normalize/segment -> documents. Acquires the
                # openmsr/msr-archive corpus (LFS-skip `--depth 1` clone into
                # data/corpus/msr-archive/, PDFs left as LFS pointers),
                # normalizes + segments the curated document set, and writes
                # msr:Document provenance nodes into urn:msr:data. Idempotent:
                # re-running skips the existing clone, and the INSERT DATA
                # writes are set-semantics no-ops. Requires the stack up and
                # seeded (needs GraphDB and the graphdb.license from setup).

make test       # GRAPHDB_REQUIRED=1 go test ./...
                # integration tests FAIL (not skip) if the stack isn't up
```

A bare `go test ./...` (without `GRAPHDB_REQUIRED=1` and without the stack
running) stays green by **skipping** the integration tests.

To tear the stack down (e.g. to reset for a clean re-bootstrap), use
`make down` (`docker compose down -v`).

## Corpus ingest

`make ingest` runs the `extraction` container's `acquire -> manifest ->
normalize/segment -> documents` pipeline (see
[`openspec/changes/ingest-archive-documents/design.md`](openspec/changes/ingest-archive-documents/design.md)
for the full design):

- **Two scopes** — the full openmsr/msr-archive corpus (637 OCR-sidecar
  documents) is acquired and staged on disk for later corpus-frequency
  statistics only. Normalization, segmentation, and `Document` node writing
  run on a curated subset of that corpus (~12 documents) alone.
- **`data/corpus/msr-archive/`** — the raw checkout: an LFS-skip
  (`GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1`) clone of openmsr/msr-archive,
  so PDFs land as LFS pointers while their paired OCR `.txt` sidecars
  (under `ocr/`) and the repo's own `README.md` manifest are pulled in full.
  Re-running `make ingest` skips the clone if this checkout already exists.
- **`data/corpus/{report#}/`** — per-curated-document processed output:
  `normalized.txt` (OCR-cleaned text) and `segments.jsonl` (one JSON object
  per sentence, with absolute character offsets into `normalized.txt`).
- `data/corpus/` is a gitignored subtree of `data/` (see below).

## `data/` bind-mount ownership

`./data` is a host bind mount shared into containers, which all run as a
fixed non-root UID **10001**.

- **macOS (Docker Desktop):** file ownership is handled transparently — no
  action needed.
- **Linux / CI:** ensure `./data` is writable by UID 10001. If you hit
  permission errors, either create the directory group-writable ahead of time
  or run `chown -R 10001 ./data`.

`data/` is gitignored except `data/nist/` (the vendored NIST thesaurus).
