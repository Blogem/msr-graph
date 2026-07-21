# chat-api Specification

## Purpose

Define the stateless `POST /api/chat` endpoint that drives the grounded-analysis agent: it accepts the full conversation OpenAI-style in the request body, holds no server-side session state, streams typed trace events over Server-Sent Events as the turn progresses, and persists no traces. The request and event schema is the contract consumed by the frontend.

## Requirements

### Requirement: Stateless `POST /api/chat` endpoint
The server SHALL expose `POST /api/chat` that accepts the full conversation in the request body, OpenAI-style (`{"messages": [{"role": "user"|"assistant", "content": "…"}, …]}`), and holds **no** server-side session state. Each request SHALL be answered purely from its body plus the read-only stores; the server SHALL NOT write SQLite while serving a chat request.

#### Scenario: Full conversation carried in the request body
- **WHEN** a client POSTs a `messages` array containing the conversation so far
- **THEN** the server processes the turn from that body alone, without relying on any stored session

#### Scenario: Malformed request body is rejected
- **WHEN** a request omits `messages` or sends a body that does not match the expected shape
- **THEN** the server responds with a client error and starts no agent turn

### Requirement: SSE trace-event stream
The response to `POST /api/chat` SHALL be a Server-Sent Events stream of typed trace events emitted as the turn progresses. The event types and payloads SHALL be:

- `text` — assistant text tokens.
- `reasoning` — assistant chain-of-thought, surfaced separately from the answer's `text`.
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

### Requirement: Reasoning is separated from the answer text
The server SHALL NOT emit a model's chain-of-thought as `text`. When a model turn carries reasoning — either inline `<think>…</think>` blocks embedded in the message content or a separate `reasoning_content` field — the server SHALL strip it out of the answer content and emit it as a distinct `reasoning` event. Reasoning SHALL NOT be written back into the conversation history sent to the model on subsequent turns.

#### Scenario: Inline `<think>` reasoning is emitted separately
- **WHEN** the model returns content containing a `<think>…</think>` block
- **THEN** the `text` event carries only the answer with the block removed, and a `reasoning` event carries the block's contents

#### Scenario: `reasoning_content` field is surfaced
- **WHEN** the model response carries a separate `reasoning_content` field
- **THEN** its contents are emitted as a `reasoning` event rather than dropped

#### Scenario: Reasoning is not re-fed to the model
- **WHEN** a subsequent turn sends the conversation history
- **THEN** the prior assistant messages contain only the reasoning-free answer content

### Requirement: Traces are ephemeral
The server SHALL NOT persist chat traces; the stream is live per turn and nothing is stored for replay. Consistent with statelessness, an interrupted stream requires no server-side recovery — the client re-sends the conversation.

#### Scenario: No trace persisted after a turn
- **WHEN** a chat turn completes and the stream closes
- **THEN** no trace or session record is written to any store
