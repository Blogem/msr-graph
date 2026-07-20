package agent

import "context"

// Tool is one capability the agent loop can offer the model. Later
// waves implement sparql_query, sql_query, and run_python against this
// interface (design D2); this package only defines the seam and drives
// it generically.
type Tool interface {
	// Spec returns the schema advertised to the model for this tool.
	Spec() ToolSpec

	// Call executes the tool with the model-supplied raw JSON argument
	// object and returns the result to feed back to the model as a
	// "tool" message. A tool error is not a crash: Call may return a
	// non-nil error, and the loop surfaces its message as the tool
	// result content so the model can react, rather than aborting the
	// turn.
	//
	// emit lets a tool report its own trace events as it runs (e.g.
	// run_python emits a ScriptRunEvent, sparql_query emits a
	// ProvenanceEvent); tools with nothing extra to report may ignore
	// it.
	Call(ctx context.Context, args string, emit Emitter) (result string, err error)
}
