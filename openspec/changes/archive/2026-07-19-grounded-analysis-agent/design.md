# Design: grounded-analysis-agent

## Context

Chunks 1–3 landed the substrate this change needs: a seeded GraphDB with the core-dataset `internal/graph` client (chunk 1), the NIST fluoride subset in `measurement_value` plus catalog triples in `urn:msr:data` (chunk 2), and a warm sandbox pool exposing `Run(ctx, script) → (stdout, stderr, exitCode)` (chunk 3). None of it is yet reachable by a user. This change adds the conversational analysis agent and its chat API — demo #1, milestone **M3**.

Binding contracts (from `docs/ARCHITECTURE.md` → _Runtime contracts_ / _Analysis execution_ / _Conversational analytics_, and `docs/IMPLEMENTATION_PLAN.md` → _Cross-cutting contracts_):

- **All computation in sandboxed scripts, never in the model.** The agent writes Python, runs it via the chunk-3 pool, and its final numbers must equal script output. Graph = method, table = numbers, sandbox = computation.
- **Read-only over both stores.** The agent grounds via `Select` (core dataset — staging invisible), reads coefficients via SELECT-only SQL, and computes in sandboxes that mount `/data/msr.db` read-only. The server never writes SQLite.
- **Stateless chat API.** `POST /api/chat` carries the full conversation (`{"messages": [{"role","content"}, …]}`, OpenAI-style); no server-side sessions. The response streams SSE trace events. Traces are ephemeral.
- **Cached byte-stable KG-schema prompt.** A deterministic serialization of TBox + SKOS vocab + salt catalog, rebuilt only when a per-request `owl:versionInfo` SELECT shows a bump. Instance data (measurements, mentions, evidence) stays behind tools, never baked into the prompt.
- **DeepSeek only, injected, stubbed in tests.** V4 Pro via an OpenAI-compatible client behind an injected interface (`DEEPSEEK_BASE_URL`, `LLM_MODEL_ANALYSIS`). Every test runs against a stub — never a live model.
- **Schema-generic.** No salt or property names are hardcoded; the answer surface is whatever the graph + table currently hold, so chunks 7 and 9 extend it with no agent code change.

## Goals / Non-Goals

**Goals:**

- A Go agent loop (`internal/agent`) driving DeepSeek V4 Pro through a tool-use cycle with three tools: `sparql_query`, `sql_query`, `run_python`.
- The density question — "density of FLiBe (the LiF-BeF₂ 66-34 mol% melt) at 900 K" — answered as ≈ **1.974 g·cm⁻³**, where the number is the output of a sandbox script (ρ(T)=2.413−4.88e-4·T at 900 K), not model arithmetic; the trace shows grounding → coefficient fetch (locator `nist-srd27/density#BeF2-LiF|34.0-66.0`) → `script_run`.
- Out-of-range temperatures flagged/refused against the measurement's `[validTempMin, validTempMax]`, never silently extrapolated.
- Comparative queries ("lowest-viscosity fluoride salt at 700 K") answered by one script aggregating over the mounted DB.
- The cached KG-schema prompt builder: byte-stable for a fixed graph state, rebuilt on `owl:versionInfo` bump.
- `POST /api/chat`: stateless request, SSE stream emitting every trace-event type (`text`, `tool_call`, `tool_result`, `script_run`, `provenance`, `done`).
- Tests: stubbed LLM + fake pool (final answer equals script output; correct event sequence), SELECT-only-guard table tests, SSE handler tests (incl. stateless shape), prompt-prefix stability + rebuild-on-bump.
- A small manual-verification CLI (`cmd/chatcli`) that drives `/api/chat` and renders the trace in the terminal, so the whole demo can be exercised by hand before chunk 10's UI exists.

**Non-Goals:**

- No web frontend (chunk 10) — this change delivers the chat API + trace-event contract plus a terminal CLI playground only; there is no browser UI, rendered diff, or admin surface.
- No write path of any kind — no ontology evolution (chunks 8–9), no checkpoint/restore (chunk 9), no SQLite writes.
- No text-derived data (chunks 6–7); the agent reads whatever the stores hold and gains those answers for free later.
- No sandbox-pool internals (chunk 3) — this change consumes `Run`, it does not build the pool.
- No live-model integration test; DeepSeek is exercised only through the injected stub. Pinning exact DeepSeek model ids is config, not code.

## Decisions

### D1 — Agent loop: bounded tool-use cycle, model orchestrates, code computes

`internal/agent` runs a standard tool-calling loop against the injected LLM client: send system prompt + conversation, receive either assistant text or tool calls, execute the tools, append results, repeat until the model emits a final answer with no tool calls (bounded by a max-iterations guard to prevent runaways). The model decides _which_ tool and _what_ arguments; it never performs computation. Each loop step emits trace events as it happens.

- _Why a tool loop and not a fixed pipeline?_ The question space is open (point evaluation, range checks, cross-salt comparison). A fixed SPARQL→SQL→eval pipeline can't express "aggregate over all fluoride salts." The loop lets the model compose the three tools per question while the invariant (computation in scripts) is enforced structurally: arithmetic answers can only come from `run_python`.
- _Why a max-iterations bound?_ A stubbed test can force a loop; production needs a hard stop. Exceeding it ends the turn with an error trace event, not a hang.
- _Defaults:_ **10** loop iterations and a **120 s** per-turn deadline (whole turn, distinct from chunk 3's per-script sandbox wall-clock timeout). Both are config-overridable; 10 iterations comfortably covers ground → fetch → compute → (compare) with headroom, and 120 s bounds a stuck turn without truncating a legitimate multi-script comparison.

### D2 — Three tools, each read-only and guarded at its own layer

| Tool           | Backing                                                       | Guard                                                                                                                                                                                  |
| -------------- | ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sparql_query` | `internal/graph.Select` (core dataset)                        | Chunk-1 client injects the three core `FROM` graphs and rejects query-carried `FROM`/`FROM NAMED`; staging/proposals are invisible.                                                    |
| `sql_query`    | `measurement_value` via `internal/store` read-only connection | **SELECT-only guard** in this chunk: reject any statement that is not a single read-only `SELECT` (no INSERT/UPDATE/DELETE/DDL/PRAGMA-write/multi-statement) before it reaches SQLite. |
| `run_python`   | chunk-3 `sandbox.Run`                                         | Isolation is the sandbox's (network-none, read-only mount, limits, single-use); this chunk passes the script through and captures stdout/stderr/exit.                                  |

- _Why `sql_query` in addition to `run_python` reading the DB directly?_ Cheap lookups ("what coefficients/range does this locator have?") don't need a container; the SELECT-only guard keeps them safe. Heavy computation goes to `run_python`. Both read the same file read-only.
- _Why not let the agent write SPARQL with its own `FROM`?_ The chunk-1 client already rejects that with a pointer to `SelectRaw`; the agent uses `Select` exclusively, so it cannot reach staging. `SelectRaw` is not exposed as a tool.
- _How does the model know where the data is?_ The scripts the model writes need the database path, so the `run_python` **tool description** (part of the tool schema the model sees) states the runtime contract explicitly: the read-only SQLite database is mounted at **`/data/msr.db`**, `numpy`/`pandas` are preinstalled, and the script must print its JSON result to stdout. The path is a fixed contract with chunk 3's sandbox spec, not something the model guesses.

### D3 — Grounding is schema-generic: labels → concept → salt → measurement → locator → coefficients

`sparql_query` grounds a mention by matching `skos:prefLabel`/`skos:altLabel` (and salt `rdfs:label`) to a vocab concept, following `skos:closeMatch` to the `MoltenSalt` individual, then reading its `PropertyMeasurement` (`forProperty`, `hasUnit`, `equationForm`, `validTempMin`/`Max`, `dataLocator`, `prov:wasDerivedFrom`, `citedIn`). The `dataLocator` string is the key into `measurement_value`; `sql_query`/`run_python` fetch `c0..c4` and the equation form's `formula`, and the script evaluates it. No salt or property name is hardcoded anywhere — the grounding walks the graph the model was shown in the prompt.

- _Why label-based grounding rather than string-matching salts?_ "FLiBe" is a vocab `altLabel` on `voc:flibe`; the salt IRI is `msrd:salt-BeF2-LiF-34.0-66.0` (canonical `BeF2-LiF | 34.0-66.0`, the eutectic with the seed density measurement). Only the SKOS layer bridges the two. This is also why the salt catalog and vocab are in the cached prompt: the model needs to see the label vocabulary to form grounding queries.
- _Consequence — the surface grows for free:_ when chunk 7 adds a text-derived measurement or chunk 9 approves `solubility`, the same grounding walk reaches it with no code change (the M4/M5 milestones depend on this).

### D4 — Cached KG-schema prompt: byte-stable prefix, per-request version check, rebuild on bump

A Go prompt builder (owned by this chunk) serializes the ontology TBox + SKOS vocab + salt catalog into a canonical, deterministically ordered string — the byte-stable prefix DeepSeek's automatic prefix caching keys on. The server does one cheap `owl:versionInfo` SELECT at the **start of every chat request**; if the version is unchanged it reuses the cached prompt, if it changed it rebuilds. This covers chunk-9 approvals and restores with no push signal. Instance data (measurements, mentions, evidence) is deliberately **not** in the prompt — it grows unbounded and traceability wants data retrieval visible as tool calls.

- _Why per-request version check rather than a cache TTL or restart?_ Approvals/restores happen while the server runs; a version check is one SELECT and makes the live agent pick up schema changes deterministically. The check result is also the `provenance` event's "ontology version used".
- _Why byte-stable ordering matters:_ prefix caching only helps if the prefix is identical across requests. The builder sorts every set (classes, properties, concepts, salts) by IRI and formats numbers/labels canonically so the same graph state always yields the same bytes. A test pins this.

### D5 — Chat API: stateless `POST /api/chat` streaming SSE trace events (the chunk-10 contract)

The server exposes `POST /api/chat`. The request body is the full conversation, OpenAI-style: `{"messages": [{"role": "user"|"assistant", "content": "…"}, …]}`. No session state is held. The response is an SSE stream of trace events, each a typed JSON payload:

| Event         | Payload                                                                  |
| ------------- | ------------------------------------------------------------------------ |
| `text`        | assistant text tokens                                                    |
| `tool_call`   | tool name + arguments                                                    |
| `tool_result` | bindings/rows (truncated inline; full payload retrievable)               |
| `script_run`  | script source, stdout, stderr, exit code, sandbox id                     |
| `provenance`  | `dataLocator`s, `citedIn` documents, dataset DOIs, ontology version used |
| `done`        | end of turn                                                              |

This request + event schema **is** the chunk-10 contract; the frontend consumes it via `fetch` streaming (native `EventSource` can't POST).

- _Why stateless?_ The demo is single-user and the trace is ephemeral; holding no session state keeps the server a pure function of the request and means the client (chunk 10) owns history. It also keeps the "server never writes" invariant clean.
- _Why SSE and not WebSocket?_ The stream is one-directional (server → client) per turn; SSE-over-`fetch` is the simplest transport that carries typed events and matches the chunk-10 consumption model.
- _Truncation default:_ `tool_result` inlines the first **50 rows/bindings** and `script_run` caps stdout/stderr at **~4 KB** each; when a payload is truncated the event carries a truncation flag and the full payload stays retrievable. These defaults keep the stream readable without hiding data; chunk 10 confirms them against the trace-timeline UI.

### D6 — Test strategy: stubbed LLM + fake pool, deterministic and offline

The LLM client and the sandbox pool are injected interfaces. Agent-loop tests drive a **stubbed LLM** that returns a scripted sequence of tool calls then a final answer, and a **fake pool** that returns canned script output; the test asserts (a) the final numeric answer equals the fake script's output — proving the model did no arithmetic — and (b) the emitted trace-event sequence is correct. The SELECT-only guard gets table-driven tests (accept clean SELECTs; reject writes, DDL, multi-statement, comment-smuggled writes). SSE handler tests assert the stateless request shape and that each event type is emitted and well-formed. Prompt-builder tests assert byte-identical output for a fixed graph state and a rebuild when `owl:versionInfo` changes. No test contacts DeepSeek or requires a Docker daemon; integration against the real pool/GraphDB is chunk 3's / chunk 1's concern.

- _Why assert final == script output specifically?_ It is the operational form of the no-model-arithmetic invariant — the single most important correctness property of the whole demo.

### D7 — Out-of-range temperatures are surfaced, not extrapolated

Grounding returns each measurement's `[validTempMin, validTempMax]`. When a requested temperature falls outside that range, the agent must flag/refuse rather than report an extrapolated value as if valid — the validity range is part of the answer contract, and the equation forms are fits, not physics. The observable behavior (a refusal/flag, not a silent number) is pinned by spec; whether the check lives in the generated script or the agent turn is an implementation detail, but the value must not be presented as a valid measurement.

## Risks / Trade-offs

- **Agent emits invalid or wide SPARQL/SQL.** → The chunk-1 `Select` guard rejects `FROM`-carrying queries (pointing at `SelectRaw`, which is not a tool); the SELECT-only guard rejects non-read SQL. Guard rejections surface as `tool_result` error events the loop can react to, not crashes.
- **Model tries to answer arithmetic itself, bypassing `run_python`.** → The invariant is enforced by test (final == script output) and by prompt instruction; a numeric claim with no preceding `script_run` in the trace is a visible defect the trace makes obvious. Mitigation is structural, not just prompt-based: the demo acceptance test fails if the number wasn't produced by a script.
- **Prompt prefix drifts (non-deterministic serialization) and silently kills caching.** → Byte-stability test pins identical output for fixed graph state; all sets sorted by IRI, numbers/labels canonically formatted.
- **Unbounded tool loop / runaway cost.** → Max-iterations bound ends the turn with an error trace event.
- **Large `tool_result` / `script_run` payloads bloat the SSE stream.** → Results truncated inline with full payload retrievable, per the event contract; scripts return compact JSON.
- **SSE stream interrupted mid-turn.** → Traces are ephemeral and stateless; the client simply re-sends the conversation. No server-side recovery needed.
- **Chunk-2/3 interfaces are still in flight (Phase 2).** → This change depends only on the _published_ contracts (the `measurement_value` schema, catalog-triple shapes, `Select`, and `sandbox.Run` signature), all fixed in the cross-cutting contracts; it consumes them through interfaces, so implementation lands after those merge.

## Migration Plan

Additive — no existing behavior changes. New code lives in `internal/agent` and the `cmd/server` chat handler; `docker-compose.yml` gains `DEEPSEEK_BASE_URL` and `LLM_MODEL_ANALYSIS` on the `server` service (additive, per the root-config ownership rule). Bring-up is unchanged (`make up` / `make load-seed`); the server gains the `/api/chat` route. Rollback = revert the change; the stores are untouched. Depends on chunks 1–3 being merged first.

## Open Questions

All previously-open items are now resolved with defaults; recorded here for traceability:

- **DeepSeek V4 Pro model id** — resolved: default `LLM_MODEL_ANALYSIS=deepseek-v4-pro`. Config-overridable if DeepSeek publishes a different identifier; no code contract depends on the literal id.
- **Max loop iterations and per-turn timeout** — resolved (see D1): defaults **10** iterations and a **120 s** per-turn deadline, both config-overridable.
- **`tool_result` truncation threshold** — resolved (see D5): inline the first **50 rows/bindings** and cap `script_run` stdout/stderr at **~4 KB** each, full payload retrievable; chunk 10 confirms against the trace-timeline UI.
