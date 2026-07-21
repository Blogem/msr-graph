# chat-ui Specification

## Purpose

Define the chat surface of the frontend: a stateless conversation that sends its full history to
`POST /api/chat` per turn, consumes the SSE trace-event stream via `fetch` streaming, and renders
a per-turn expandable trace timeline covering every chunk-4 event type — including tool calls,
script source and output, provenance chips, and the answer groundedness stamp. This capability
consumes the chunk-4 `chat-api` contract unchanged.

## Requirements

### Requirement: Stateless conversation posted in full per turn
The chat surface SHALL hold the full conversation history in the client and send it in full with
each turn as `{"messages": [{"role", "content"}, …]}` to `POST /api/chat`, relying on no
server-side session. After the assistant turn completes, the assistant message SHALL be appended
to the client-held history for the next turn.

#### Scenario: Full history sent on each turn
- **WHEN** the user sends a second message in a conversation
- **THEN** the request body contains the entire prior conversation plus the new user message

#### Scenario: Assistant reply retained client-side
- **WHEN** an assistant turn completes
- **THEN** the assistant message is appended to the client-held history and included in the next
  request

### Requirement: SSE stream consumed via fetch streaming
The chat surface SHALL consume the `POST /api/chat` response as a streamed body read with `fetch`
(not native `EventSource`, which cannot POST), parsing the SSE framing into typed trace events
and handling event boundaries that split across network chunks. Rendering SHALL be incremental as
events arrive.

#### Scenario: Events parsed from a streamed response
- **WHEN** the server streams SSE trace events in response to a chat POST
- **THEN** the client parses each event and updates the UI incrementally as events arrive

#### Scenario: Event split across chunk boundaries is parsed correctly
- **WHEN** a single SSE event's bytes are delivered across two network chunks
- **THEN** the parser buffers until the complete event frame is received and emits exactly one
  event

### Requirement: Trace timeline renders every event type
Each assistant turn SHALL present an expandable trace timeline that renders every chunk-4 trace
event type: `text` (assistant tokens streamed into the answer), `tool_call` (tool name and
arguments), `tool_result` (result bindings/rows, truncated with an expand affordance),
`script_run` (script source plus stdout, stderr, exit code, and sandbox id), `provenance`, and
`answer`. Events SHALL be shown in stream order.

#### Scenario: All event types are visible in a completed trace
- **WHEN** a turn grounds via SPARQL, reads SQL, runs a script, and answers
- **THEN** the timeline shows the `tool_call`, `tool_result`, `script_run`, `provenance`, and
  `answer` events in order and the streamed `text` in the answer

#### Scenario: Script source and output are inspectable
- **WHEN** a `script_run` event is rendered
- **THEN** its script source, stdout, stderr, and exit code are viewable in the timeline

### Requirement: Provenance rendered as source-linking chips
A `provenance` event SHALL be rendered as chips that surface the value's `dataLocator`(s), the
dataset DOI, any `citedIn` document (ORNL report), and the ontology version used, with document
references presented as links where a URL/identifier is available.

#### Scenario: Provenance chips name the sources
- **WHEN** an answer is grounded in a NIST-derived measurement
- **THEN** provenance chips show the `dataLocator`, dataset DOI, and ontology version, and an
  empty/absent `citedIn` is rendered without error

### Requirement: Answer groundedness is stamped
The `answer` event SHALL be rendered as a visible groundedness stamp on the turn: a grounded
answer shows its aggregated provenance chain, and an ungrounded answer (`grounded: false`) is
visibly flagged as unsourced.

#### Scenario: Grounded answer shows its provenance chain
- **WHEN** the `answer` event reports `grounded: true`
- **THEN** the turn is marked grounded and the aggregated provenance chain is shown

#### Scenario: Ungrounded answer is flagged
- **WHEN** the `answer` event reports `grounded: false`
- **THEN** the turn is visibly flagged as an unsourced answer

### Requirement: Unknown event types degrade gracefully
The chat surface SHALL tolerate trace events of an unrecognized type or with extra fields
(forward-compatibility with later chunks) by surfacing them in a raw/fallback form rather than
dropping them or failing the stream.

#### Scenario: Unrecognized event is not fatal
- **WHEN** the stream carries an event type the client does not explicitly render
- **THEN** the client renders it in a raw fallback form and continues processing the stream
