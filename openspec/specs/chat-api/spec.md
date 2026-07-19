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
- `tool_call` — tool name and arguments.
- `tool_result` — result bindings/rows, truncated inline with the full payload retrievable.
- `script_run` — script source, stdout, stderr, exit code, and sandbox id.
- `provenance` — `dataLocator`s, `citedIn` documents, dataset DOIs, and the ontology version used.
- `done` — end of turn.

This request and event schema is the contract consumed by the chunk-10 frontend.

#### Scenario: Each event type is emitted and well-formed
- **WHEN** a chat turn grounds via SPARQL, reads SQL, runs a script, and answers
- **THEN** the stream carries `text`, `tool_call`, `tool_result`, `script_run`, `provenance`, and a terminating `done` event, each a well-formed typed payload

#### Scenario: script_run carries the script and its output
- **WHEN** the agent runs a `run_python` script during the turn
- **THEN** a `script_run` event carries the script source, stdout, stderr, exit code, and sandbox id

#### Scenario: provenance names the data sources
- **WHEN** an answer is grounded in a NIST-derived measurement
- **THEN** a `provenance` event names the value's `dataLocator`, the `citedIn` document, the dataset DOI, and the ontology version used

### Requirement: Traces are ephemeral
The server SHALL NOT persist chat traces; the stream is live per turn and nothing is stored for replay. Consistent with statelessness, an interrupted stream requires no server-side recovery — the client re-sends the conversation.

#### Scenario: No trace persisted after a turn
- **WHEN** a chat turn completes and the stream closes
- **THEN** no trace or session record is written to any store
