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

make load-nist  # ingest the 4 vendored NIST SRD 27 fluoride CSVs: coefficient
                # rows -> SQLite measurement_value (source='nist'); MoltenSalt /
                # Constituent / PropertyMeasurement catalog triples -> urn:msr:data
                # via additive SPARQL INSERT (idempotent; preserves the seed A-Box).
                # Chains after load-seed — must run after seed, since seed's
                # graph-replace PUT would otherwise drop the NIST triples.

make ingest     # one-shot Compose run of the extraction container: acquire ->
                # manifest -> normalize/segment -> documents. Acquires the
                # openmsr/msr-archive corpus (LFS-skip `--depth 1` clone into
                # data/corpus/msr-archive/, PDFs left as LFS pointers),
                # normalizes + segments the curated document set, and writes
                # msr:Document provenance nodes into urn:msr:data. Idempotent:
                # re-running skips the existing clone, and the INSERT DATA
                # writes are set-semantics no-ops. Requires the stack up and
                # seeded (needs GraphDB and the graphdb.license from setup).

make link       # one-shot Compose run of the extraction container: seed the
                # spaCy matcher from the graph -> link segments -> Flash
                # disambiguation for unresolved spans -> write msr:Mention
                # triples + data/corpus/{report#}/mentions.jsonl (see
                # openspec/changes/ner-entity-linking/design.md). Requires
                # `make load-seed` to have run first (the mention T-Box lives
                # in ontology/msr.ttl) as well as `make ingest` (segments.jsonl).

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

## Entity linking (`make link`)

`make link` runs the `extraction` container's NER linking pipeline (see
[`openspec/changes/ner-entity-linking/design.md`](openspec/changes/ner-entity-linking/design.md)
for the full design): it rebuilds a spaCy matcher from the graph's current
vocab/ontology/salt catalog, links spans in each curated document's
`segments.jsonl`, falls back to a DeepSeek V4 Flash disambiguation layer for
spans the lexical layers can't settle, and writes the results both as
`msr:Mention` triples in `urn:msr:data` and as a JSONL artifact:

- **`data/corpus/{report#}/mentions.jsonl`** — one JSON object per recognized
  span, with fields:
  - `report` — the report number the mention belongs to.
  - `seg_index` — index into that report's `segments.jsonl`.
  - `char_start` / `char_end` — absolute character offsets into
    `normalized.txt`, matching the segment's own offsets.
  - `surface_form` — the matched text.
  - `status` — `"linked"` (resolved to a known entity) or `"novel"`
    (recorded for chunk 8's novelty mining, never written to the graph).
  - `target_iri` / `target_kind` — the resolved concept/class/individual IRI
    and its kind, when `status` is `"linked"`.
  - `layer` — which matching layer resolved the span (expanded exact,
    formula normalizer, bounded fuzzy match, or Flash disambiguation).
  - `score` — the resolving layer's confidence/match score.

  The file is regenerated wholesale on each `make link` run, so it is
  idempotent like the graph writes.

## `data/` bind-mount ownership

`./data` is a host bind mount shared into containers, which all run as a
fixed non-root UID **10001**.

- **macOS (Docker Desktop):** file ownership is handled transparently — no
  action needed.
- **Linux / CI:** ensure `./data` is writable by UID 10001. If you hit
  permission errors, either create the directory group-writable ahead of time
  or run `chown -R 10001 ./data`.

`data/` is gitignored except `data/nist/` (the vendored NIST thesaurus).

## Sandboxed Python execution (`internal/sandbox`)

The grounded-analysis agent runs every computation as model-authored Python
rather than doing arithmetic itself or pushing it into SQL, so the script and
its output appear verbatim in the chat trace. That code is untrusted, so it
runs in a warm pool of throwaway, hardened Docker containers managed by
`internal/sandbox`.

The pool's public surface is `Run(ctx, script) (stdout, stderr []byte,
exitCode int, err error)`: the script is fed to `python -` on stdin, and
stdout/stderr/exit code come back verbatim and unparsed. A non-zero exit
code is a normal result (surfaced in the trace), not an error; `err` is
reserved for infrastructure failures, including a distinguishable timeout
error when a script exceeds its wall-clock limit. A container serves
exactly **one** script run, is then always force-removed, and is replaced
in the background — no state ever survives from one run to the next.

Every sandbox is hardened: no network (`--network none`), a read-only root
filesystem with a `noexec` tmpfs `/tmp` for scratch space, non-root user
(UID 10001), dropped Linux capabilities and no-new-privileges, CPU/memory
(no swap)/pids limits, and a wall-clock timeout enforced by force-removing
the container. The shared SQLite data directory is bind-mounted read-only
at `/data` (the DB lives at `/data/msr.db`) — scripts can query it but never
write to it.

Configuration is two environment variables on the `server` service, already
wired in `docker-compose.yml`:

- `MSR_DATA_HOST_DIR` — the **host** path of the data directory
  (`${PWD}/data`), because sandboxes are Docker siblings created over the
  mounted `/var/run/docker.sock`: the daemon resolves bind-mount sources
  against the host filesystem, not the server's own container namespace, so
  the host path must be supplied explicitly rather than derived from the
  server's internal `/data`.
- `MSR_SANDBOX_IMAGE` — the sandbox image reference (defaults to the tag
  `make up` builds).

Because a crash, kill, or restart can skip graceful shutdown, every sandbox
carries a distinctive label; pool startup force-removes every pre-existing
labelled container before warming a fresh pool, so a restarted server always
begins clean regardless of how its predecessor died. As a backstop, each
sandbox idles on a bounded TTL well above the run timeout and is
auto-removed by Docker if it's ever abandoned and no server returns to sweep
it.

**Known limitation:** the server holds `/var/run/docker.sock`, which makes
it host-root-equivalent — sandbox hardening protects against the untrusted
*script*, not against a compromised server process. This is an accepted,
documented ceiling for a single-host proof of concept.
