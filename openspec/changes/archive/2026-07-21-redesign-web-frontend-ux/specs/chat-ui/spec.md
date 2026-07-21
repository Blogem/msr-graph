## ADDED Requirements

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
