package main

import (
	"reflect"
	"strings"
	"testing"
)

// TestParseSSE_SequenceAcrossTypes builds a canned in-memory SSE byte
// stream covering every trace-event type, including a multi-line data
// field (per the SSE convention of joining consecutive "data:" lines
// with "\n" — exercised here via a pretty-printed, multi-line JSON
// payload) and a final event with no trailing blank line, and asserts
// ParseSSE decodes the exact sequence of events.
func TestParseSSE_SequenceAcrossTypes(t *testing.T) {
	var b strings.Builder

	// Comment line, should be ignored.
	b.WriteString(": keep-alive\n")

	// Single-line data.
	b.WriteString("event: text\n")
	b.WriteString(`data: {"type":"text","text":"hello"}` + "\n\n")

	// Multi-line data: a pretty-printed JSON payload split across
	// several "data:" lines, which must be rejoined with "\n" before
	// decoding (structural whitespace between JSON tokens is legal, so
	// the reconstructed multi-line text is still valid JSON).
	toolCallJSON := "{\n  \"type\": \"tool_call\",\n  \"tool_call\": {\n    \"id\": \"call-1\",\n    \"name\": \"sparql_query\",\n    \"arguments\": \"{}\"\n  }\n}"
	b.WriteString("event: tool_call\n")
	for _, line := range strings.Split(toolCallJSON, "\n") {
		b.WriteString("data: " + line + "\n")
	}
	b.WriteString("\n")

	b.WriteString("event: tool_result\n")
	b.WriteString(`data: {"type":"tool_result","tool_result":{"name":"sparql_query","content":"...rows...","truncated":true}}` + "\n\n")

	b.WriteString("event: script_run\n")
	b.WriteString(`data: {"type":"script_run","script_run":{"source":"print(1)","stdout":"1\n","stderr":"","exit_code":0,"sandbox_id":"sb-1","truncated":false}}` + "\n\n")

	b.WriteString("event: provenance\n")
	b.WriteString(`data: {"type":"provenance","provenance":{"data_locators":["loc-1"],"cited_in":["doc-1"],"dataset_dois":["doi-1"],"ontology_version":"v1"}}` + "\n\n")

	b.WriteString("event: error\n")
	b.WriteString(`data: {"type":"error","error":"boom"}` + "\n\n")

	// Final event with no trailing blank line: ParseSSE must still
	// flush it once the stream reaches EOF.
	b.WriteString("event: done\n")
	b.WriteString(`data: {"type":"done"}`)

	var got []Event
	err := ParseSSE(strings.NewReader(b.String()), func(ev Event) {
		got = append(got, ev)
	})
	if err != nil {
		t.Fatalf("ParseSSE error: %v", err)
	}

	want := []Event{
		{Type: EventText, Text: "hello"},
		{Type: EventToolCall, ToolCall: &ToolCallEvent{ID: "call-1", Name: "sparql_query", Arguments: "{}"}},
		{Type: EventToolResult, ToolResult: &ToolResultEvent{Name: "sparql_query", Content: "...rows...", Truncated: true}},
		{Type: EventScriptRun, ScriptRun: &ScriptRunEvent{Source: "print(1)", Stdout: "1\n", ExitCode: 0, SandboxID: "sb-1"}},
		{Type: EventProvenance, Provenance: &ProvenanceEvent{DataLocators: []string{"loc-1"}, CitedIn: []string{"doc-1"}, DatasetDOIs: []string{"doi-1"}, OntologyVersion: "v1"}},
		{Type: EventError, Error: "boom"},
		{Type: EventDone},
	}

	if len(got) != len(want) {
		t.Fatalf("got %d events, want %d: %+v", len(got), len(want), got)
	}
	for i := range want {
		if !reflect.DeepEqual(got[i], want[i]) {
			t.Errorf("event[%d] = %+v, want %+v", i, got[i], want[i])
		}
	}
}

// TestParseSSE_IgnoresBlankRecordsAndUnknownFields asserts that a blank
// line with no preceding data does not synthesize a spurious event, and
// that an "id:"/"retry:" field is tolerated without affecting decoding.
func TestParseSSE_IgnoresBlankRecordsAndUnknownFields(t *testing.T) {
	stream := "\n\nid: 1\nretry: 1000\nevent: done\ndata: {\"type\":\"done\"}\n\n\n"

	var got []Event
	err := ParseSSE(strings.NewReader(stream), func(ev Event) {
		got = append(got, ev)
	})
	if err != nil {
		t.Fatalf("ParseSSE error: %v", err)
	}
	if len(got) != 1 {
		t.Fatalf("got %d events, want 1: %+v", len(got), got)
	}
	if got[0].Type != EventDone {
		t.Errorf("event type = %q, want %q", got[0].Type, EventDone)
	}
}

// TestParseSSE_MalformedDataReturnsError asserts a data payload that
// isn't valid JSON surfaces a decode error rather than being silently
// dropped or panicking.
func TestParseSSE_MalformedDataReturnsError(t *testing.T) {
	stream := "event: text\ndata: not json\n\n"

	err := ParseSSE(strings.NewReader(stream), func(Event) {
		t.Error("handle should not be called for malformed data")
	})
	if err == nil {
		t.Fatal("ParseSSE error = nil, want non-nil")
	}
}
