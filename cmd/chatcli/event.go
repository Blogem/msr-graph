package main

// EventType discriminates the payload of an Event. This mirrors
// internal/agent.EventType's JSON values exactly, but is defined locally
// so this CLI depends only on the documented wire format of POST
// /api/chat's SSE stream, not on server internals (see
// openspec/changes/grounded-analysis-agent/proposal.md and
// internal/agent/events.go for the authoritative contract this copies).
type EventType string

const (
	EventText       EventType = "text"
	EventReasoning  EventType = "reasoning"
	EventToolCall   EventType = "tool_call"
	EventToolResult EventType = "tool_result"
	EventScriptRun  EventType = "script_run"
	EventProvenance EventType = "provenance"
	EventDone       EventType = "done"
	EventError      EventType = "error"
)

// Event is one entry in a turn's trace, decoded from a single SSE
// frame's "data:" payload. Exactly one of the optional fields is
// populated, matching Type.
type Event struct {
	Type       EventType        `json:"type"`
	Text       string           `json:"text,omitempty"`
	Reasoning  string           `json:"reasoning,omitempty"`
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
// truncated relative to what was fed back to the model; Truncated
// reports whether that happened.
type ToolResultEvent struct {
	Name      string `json:"name"`
	Content   string `json:"content"`
	Truncated bool   `json:"truncated"`
}

// ScriptRunEvent is the payload of an EventScriptRun: one run_python
// execution. Stdout/Stderr may be truncated for the trace; Truncated
// reports whether that happened.
type ScriptRunEvent struct {
	Source    string `json:"source"`
	Stdout    string `json:"stdout"`
	Stderr    string `json:"stderr"`
	ExitCode  int    `json:"exit_code"`
	SandboxID string `json:"sandbox_id"`
	Truncated bool   `json:"truncated"`
}

// ProvenanceEvent is the payload of an EventProvenance: grounding
// provenance surfaced alongside an answer.
type ProvenanceEvent struct {
	DataLocators    []string `json:"data_locators"`
	CitedIn         []string `json:"cited_in"`
	DatasetDOIs     []string `json:"dataset_dois"`
	OntologyVersion string   `json:"ontology_version"`
}
