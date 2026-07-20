# chat-api (delta)

## MODIFIED Requirements

### Requirement: SSE trace-event stream
The response to `POST /api/chat` SHALL be a Server-Sent Events stream of typed trace events emitted as the turn progresses. The event types and payloads SHALL be:

- `text` — assistant text tokens.
- `tool_call` — tool name and arguments.
- `tool_result` — result bindings/rows, truncated inline with the full payload retrievable.
- `script_run` — script source, stdout, stderr, exit code, sandbox id, and the `dataLocator`(s) the script read.
- `provenance` — `dataLocator`s, `citedIn` documents, dataset DOIs, and the ontology version used.
- `answer` — the turn's groundedness verdict (`grounded`: true/false) and the aggregated provenance chain (the union of `dataLocator`s, `citedIn` documents, and dataset DOIs) of the facts the answer used, emitted once per turn immediately before `done`.
- `done` — end of turn.

This request and event schema is the contract consumed by the chunk-10 frontend.

#### Scenario: Each event type is emitted and well-formed
- **WHEN** a chat turn grounds via SPARQL, reads SQL, runs a script, and answers
- **THEN** the stream carries `text`, `tool_call`, `tool_result`, `script_run`, `provenance`, an `answer` stamp, and a terminating `done` event, each a well-formed typed payload

#### Scenario: script_run carries the script and its output
- **WHEN** the agent runs a `run_python` script during the turn
- **THEN** a `script_run` event carries the script source, stdout, stderr, exit code, sandbox id, and any `dataLocator`(s) the script read

#### Scenario: provenance names the data sources
- **WHEN** an answer is grounded in a NIST-derived measurement
- **THEN** a `provenance` event names the value's `dataLocator`, the dataset DOI, and the ontology version used (and a `citedIn` document when one is known — the NIST loader emits none, so a NIST-derived answer carries an empty `citedIn`; the field is populated once chunk-7 citation extraction lands)

#### Scenario: answer stamp marks groundedness before done
- **WHEN** a turn completes
- **THEN** an `answer` event is emitted immediately before `done`, carrying `grounded` true/false and, when grounded, the aggregated provenance chain of the facts the answer used

#### Scenario: An ungrounded answer is marked
- **WHEN** the turn returns a final answer with no provenance surfaced
- **THEN** the `answer` event carries `grounded: false` so the client can flag the answer as unsourced
