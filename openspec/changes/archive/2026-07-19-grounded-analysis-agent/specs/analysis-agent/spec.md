# Spec: analysis-agent

## ADDED Requirements

### Requirement: Tool-using agent loop over an injected LLM client
The system SHALL provide a Go agent (`internal/agent`) that drives DeepSeek V4 Pro through an **injected** OpenAI-compatible client interface, running a bounded tool-use loop: it sends the system prompt plus the conversation, and on each turn either executes the model's requested tool calls and continues, or returns the model's final answer when no tool call is requested. The loop SHALL be bounded by a maximum-iterations guard, and the LLM client SHALL be an interface so every test runs against a stub rather than a live model.

#### Scenario: Loop executes tool calls then returns the final answer
- **WHEN** a stubbed LLM returns a sequence of tool calls followed by a final text answer
- **THEN** the agent executes each tool call in order, feeds the results back to the model, and returns the final answer when the model requests no further tools

#### Scenario: Iteration bound stops a runaway loop
- **WHEN** the stubbed LLM requests tool calls without ever producing a final answer
- **THEN** the agent stops at the configured maximum iterations and ends the turn with an error rather than looping unbounded

#### Scenario: Tests use a stubbed client
- **WHEN** the agent-loop tests run
- **THEN** they exercise the loop against a stubbed LLM client and never contact a live model

### Requirement: All computation happens in sandbox scripts, never in the model
The agent SHALL perform no arithmetic itself: every numeric answer it reports MUST be the output of a `run_python` script executed in the chunk-3 sandbox pool. The final numeric answer returned for a turn MUST equal the value produced by the script.

#### Scenario: Final number equals script output
- **WHEN** the agent answers a question requiring a computation and the fake pool returns a specific numeric result from the script
- **THEN** the agent's final answer reports exactly that number, and no numeric result is computed by the model itself

#### Scenario: A numeric answer is preceded by a script run
- **WHEN** the agent produces a numeric answer in a turn
- **THEN** the trace for that turn contains a `script_run` whose output is the reported number

### Requirement: `sparql_query` grounds through the core-dataset client
The agent SHALL expose a `sparql_query` tool that runs SPARQL SELECT queries through the chunk-1 `internal/graph` core-dataset client (`Select`), so queries evaluate against exactly the three core graphs and staging/proposal graphs are invisible. The tool SHALL NOT expose the unrestricted (`SelectRaw`) path. Grounding SHALL resolve a mention to a salt individual, its measurement, `dataLocator`, equation form, unit, and valid temperature range by matching SKOS pref/altLabels and salt labels and following `skos:closeMatch` — with no salt or property name hardcoded in the agent.

#### Scenario: A mention grounds to a measurement via labels
- **WHEN** the agent issues a `sparql_query` to ground a salt mention such as "FLiBe" / "LiF-BeF2"
- **THEN** the query returns, via the core-dataset client, the matching `MoltenSalt` individual and a `PropertyMeasurement` with its property, unit, equation form, valid temperature range, and a `dataLocator`

#### Scenario: Staging is invisible to grounding
- **WHEN** a triple exists only in `urn:msr:staging` and the agent grounds via `sparql_query`
- **THEN** the staging triple does not appear in the tool result, because the tool reads through the core-dataset client

### Requirement: `sql_query` is read-only with a SELECT-only guard
The agent SHALL expose a `sql_query` tool that reads `measurement_value` through a read-only connection and rejects any statement that is not a single read-only `SELECT` — INSERT/UPDATE/DELETE, DDL, PRAGMA writes, and multi-statement input SHALL be refused before reaching SQLite.

#### Scenario: A SELECT returns rows
- **WHEN** `sql_query` runs `SELECT c0, c1 FROM measurement_value WHERE locator = ?` for a known locator
- **THEN** it returns the matching coefficient row

#### Scenario: Non-SELECT statements are rejected
- **WHEN** `sql_query` is called with an `INSERT`, `UPDATE`, `DELETE`, DDL, or multi-statement input (including attempts to smuggle a write past a comment)
- **THEN** the guard rejects it before it reaches SQLite and no write occurs

### Requirement: `run_python` executes computation in the sandbox pool
The agent SHALL expose a `run_python` tool that submits script source to the chunk-3 sandbox pool via its `Run` interface and captures stdout, stderr, and exit code for the trace. Scripts read the read-only `/data/msr.db` mount and return JSON on stdout; a non-zero exit SHALL be surfaced as a tool result (captured stderr + code), not a crash. The tool's description presented to the model SHALL state the runtime contract the generated scripts must target: the read-only SQLite database path `/data/msr.db`, the availability of `numpy`/`pandas`, and that the result is JSON printed to stdout.

#### Scenario: Tool description advertises the database path and runtime contract
- **WHEN** the tool schema exposed to the model is inspected
- **THEN** the `run_python` description names the read-only database path `/data/msr.db`, the available libraries, and the JSON-on-stdout result contract, so scripts the model writes know where and how to read the data

#### Scenario: A script computes and returns JSON
- **WHEN** the agent submits a script that reads coefficients and evaluates an equation, and the fake pool returns the computed JSON
- **THEN** `run_python` returns that stdout and the agent uses it as the computed result

#### Scenario: A failing script surfaces stderr and exit code
- **WHEN** a submitted script exits non-zero
- **THEN** the tool result carries the captured stderr and non-zero exit code and the agent does not crash

### Requirement: Grounded temperature-range enforcement
When a requested temperature falls outside a measurement's `[validTempMin, validTempMax]` range obtained during grounding, the agent SHALL flag or refuse rather than report an extrapolated value as if it were a valid measurement.

#### Scenario: Out-of-range temperature is not silently extrapolated
- **WHEN** the agent is asked for a property at a temperature outside the measurement's valid range
- **THEN** the answer flags or refuses the out-of-range request and does not present an extrapolated number as a valid measurement

### Requirement: End-to-end grounded density answer
The agent SHALL answer "density of FLiBe (the LiF-BeF₂ 66-34 mol% melt) at 900 K" as approximately **1.974 g·cm⁻³**, produced by grounding the mention to the seed FLiBe salt (`msrd:salt-BeF2-LiF-34.0-66.0`, canonical form `BeF2-LiF | 34.0-66.0`) and its density measurement, fetching the coefficients (`c0=2.413`, `c1=-4.88e-4`) from `measurement_value` by the `dataLocator` `nist-srd27/density#BeF2-LiF|34.0-66.0`, and evaluating `c0 + c1·T` at T=900 in a sandbox script — with the final number equal to the script output.

#### Scenario: Density question answered from grounded coefficients via a script
- **WHEN** the agent is asked for the density of FLiBe (LiF-BeF₂ 66-34 mol%) at 900 K with the seed data loaded
- **THEN** the trace shows SPARQL grounding to the FLiBe salt and its density measurement, a coefficient fetch by the `dataLocator`, and a `script_run` evaluating the equation, and the final answer is ≈ 1.974 g·cm⁻³ equal to the script output

### Requirement: Comparative queries answered by aggregation in one script
The agent SHALL answer comparative questions (e.g. "lowest-viscosity fluoride salt at 700 K") by grounding the candidate salts and running a single sandbox script that aggregates over the mounted database, rather than by model-side comparison.

#### Scenario: Comparison resolved by a single aggregating script
- **WHEN** the agent is asked for the lowest-viscosity fluoride salt at a given temperature
- **THEN** it grounds the candidates and runs one `run_python` script that aggregates over `/data/msr.db`, and the reported winner is the script's output

### Requirement: Schema-generic answer surface
The agent SHALL hardcode no salt names, property names, or measurement identifiers; its answer surface SHALL be exactly what the graph and measurement store currently contain, so data added by later chunks becomes answerable with no agent code change.

#### Scenario: New data is answerable without code changes
- **WHEN** a new `PropertyMeasurement` and its coefficient row are present in the stores that were not present before
- **THEN** the agent can ground and answer questions about it without any change to the agent's code
