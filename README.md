# MSR Knowledge-Graph POC

A proof-of-concept knowledge graph for molten-salt reactor (MSR) chemistry: a
seed ontology and SKOS vocabulary load into a local GraphDB store, and all
instance data (salts, measurements, documents, mentions) is written only by
the real-data pipeline — the NIST loader and the extraction pipeline — never
by a hand-curated seed. GraphDB sits alongside a SQLite value store, both
accessed through the shared `internal/graph` core-dataset client. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design.

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
                # two seed graphs (graph-replace, idempotent):
                #   ontology/msr.ttl          -> urn:msr:ontology
                #   ontology/vocab.ttl        -> urn:msr:vocab
                # and ensure urn:msr:staging exists. There is no seed A-Box —
                # urn:msr:data starts empty and is populated exclusively by
                # `make load-nist` below and the extraction pipeline
                # (`make ingest` + `make link`).

make load-nist  # ingest the 4 vendored NIST SRD 27 fluoride CSVs: coefficient
                # rows -> SQLite measurement_value (source='nist'); MoltenSalt /
                # Constituent / PropertyMeasurement catalog triples -> urn:msr:data
                # via additive SPARQL INSERT (idempotent). Chains after
                # load-seed — must run after seed so the ontology/vocab graphs
                # exist before data lands (the mention T-Box the linker needs
                # lives in ontology/msr.ttl).

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

### Building the demo graph

There is no seed A-Box, so the graph has no salts, measurements, documents,
or mentions until the real pipeline has run. To reproduce the density demo
end to end on a fresh stack:

```bash
make up && make load-nist && make ingest && make link && make demo-density
```

`make link`'s Flash disambiguation layer may need `DEEPSEEK_API_KEY` set in
the environment (the deterministic composed-salt match itself needs no LLM).
`make demo-density` depends on that full build having populated
`urn:msr:data` — it is not a standalone fixture.

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

## Chat API (`POST /api/chat`)

The grounded-analysis agent (`internal/agent`) is reachable over one HTTP
endpoint, `POST /api/chat`. The endpoint is **stateless**: the request body
carries the full conversation so far, OpenAI-style, and the server holds no
server-side session — every request is answered purely from its own body
plus the read-only stores (GraphDB + SQLite). This request/response shape
is the interface a future browser frontend consumes; until then, exercise
it with the `cmd/chatcli` playground (below).

```json
{
  "messages": [
    { "role": "user", "content": "What is the density of FLiBe at 900 K?" }
  ]
}
```

`role` is `"user"` or `"assistant"`; both `role` and `content` are required
on every message. A malformed body (missing/empty `messages`, or a message
missing `role`/`content`) gets a client error response and no agent turn is
started.

The response is a **Server-Sent Events** stream, not a single JSON payload —
consume it with `fetch` streaming rather than the native `EventSource` API,
since `EventSource` cannot send a POST body. Nothing about a turn is
persisted: the trace is ephemeral and exists only for the lifetime of the
stream, so an interrupted connection needs no server-side recovery — the
client simply re-sends the conversation.

### SSE trace-event contract

Each SSE frame carries one typed event (`event: <type>` / `data: <json>`).
Every trace-event type the agent loop can emit is represented in the
stream:

| `type` | Payload fields | Meaning |
| --- | --- | --- |
| `text` | `text` | Assistant text tokens (commentary or the final answer). |
| `tool_call` | `tool_call.id`, `tool_call.name`, `tool_call.arguments` | The tool name and raw JSON arguments the model requested. |
| `tool_result` | `tool_result.name`, `tool_result.content`, `tool_result.truncated` | A tool's result, inlined for the trace. |
| `script_run` | `script_run.source`, `script_run.stdout`, `script_run.stderr`, `script_run.exit_code`, `script_run.sandbox_id`, `script_run.truncated` | One `run_python` execution: the script that ran, its captured stdout/stderr, exit code, and which sandbox container ran it. |
| `provenance` | `provenance.data_locators`, `provenance.cited_in`, `provenance.dataset_dois`, `provenance.ontology_version` | Grounding provenance for the answer: the measurement's `dataLocator`(s), citing document(s), dataset DOI(s), and the ontology version used. |
| `done` | *(none)* | Marks the end of the turn, successful or not. |
| `error` | `error` | A turn-ending error (e.g. an LLM call failure or the max-iterations guard tripping). |

A terminating `done` event always closes every turn, including error
turns. Large `tool_result` and `script_run` payloads are truncated inline
(their `truncated` field is set) rather than blowing up the stream, but
truncation only ever applies to what is shown in the trace — the full
result is still what was fed back to the model.

### LLM configuration (DeepSeek)

The `server` service talks to DeepSeek V4 Pro through an OpenAI-compatible
client, configured by three environment variables (`docker-compose.yml`):

- `DEEPSEEK_BASE_URL` — the OpenAI-compatible base URL (default
  `https://api.deepseek.com`).
- `LLM_MODEL_ANALYSIS` — the analysis-agent model id (default
  `deepseek-v4-pro`).
- `DEEPSEEK_API_KEY` — the DeepSeek API secret. This is a **runtime
  secret only**: it is sourced from the host environment
  (`DEEPSEEK_API_KEY=... make up`, or your shell's exported env) and has no
  default. It must never be committed to the repo or baked into an image.

### Manual smoke-test checklist

With the stack up and fully built (`make up && make load-nist && make ingest
&& make link`) and `DEEPSEEK_API_KEY` set in the environment, exercise the
agent by hand with `make chat` (an interactive REPL against a running
`/api/chat`) or `make demo-density` (a canonical one-shot question). Confirm,
with the full trace visible for each:

- **Density answer.** "density of FLiBe (LiF-BeF₂ 66-34 mol%) at 900 K"
  resolves to ≈ **1.974 g·cm⁻³**. Grounding resolves the salt through a real
  `msr:Mention` from `ORNL-TM-2316` (`surfaceForm` → `msr:linksTo` →
  `msr:MoltenSalt`, with `msr:inDocument` naming the source), not a
  hand-curated alignment edge, and the trace shows a `script_run` event
  (a `run_python` execution) immediately preceding that number — the
  answer comes from the sandboxed script, not model arithmetic.
- **Out-of-range refusal.** A temperature outside the measurement's valid
  range is refused or explicitly flagged in the response, never silently
  extrapolated into a number presented as valid.
- **Comparative query.** A question like "lowest-viscosity fluoride salt
  at 700 K" is answered by one script that aggregates over the mounted
  database, not by multiple ad hoc lookups.
