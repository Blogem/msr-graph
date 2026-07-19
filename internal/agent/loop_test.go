package agent_test

// Unit tests for the bounded tool-use loop (tasks 1.3, 2.4, 6.1). Every
// test drives a stubbed LLMClient and fake Tools -- no test contacts a
// live model (design D6).

import (
	"context"
	"encoding/json"
	"errors"
	"testing"
	"time"

	"github.com/blogem/msr-graph/internal/agent"
)

// stubLLM returns a scripted sequence of Completions, one per call to
// Complete. If Complete is called more times than there are scripted
// completions, it repeats the last one -- this drives the
// max-iterations test, where the model never stops requesting tools.
type stubLLM struct {
	completions []agent.Completion
	calls       int
}

func (s *stubLLM) Complete(_ context.Context, _ string, _ []agent.Message, _ []agent.ToolSpec) (agent.Completion, error) {
	idx := s.calls
	s.calls++
	if idx >= len(s.completions) {
		idx = len(s.completions) - 1
	}
	return s.completions[idx], nil
}

// fakeTool is a minimal agent.Tool driven by a closure, so each test
// can script exactly the behavior (including emitting events) it
// needs.
type fakeTool struct {
	name string
	call func(ctx context.Context, args string, emit agent.Emitter) (string, error)
}

func (t *fakeTool) Spec() agent.ToolSpec {
	return agent.ToolSpec{
		Name:        t.name,
		Description: "fake tool for tests",
		Parameters:  json.RawMessage(`{"type":"object"}`),
	}
}

func (t *fakeTool) Call(ctx context.Context, args string, emit agent.Emitter) (string, error) {
	return t.call(ctx, args, emit)
}

// eventTypes extracts the Type of each event, for concise sequence
// assertions.
func eventTypes(events []agent.Event) []agent.EventType {
	out := make([]agent.EventType, len(events))
	for i, e := range events {
		out[i] = e.Type
	}
	return out
}

func TestRun_ExecutesToolCallsThenReturnsFinalAnswer(t *testing.T) {
	llm := &stubLLM{completions: []agent.Completion{
		{ToolCalls: []agent.ToolCall{{ID: "1", Name: "tool_a", Arguments: `{}`}}},
		{ToolCalls: []agent.ToolCall{{ID: "2", Name: "tool_b", Arguments: `{}`}}},
		{Content: "final answer 42"},
	}}

	var toolACalls, toolBCalls int
	toolA := &fakeTool{name: "tool_a", call: func(_ context.Context, _ string, _ agent.Emitter) (string, error) {
		toolACalls++
		return "result_a", nil
	}}
	toolB := &fakeTool{name: "tool_b", call: func(_ context.Context, _ string, _ agent.Emitter) (string, error) {
		toolBCalls++
		return "result_b", nil
	}}

	var events []agent.Event
	a := agent.New(llm, []agent.Tool{toolA, toolB}, agent.DefaultConfig())
	err := a.Run(context.Background(), agent.RunRequest{SystemPrompt: "sys"}, func(e agent.Event) {
		events = append(events, e)
	})
	if err != nil {
		t.Fatalf("Run returned error: %v", err)
	}
	if toolACalls != 1 || toolBCalls != 1 {
		t.Fatalf("expected each tool called once, got tool_a=%d tool_b=%d", toolACalls, toolBCalls)
	}

	wantTypes := []agent.EventType{
		agent.EventToolCall, agent.EventToolResult,
		agent.EventToolCall, agent.EventToolResult,
		agent.EventText, agent.EventDone,
	}
	gotTypes := eventTypes(events)
	if len(gotTypes) != len(wantTypes) {
		t.Fatalf("event sequence length = %d, want %d; got %v", len(gotTypes), len(wantTypes), gotTypes)
	}
	for i, want := range wantTypes {
		if gotTypes[i] != want {
			t.Errorf("event[%d].Type = %q, want %q (full sequence: %v)", i, gotTypes[i], want, gotTypes)
		}
	}

	// Tool calls executed in requested order, with the right names and
	// results reaching the trace.
	if events[0].ToolCall == nil || events[0].ToolCall.Name != "tool_a" {
		t.Errorf("event[0] tool_call.Name = %+v, want tool_a", events[0].ToolCall)
	}
	if events[1].ToolResult == nil || events[1].ToolResult.Content != "result_a" {
		t.Errorf("event[1] tool_result.Content = %+v, want result_a", events[1].ToolResult)
	}
	if events[2].ToolCall == nil || events[2].ToolCall.Name != "tool_b" {
		t.Errorf("event[2] tool_call.Name = %+v, want tool_b", events[2].ToolCall)
	}
	if events[3].ToolResult == nil || events[3].ToolResult.Content != "result_b" {
		t.Errorf("event[3] tool_result.Content = %+v, want result_b", events[3].ToolResult)
	}
	if events[4].Text != "final answer 42" {
		t.Errorf("event[4].Text = %q, want %q", events[4].Text, "final answer 42")
	}
}

func TestRun_MaxIterationsBoundsARunawayLoop(t *testing.T) {
	// The stub always requests a tool call and never produces a final
	// answer -- the loop must stop at cfg.MaxIterations rather than
	// looping unbounded.
	llm := &stubLLM{completions: []agent.Completion{
		{ToolCalls: []agent.ToolCall{{ID: "1", Name: "tool_a", Arguments: `{}`}}},
	}}

	var toolCalls int
	toolA := &fakeTool{name: "tool_a", call: func(_ context.Context, _ string, _ agent.Emitter) (string, error) {
		toolCalls++
		return "ok", nil
	}}

	cfg := agent.DefaultConfig()
	cfg.MaxIterations = 3

	var events []agent.Event
	a := agent.New(llm, []agent.Tool{toolA}, cfg)
	err := a.Run(context.Background(), agent.RunRequest{SystemPrompt: "sys"}, func(e agent.Event) {
		events = append(events, e)
	})

	if err == nil {
		t.Fatal("Run returned nil error, want a max-iterations error")
	}
	if llm.calls != cfg.MaxIterations {
		t.Errorf("llm.Complete called %d times, want exactly %d (the bound)", llm.calls, cfg.MaxIterations)
	}
	if toolCalls != cfg.MaxIterations {
		t.Errorf("tool called %d times, want exactly %d", toolCalls, cfg.MaxIterations)
	}

	if len(events) < 2 {
		t.Fatalf("expected at least an error+done tail, got %v", eventTypes(events))
	}
	lastTwo := events[len(events)-2:]
	if lastTwo[0].Type != agent.EventError {
		t.Errorf("second-to-last event.Type = %q, want %q", lastTwo[0].Type, agent.EventError)
	}
	if lastTwo[1].Type != agent.EventDone {
		t.Errorf("last event.Type = %q, want %q", lastTwo[1].Type, agent.EventDone)
	}
}

func TestRun_ScriptRunPrecedesNumericFinalAnswer(t *testing.T) {
	// Structural no-arithmetic property: when the final answer is
	// numeric, a script_run event carrying that number appears earlier
	// in the trace (design D6's "final == script output").
	llm := &stubLLM{completions: []agent.Completion{
		{ToolCalls: []agent.ToolCall{{ID: "1", Name: "run_python", Arguments: `{"script":"print(42)"}`}}},
		{Content: "42"},
	}}

	runPython := &fakeTool{name: "run_python", call: func(_ context.Context, _ string, emit agent.Emitter) (string, error) {
		emit(agent.Event{
			Type: agent.EventScriptRun,
			ScriptRun: &agent.ScriptRunEvent{
				Source:    "print(42)",
				Stdout:    "42",
				ExitCode:  0,
				SandboxID: "sandbox-1",
			},
		})
		return "42", nil
	}}

	var events []agent.Event
	a := agent.New(llm, []agent.Tool{runPython}, agent.DefaultConfig())
	err := a.Run(context.Background(), agent.RunRequest{SystemPrompt: "sys"}, func(e agent.Event) {
		events = append(events, e)
	})
	if err != nil {
		t.Fatalf("Run returned error: %v", err)
	}

	var scriptRunIdx, textIdx = -1, -1
	for i, e := range events {
		switch e.Type {
		case agent.EventScriptRun:
			scriptRunIdx = i
		case agent.EventText:
			textIdx = i
		}
	}
	if scriptRunIdx == -1 {
		t.Fatalf("no script_run event in trace: %v", eventTypes(events))
	}
	if textIdx == -1 {
		t.Fatalf("no text event in trace: %v", eventTypes(events))
	}
	if scriptRunIdx >= textIdx {
		t.Fatalf("script_run event (idx %d) did not precede the final text event (idx %d)", scriptRunIdx, textIdx)
	}
	if events[scriptRunIdx].ScriptRun.Stdout != "42" {
		t.Errorf("script_run.Stdout = %q, want %q", events[scriptRunIdx].ScriptRun.Stdout, "42")
	}
	if events[textIdx].Text != "42" {
		t.Errorf("final text = %q, want %q (must equal script output)", events[textIdx].Text, "42")
	}
}

func TestRun_StampsOntologyVersionOnBlankProvenance(t *testing.T) {
	llm := &stubLLM{completions: []agent.Completion{
		{ToolCalls: []agent.ToolCall{{ID: "1", Name: "sparql_query", Arguments: `{}`}}},
		{Content: "grounded"},
	}}

	sparql := &fakeTool{name: "sparql_query", call: func(_ context.Context, _ string, emit agent.Emitter) (string, error) {
		emit(agent.Event{
			Type: agent.EventProvenance,
			Provenance: &agent.ProvenanceEvent{
				DataLocators: []string{"nist-srd27/density#BeF2-LiF|34.0-66.0"},
			},
		})
		return "grounded result", nil
	}}

	var events []agent.Event
	a := agent.New(llm, []agent.Tool{sparql}, agent.DefaultConfig())
	req := agent.RunRequest{SystemPrompt: "sys", OntologyVersion: "v3"}
	err := a.Run(context.Background(), req, func(e agent.Event) {
		events = append(events, e)
	})
	if err != nil {
		t.Fatalf("Run returned error: %v", err)
	}

	var found bool
	for _, e := range events {
		if e.Type == agent.EventProvenance {
			found = true
			if e.Provenance.OntologyVersion != "v3" {
				t.Errorf("provenance.OntologyVersion = %q, want %q", e.Provenance.OntologyVersion, "v3")
			}
		}
	}
	if !found {
		t.Fatal("no provenance event in trace")
	}
}

func TestRun_UnknownToolFeedsBackAnError(t *testing.T) {
	llm := &stubLLM{completions: []agent.Completion{
		{ToolCalls: []agent.ToolCall{{ID: "1", Name: "does_not_exist", Arguments: `{}`}}},
		{Content: "handled"},
	}}

	var events []agent.Event
	a := agent.New(llm, nil, agent.DefaultConfig())
	err := a.Run(context.Background(), agent.RunRequest{SystemPrompt: "sys"}, func(e agent.Event) {
		events = append(events, e)
	})
	if err != nil {
		t.Fatalf("Run returned error: %v", err)
	}

	// The loop must not crash on an unknown tool; it feeds an error
	// result back and the model can still produce a final answer.
	var sawToolResult bool
	for _, e := range events {
		if e.Type == agent.EventToolResult {
			sawToolResult = true
		}
	}
	if !sawToolResult {
		t.Fatal("expected a tool_result event for the unknown tool call")
	}
}

func TestRun_AppliesTurnDeadline(t *testing.T) {
	// A slow stub that blocks past a very short deadline must cause Run
	// to return promptly rather than hang for the caller-supplied
	// context's lifetime.
	block := make(chan struct{})
	llm := &blockingLLM{block: block}

	cfg := agent.DefaultConfig()
	cfg.TurnDeadline = 10 * time.Millisecond

	a := agent.New(llm, nil, cfg)
	done := make(chan error, 1)
	go func() {
		done <- a.Run(context.Background(), agent.RunRequest{SystemPrompt: "sys"}, func(agent.Event) {})
	}()

	select {
	case err := <-done:
		if err == nil {
			t.Error("Run returned nil error after its context deadline should have elapsed")
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Run did not return within 2s of a 10ms turn deadline")
	}
	close(block)
}

// blockingLLM blocks until its context is done (or block is closed),
// so tests can assert that Run's context deadline is honored.
type blockingLLM struct {
	block chan struct{}
}

func (b *blockingLLM) Complete(ctx context.Context, _ string, _ []agent.Message, _ []agent.ToolSpec) (agent.Completion, error) {
	select {
	case <-ctx.Done():
		return agent.Completion{}, ctx.Err()
	case <-b.block:
		return agent.Completion{}, errors.New("unblocked without a deadline firing")
	}
}
