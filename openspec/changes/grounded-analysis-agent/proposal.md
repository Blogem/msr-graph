# Proposal: grounded-analysis-agent

## Why

The POC's structured track has landed running stores (chunk 1), the NIST fluoride subset in SQLite with catalog triples in the graph (chunk 2), and a safe sandbox execution pool (chunk 3) — but nothing yet turns a natural-language question into a grounded, traceable answer. This change builds demo #1 (milestone **M3**): a conversational agent that answers domain questions from the graph + the measurement table, does **all** computation in sandboxed scripts (never in the model), and streams a full trace of how each answer was produced — the first end-to-end proof that the design works, delivered over an API before any UI exists.

## What Changes

- **Go agent loop** (`internal/agent`, DeepSeek V4 Pro via an **injected** OpenAI-compatible client) with **three tools**:
  - `sparql_query` — grounding: resolve a mention like "FLiBe" / "LiF-BeF2" to a salt individual, its measurement, `dataLocator`, equation form, and valid temperature range via the graph + SKOS pref/altLabels; reads **through the core-dataset client** (`Select`), so staging/proposal graphs stay invisible.
  - `sql_query` — read-only, **SELECT-only guarded** reads of `measurement_value`.
  - `run_python` — executes computation (equation evaluation, aggregation, comparison) in the chunk-3 sandbox pool. Its tool description tells the model the runtime contract the scripts must target: the read-only SQLite database is at **`/data/msr.db`**, `numpy`/`pandas` are available, and the script returns its JSON result on stdout.
- **Computation invariant**: the model never does arithmetic — every numeric answer is the output of a `run_python` script. The final answer equals the script output.
- **Cached KG-schema system prompt**: a byte-stable serialization of the TBox + vocab + salt catalog, built by a Go prompt builder that lives in this chunk; rebuilt only when the per-request `owl:versionInfo` check detects an ontology version bump (so approvals/restores in later chunks are picked up live).
- **Stateless chat API**: `POST /api/chat` on the server carries the full conversation in the request body (OpenAI-style `messages`; no server-side sessions) and streams **SSE trace events** — `text`, `tool_call`, `tool_result`, `script_run`, `provenance`, `done`. This request + event schema is the chunk-10 contract. Traces are ephemeral; the server never writes SQLite.
- **Schema-generic**: no salt or property names are hardcoded, so chunks 7 and 9 grow the agent's answer surface with **no agent code change**.
- **LLM configuration** wired into the `server` service (`DEEPSEEK_BASE_URL`, `LLM_MODEL_ANALYSIS`).
- **Manual-verification CLI** (`cmd/chatcli`): a small terminal client that POSTs to `/api/chat` and pretty-prints the SSE trace — a playground to exercise the agent end-to-end (density answer, out-of-range refusal, comparison) until chunk 10's frontend lands.

## Capabilities

### New Capabilities

- `analysis-agent`: the Go agent loop, its three grounded/guarded/sandboxed tools, the model-does-no-arithmetic invariant, the injected LLM client (stub in tests), and its schema-generic answer surface.
- `kg-schema-prompt`: the cached, byte-stable KG-schema system-prompt builder (TBox + vocab + salt-catalog serialization) and its rebuild-on-`owl:versionInfo`-bump behavior.
- `chat-api`: the stateless `POST /api/chat` endpoint and its SSE trace-event stream (`text`, `tool_call`, `tool_result`, `script_run`, `provenance`, `done`) — the request + event contract chunk 10 consumes.

### Modified Capabilities

- `container-stack`: the `server` service gains LLM configuration (`DEEPSEEK_BASE_URL`, `LLM_MODEL_ANALYSIS`) so it can reach the analysis model at runtime.

## Impact

- **New code**: `internal/agent/` (loop, tool implementations, trace events, prompt builder — Go + tests); chat-API handler in `cmd/server`; wiring of the injected LLM client and the chunk-3 sandbox pool into the server; `cmd/chatcli` (manual-verification CLI) + a `make chat` target.
- **Consumes (read-only)**: `internal/graph` core-dataset client (chunk 1), the `measurement_value` store (chunks 1–2), the catalog triples + SKOS labels (chunks 1–2), and the sandbox `Run` interface (chunk 3).
- **APIs**: introduces `POST /api/chat` (SSE) — the stateless request body + trace-event schema that chunk 10's frontend depends on.
- **Config**: `DEEPSEEK_BASE_URL`, `LLM_MODEL_ANALYSIS` (additive `server` env in `docker-compose.yml`); every test runs against a stubbed LLM and a fake pool — never a live model.
- **Downstream**: chunks 7 (text-derived measurements) and 9 (approved ontology changes) extend the stores/ontology the agent already reads, so its answers grow with no code change; chunk 10 renders this chunk's trace events and consumes this chat contract.
