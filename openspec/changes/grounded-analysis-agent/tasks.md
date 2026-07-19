# Tasks: grounded-analysis-agent

## 1. Agent package scaffolding and LLM client

- [ ] 1.1 Create `internal/agent` with the injected OpenAI-compatible LLM client interface (method(s) for a chat/tool-use turn) and a DeepSeek-backed implementation constructed from `DEEPSEEK_BASE_URL` + `LLM_MODEL_ANALYSIS` (default model id `deepseek-v4-pro`); default the loop to 10 iterations and a 120 s per-turn deadline (both config-overridable)
- [ ] 1.2 Define the trace-event types (`text`, `tool_call`, `tool_result`, `script_run`, `provenance`, `done`) as typed Go structs with their payload fields
- [ ] 1.3 Implement the bounded tool-use loop: send system prompt + conversation, execute requested tool calls, feed results back, return the final answer when no tool is requested; enforce a max-iterations guard emitting an error event on overrun

## 2. Tools

- [ ] 2.1 Implement the `sparql_query` tool over the chunk-1 `internal/graph.Select` core-dataset client (do not expose `SelectRaw`); grounding walk resolves mention → SKOS pref/altLabel + salt label → `skos:closeMatch` salt → `PropertyMeasurement` (property, unit, equation form, `validTempMin`/`Max`, `dataLocator`, `citedIn`, `prov:wasDerivedFrom`), with no salt/property name hardcoded
- [ ] 2.2 Implement the `sql_query` tool over an `internal/store` read-only connection with a SELECT-only guard rejecting INSERT/UPDATE/DELETE, DDL, PRAGMA writes, multi-statement, and comment-smuggled writes before reaching SQLite
- [ ] 2.3 Implement the `run_python` tool over the chunk-3 `sandbox.Run` interface, capturing stdout/stderr/exit code and surfacing non-zero exits as tool results (not crashes); its tool description MUST advertise the runtime contract to the model — read-only DB at `/data/msr.db`, `numpy`/`pandas` available, JSON result on stdout
- [ ] 2.4 Enforce the no-model-arithmetic invariant and out-of-range temperature handling in the loop/prompt: numeric answers come from `run_python`; a requested temperature outside `[validTempMin, validTempMax]` is flagged/refused, not extrapolated

## 3. KG-schema prompt builder

- [ ] 3.1 Implement the Go prompt builder: canonical, IRI-sorted, deterministically formatted serialization of TBox + SKOS vocab + salt catalog (schema only — no measurements/mentions/evidence)
- [ ] 3.2 Implement per-request `owl:versionInfo` detection (one `Select`) with cache reuse when unchanged and rebuild on bump; expose the detected version for the `provenance` event

## 4. Chat API (`cmd/server`)

- [ ] 4.1 Add the `POST /api/chat` handler: decode the stateless OpenAI-style `{"messages":[…]}` body, reject malformed bodies with a client error, and start an agent turn
- [ ] 4.2 Stream the turn as SSE trace events (via `fetch`-streamable SSE), emitting each event type as it occurs and a terminating `done`; truncate large `tool_result`/`script_run` payloads inline with full payload retrievable; persist nothing
- [ ] 4.3 Wire the agent's dependencies into the server: core-dataset client, read-only store connection, chunk-3 sandbox pool, prompt builder, and injected LLM client

## 5. Configuration

- [ ] 5.1 Add `DEEPSEEK_BASE_URL` and `LLM_MODEL_ANALYSIS` (default `deepseek-v4-pro`) to the `server` service in `docker-compose.yml` (additive) and read them at server startup; source the API secret from the environment, never committed

## 6. Tests

- [ ] 6.1 Agent-loop tests with a stubbed LLM + fake pool: correct tool-call/final-answer sequence, final numeric answer equals the fake script output (no model arithmetic), a numeric answer is preceded by a `script_run`, and the max-iterations bound stops a runaway loop
- [ ] 6.2 End-to-end grounded density test (stubbed LLM + fake pool): "density of FLiBe (LiF-BeF₂ 66-34 mol%) at 900 K" → ≈ 1.974 g·cm⁻³ from `c0=2.413`, `c1=-4.88e-4` (locator `nist-srd27/density#BeF2-LiF|34.0-66.0`) via a script; trace shows grounding → coefficient fetch → `script_run`
- [ ] 6.3 Out-of-range temperature test: a temperature outside the valid range is flagged/refused, not reported as a valid number
- [ ] 6.4 Comparative-query test (stubbed LLM + fake pool): a "lowest-viscosity" question is resolved by a single aggregating script whose output is the reported winner
- [ ] 6.5 SELECT-only-guard table tests: clean SELECTs pass; INSERT/UPDATE/DELETE, DDL, PRAGMA writes, multi-statement, and comment-smuggled writes are rejected
- [ ] 6.6 SSE handler tests: stateless request shape accepted, malformed body rejected, every event type emitted and well-formed, `script_run` carries source+stdout+stderr+exit+sandbox id, `provenance` names locator/citedIn/DOI/version, and no trace is persisted
- [ ] 6.7 Prompt-builder tests: byte-identical output for a fixed graph state (order-independent of query result order); rebuild triggered when `owl:versionInfo` changes; instance data absent from the prompt
- [ ] 6.8 Schema-generic test: a newly present measurement/coefficient row becomes answerable with no agent code change

## 7. Manual verification tooling (playground until the frontend lands)

- [ ] 7.1 Build a small CLI (`cmd/chatcli`) that POSTs a question to a running `/api/chat`, consumes the SSE stream, and pretty-prints each trace event to the terminal (assistant text, tool calls/results, script source + stdout, provenance chips, done) — an interactive playground for the agent before chunk 10's UI exists
- [ ] 7.2 Support a multi-turn REPL mode in the CLI: keep the conversation in memory and re-send the full `messages` array each turn (exercising the stateless contract exactly as chunk 10 will)
- [ ] 7.3 Add a `make chat` target (and a `make demo-density` shortcut running the canonical density question) that runs the CLI against the live stack, and record a manual smoke-test checklist in the README: density answer ≈ 1.974 g·cm⁻³, out-of-range refusal, and a comparative query, each with its full trace visible

## 8. Documentation

- [ ] 8.1 Document the `POST /api/chat` request shape and SSE trace-event contract (the chunk-10 interface) and the `DEEPSEEK_BASE_URL` / `LLM_MODEL_ANALYSIS` configuration in the README
