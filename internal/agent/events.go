package agent

// EventType discriminates the payload carried by an Event. The chat API
// (a later wave) streams these as typed SSE payloads, one per line of
// the trace (design D5).
type EventType string

// Trace-event types emitted by the agent loop. Every event type in the
// chunk-10 chat-API contract is represented here.
const (
	// EventText carries assistant text tokens (commentary or the final
	// answer).
	EventText EventType = "text"
	// EventToolCall carries the tool name and arguments the model
	// requested.
	EventToolCall EventType = "tool_call"
	// EventToolResult carries a tool's result, truncated for the trace
	// (the full result is still fed back to the model).
	EventToolResult EventType = "tool_result"
	// EventScriptRun carries one run_python execution: source, stdout,
	// stderr, exit code, and sandbox id.
	EventScriptRun EventType = "script_run"
	// EventProvenance carries grounding provenance: data locators, citing
	// documents, dataset DOIs, and the ontology version used.
	EventProvenance EventType = "provenance"
	// EventDone marks the end of a turn, successful or not.
	EventDone EventType = "done"
	// EventError carries a turn-ending error (e.g. an LLM call failure or
	// the max-iterations guard tripping).
	EventError EventType = "error"
)

// Event is one entry in a turn's trace. Exactly one of the optional
// fields is populated, matching Type; the rest are zero-valued and
// omitted from JSON.
type Event struct {
	Type       EventType        `json:"type"`
	Text       string           `json:"text,omitempty"`
	ToolCall   *ToolCallEvent   `json:"tool_call,omitempty"`
	ToolResult *ToolResultEvent `json:"tool_result,omitempty"`
	ScriptRun  *ScriptRunEvent  `json:"script_run,omitempty"`
	Provenance *ProvenanceEvent `json:"provenance,omitempty"`
	Error      string           `json:"error,omitempty"`
}

// ToolCallEvent is the payload of an EventToolCall: the tool name and
// its raw JSON argument string as requested by the model.
type ToolCallEvent struct {
	ID        string `json:"id"`
	Name      string `json:"name"`
	Arguments string `json:"arguments"`
}

// ToolResultEvent is the payload of an EventToolResult. Content may be
// truncated relative to what was fed back to the model as the tool
// message; Truncated reports whether that happened.
type ToolResultEvent struct {
	Name      string `json:"name"`
	Content   string `json:"content"`
	Truncated bool   `json:"truncated"`
}

// ScriptRunEvent is the payload of an EventScriptRun: one run_python
// execution against the chunk-3 sandbox pool. Stdout/Stderr may be
// truncated for the trace; Truncated reports whether that happened.
type ScriptRunEvent struct {
	Source    string `json:"source"`
	Stdout    string `json:"stdout"`
	Stderr    string `json:"stderr"`
	ExitCode  int    `json:"exit_code"`
	SandboxID string `json:"sandbox_id"`
	Truncated bool   `json:"truncated"`
}

// ProvenanceEvent is the payload of an EventProvenance: grounding
// provenance surfaced alongside an answer. OntologyVersion is filled in
// by the loop from the request's OntologyVersion when a tool leaves it
// empty (see Agent.Run).
type ProvenanceEvent struct {
	DataLocators    []string `json:"data_locators"`
	CitedIn         []string `json:"cited_in"`
	DatasetDOIs     []string `json:"dataset_dois"`
	OntologyVersion string   `json:"ontology_version"`
}

// Emitter receives trace events as the loop and tools produce them. It
// is a plain function type rather than an interface so a channel send,
// an SSE writer, or a test's append-to-slice can all be passed
// directly.
type Emitter func(Event)
