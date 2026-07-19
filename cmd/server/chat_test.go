package main

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/blogem/msr-graph/internal/agent"
	"github.com/blogem/msr-graph/internal/graph"
)

// stubLLM is a minimal agent.LLMClient stub: it always returns the same
// scripted Completion (a final answer, no tool calls), so a turn ends
// immediately without exercising any tool. Every test in this file is
// offline: no test contacts a live model (mirrors internal/agent's own
// test strategy, design D6).
type stubLLM struct {
	completion agent.Completion
	calls      int
}

func (s *stubLLM) Complete(_ context.Context, _ string, _ []agent.Message, _ []agent.ToolSpec) (agent.Completion, error) {
	s.calls++
	return s.completion, nil
}

// fakeSchemaSource is a minimal agent.SchemaSource fake: it answers the
// version-detection query with a fixed owl:versionInfo binding and every
// other schema query (classes, properties, vocab, salts, constituents)
// with an empty result set, which is enough for PromptCache.Get to
// succeed without contacting a live GraphDB.
type fakeSchemaSource struct{}

func (fakeSchemaSource) Select(_ context.Context, query string) (*graph.Results, error) {
	res := &graph.Results{}
	if strings.Contains(query, "versionInfo") {
		res.Head.Vars = []string{"version"}
		res.Results.Bindings = []map[string]graph.Binding{
			{"version": {Type: "literal", Value: "v1"}},
		}
	}
	return res, nil
}

func TestChatHandler_GETNotAllowed(t *testing.T) {
	llm := &stubLLM{completion: agent.Completion{Content: "hi"}}
	ag := agent.New(llm, nil, agent.DefaultConfig())
	handler := newChatHandler(ag, agent.NewPromptCache(fakeSchemaSource{}))

	req := httptest.NewRequest(http.MethodGet, "/api/chat", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusMethodNotAllowed {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusMethodNotAllowed)
	}
	if got := rec.Header().Get("Allow"); got != http.MethodPost {
		t.Errorf("Allow header = %q, want %q", got, http.MethodPost)
	}
	if llm.calls != 0 {
		t.Errorf("llm.calls = %d, want 0 (no turn should start)", llm.calls)
	}
}

func TestChatHandler_MalformedBodyRejected(t *testing.T) {
	tests := []struct {
		name string
		body string
	}{
		{"invalid JSON", `not json`},
		{"missing messages", `{}`},
		{"empty messages", `{"messages": []}`},
		{"message missing role", `{"messages": [{"content": "hi"}]}`},
		{"message missing content", `{"messages": [{"role": "user"}]}`},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			llm := &stubLLM{completion: agent.Completion{Content: "hi"}}
			ag := agent.New(llm, nil, agent.DefaultConfig())
			handler := newChatHandler(ag, agent.NewPromptCache(fakeSchemaSource{}))

			req := httptest.NewRequest(http.MethodPost, "/api/chat", strings.NewReader(tt.body))
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)

			if rec.Code < 400 || rec.Code >= 500 {
				t.Fatalf("status = %d, want 4xx", rec.Code)
			}
			if llm.calls != 0 {
				t.Errorf("llm.calls = %d, want 0 (no turn should start)", llm.calls)
			}
		})
	}
}

func TestChatHandler_ValidRequestStreamsSSEEndingInDone(t *testing.T) {
	llm := &stubLLM{completion: agent.Completion{Content: "the answer is 42"}}
	ag := agent.New(llm, nil, agent.DefaultConfig())
	handler := newChatHandler(ag, agent.NewPromptCache(fakeSchemaSource{}))

	body := `{"messages": [{"role": "user", "content": "hello"}]}`
	req := httptest.NewRequest(http.MethodPost, "/api/chat", strings.NewReader(body))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}
	if ct := rec.Header().Get("Content-Type"); ct != "text/event-stream" {
		t.Errorf("Content-Type = %q, want %q", ct, "text/event-stream")
	}
	if llm.calls == 0 {
		t.Errorf("llm.calls = 0, want at least 1 (a turn should have started)")
	}

	got := rec.Body.String()
	if !strings.Contains(got, `"type":"text"`) {
		t.Errorf("stream missing text event, got: %s", got)
	}
	if !strings.HasSuffix(strings.TrimRight(got, "\n"), `data: {"type":"done"}`) {
		t.Errorf("stream did not end with a done event, got: %s", got)
	}
}
