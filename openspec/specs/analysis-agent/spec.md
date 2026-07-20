# analysis-agent Specification

## Purpose

Define the grounded tool-using analysis agent (`internal/agent`) that drives an injected OpenAI-compatible LLM client through a bounded tool-use loop. The agent grounds every answer through the core-dataset SPARQL client, a read-only SQL tool, and a sandbox-executed Python tool; performs all arithmetic in sandbox scripts rather than in the model; enforces measurement temperature ranges; and keeps its answer surface schema-generic so new data becomes answerable without agent code changes.

## Requirements

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
The agent SHALL expose a `sparql_query` tool that runs SPARQL SELECT queries through the chunk-1 `internal/graph` core-dataset client (`Select`), so queries evaluate against exactly the three core graphs and staging/proposal graphs are invisible. The tool SHALL NOT expose the unrestricted (`SelectRaw`) path. Grounding SHALL resolve a **salt** reference to its `msr:MoltenSalt` individual by matching a real document `msr:Mention`'s `msr:surfaceForm` (optionally expanding the query term through a SKOS `prefLabel`/`altLabel` synonym in the vocab) and following `msr:linksTo` from that Mention to the salt; the matched Mention (with `msr:inDocument` + provenance) is the traceable evidence. Grounding SHALL resolve a **physical property** reference by matching the query's property term against the `rdfs:label` of a `msr:PhysicalProperty` term directly. Grounding SHALL NOT use `skos:closeMatch` at all — neither salt↔concept nor property-term↔concept; the SKOS vocab supplies labels for recognizing/expanding the query term only, and is never traversed as a grounding edge. No salt or property name is hardcoded in the agent.

#### Scenario: A salt reference grounds to a measurement via a real mention
- **WHEN** the agent issues a `sparql_query` to ground the salt reference "LiF-BeF₂ (66-34 mol%)"
- **THEN** the query matches a real `msr:Mention` whose `msr:surfaceForm` denotes that composition, follows `msr:linksTo` to the `msr:MoltenSalt` individual, and returns a `PropertyMeasurement` with its property, unit, equation form, valid temperature range, and a `dataLocator`

#### Scenario: A property grounds by its own label
- **WHEN** the agent grounds the property term "density"
- **THEN** the query matches `?prop a msr:PhysicalProperty ; rdfs:label "density"` directly, with no `skos:closeMatch` traversal

#### Scenario: Grounding uses no closeMatch anywhere
- **WHEN** the agent grounds any salt or property reference
- **THEN** the resolution paths are `Mention.surfaceForm → msr:linksTo → msr:MoltenSalt` (salts) and `rdfs:label → msr:PhysicalProperty` (properties), and no `skos:closeMatch` is required or present in the grounding path

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
The agent SHALL answer "density of FLiBe (the LiF-BeF₂ 66-34 mol% melt) at 900 K" as approximately **1.974 g·cm⁻³**, produced by grounding the salt reference to `msrd:salt-BeF2-LiF-34.0-66.0` (canonical form `BeF2-LiF | 34.0-66.0`) through a real `msr:Mention` — the linker-resolved `"LiF-BeF, (66-34 mole %)"` span from `ORNL-TM-2316`, whose `msr:linksTo` points at that salt — then reading its density measurement, fetching the coefficients (`c0=2.413`, `c1=-4.88e-4`) from `measurement_value` by the `dataLocator` `nist-srd27/density#BeF2-LiF|34.0-66.0`, and evaluating `c0 + c1·T` at T=900 in a sandbox script — with the final number equal to the script output. All grounding data is real: the salt and measurement come from `loader nist` (vendored NIST CSV) and the grounding link is a real document mention (no hand-curated seed, no `skos:closeMatch`). The demo presupposes the real pipeline (`loader nist` + `ingest` + `link`) has built the graph. (Full generation provenance — the extraction `Activity` and the dataset DOI — is added by the follow-on `provenance-model` change; a measurement↔document `msr:citedIn` edge awaits real citation extraction in chunk 7. This change requires only the mention's `msr:inDocument` to make grounding document-traceable.)

#### Scenario: Density question answered from real-mention grounding via a script
- **WHEN** the agent is asked for the density of FLiBe (LiF-BeF₂ 66-34 mol%) at 900 K after `loader nist` + `ingest` + `link` have run
- **THEN** the trace shows SPARQL grounding through a real `msr:Mention` (`surfaceForm → msr:linksTo → msrd:salt-BeF2-LiF-34.0-66.0`) and its density measurement, a coefficient fetch by the `dataLocator`, and a `script_run` evaluating the equation, and the final answer is ≈ 1.974 g·cm⁻³ equal to the script output

#### Scenario: Grounding traces to a real document
- **WHEN** the grounded answer is inspected
- **THEN** the matched `msr:Mention` names its `msr:inDocument` (`ORNL-TM-2316`), so the grounding itself — not just the measurement — is traceable to a real document (the fuller PROV chain is added by `provenance-model`)

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
