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
	// EventReasoning carries the model's chain-of-thought, surfaced
	// separately from the answer so it never pollutes the answer text and
	// is never fed back into the conversation (see splitReasoning).
	EventReasoning EventType = "reasoning"
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
	// EventAnswer carries the turn's groundedness verdict -- grounded
	// iff at least one ProvenanceEvent was emitted this turn -- and the
	// aggregated provenance chain. The loop emits exactly one of these
	// per final-answer turn, immediately before EventDone (design D4);
	// it is enforced in the loop itself, independent of the model.
	EventAnswer EventType = "answer"
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
	Reasoning  string           `json:"reasoning,omitempty"`
	ToolCall   *ToolCallEvent   `json:"tool_call,omitempty"`
	ToolResult *ToolResultEvent `json:"tool_result,omitempty"`
	ScriptRun  *ScriptRunEvent  `json:"script_run,omitempty"`
	Provenance *ProvenanceEvent `json:"provenance,omitempty"`
	Answer     *AnswerEvent     `json:"answer,omitempty"`
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
// DataLocators is filled in by the loop (design D5), not by the tool:
// it is the set of grounded dataLocator values (surfaced by
// sparql_query earlier in the same turn) whose string appears in
// Source, so a computed number can be tied back to the rows it read
// without the model self-reporting them.
type ScriptRunEvent struct {
	Source       string   `json:"source"`
	Stdout       string   `json:"stdout"`
	Stderr       string   `json:"stderr"`
	ExitCode     int      `json:"exit_code"`
	SandboxID    string   `json:"sandbox_id"`
	Truncated    bool     `json:"truncated"`
	DataLocators []string `json:"data_locators,omitempty"`
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

// AnswerEvent is the payload of an EventAnswer: the loop's per-turn
// groundedness verdict, emitted once per final answer immediately
// before EventDone (design D4). Grounded is true iff at least one
// ProvenanceEvent was emitted during the turn; Provenance then carries
// the aggregated union of every such event's locators/citedIn/DOIs
// plus the request's OntologyVersion. When the turn is ungrounded,
// Provenance is left nil -- a bare, unsourced answer carries no
// provenance chain to aggregate.
type AnswerEvent struct {
	Grounded   bool             `json:"grounded"`
	Provenance *ProvenanceEvent `json:"provenance,omitempty"`
}

// Emitter receives trace events as the loop and tools produce them. It
// is a plain function type rather than an interface so a channel send,
// an SSE writer, or a test's append-to-slice can all be passed
// directly.
type Emitter func(Event)
