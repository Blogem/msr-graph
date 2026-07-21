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
`answer`. Events SHALL be shown in stream order. The `reasoning` event is not part of the trace
timeline — it has its own affordance (see "Model reasoning shown in a collapsible section").

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

### Requirement: Assistant answers render sanitized markdown
The chat surface SHALL render the assistant answer body as formatted markdown — headings, bold/italic, ordered and unordered lists, inline code and fenced code blocks, tables, and links — rather than as literal plain text. Because the answer is untrusted LLM output, the rendered HTML SHALL be sanitized before insertion into the DOM; no unsanitized model output is ever rendered as HTML. User turns and trace-event payloads are not affected by this requirement.

#### Scenario: Markdown formatting is rendered
- **WHEN** an assistant answer contains `**bold**`, a `- ` list, and a fenced code block
- **THEN** the surface renders bold text, a list, and a code block — not the literal `**`, `-`, and backtick characters

#### Scenario: Malicious markup is sanitized
- **WHEN** an assistant answer contains embedded HTML such as a `<script>` tag or an `onerror` attribute
- **THEN** the dangerous markup is stripped by sanitization and does not execute

#### Scenario: Incomplete streamed markdown does not break rendering
- **WHEN** the answer is mid-stream and contains partial/unterminated markdown (e.g. an unclosed code fence)
- **THEN** rendering succeeds without throwing and completes correctly once the remaining tokens arrive

### Requirement: Model reasoning shown in a collapsible section
When a turn carries `reasoning` events, the chat surface SHALL accumulate their text and present it in a collapsed disclosure ("Thinking") shown above the answer, visually distinct from the answer body. Reasoning SHALL NOT be concatenated into the answer bubble.

#### Scenario: Reasoning appears under a collapsed disclosure
- **WHEN** the stream carries `reasoning` events for a turn
- **THEN** a collapsed "Thinking" section holds the reasoning and the answer bubble contains only the answer `text`

#### Scenario: A turn with no reasoning shows no disclosure
- **WHEN** a turn carries no `reasoning` events
- **THEN** no "Thinking" disclosure is rendered

### Requirement: In-progress streaming affordance
While an assistant turn is still streaming, the chat surface SHALL show a visible in-progress affordance (such as a caret or pulse) on that turn, and SHALL remove it when the turn completes or errors, so it is always clear whether the assistant is still responding.

#### Scenario: Streaming turn is visibly in progress
- **WHEN** assistant tokens are still arriving for the current turn
- **THEN** the turn shows an in-progress affordance

#### Scenario: Completed turn is not marked in progress
- **WHEN** the turn completes (the stream is done) or errors
- **THEN** the in-progress affordance is removed

### Requirement: Assistant answer has a copy action
Each completed assistant answer SHALL offer a copy action that places the answer text on the clipboard, so a reviewer can lift a grounded answer without manual selection. The action SHALL confirm it fired (e.g. a transient "copied" state or toast).

#### Scenario: Copy places the answer on the clipboard
- **WHEN** the user activates the copy action on a completed assistant answer
- **THEN** the answer text is written to the clipboard and the action shows a transient confirmation

### Requirement: Empty conversation shows onboarding prompts
When the conversation has no turns yet, the chat surface SHALL present onboarding guidance including one or more example prompts the user can run, so a first-time user is not faced with only an empty input.

#### Scenario: First load offers example prompts
- **WHEN** the chat surface loads with an empty conversation
- **THEN** it shows example prompt suggestions

#### Scenario: Onboarding disappears once the conversation starts
- **WHEN** the user sends the first message
- **THEN** the onboarding guidance is no longer shown and the conversation is displayed
