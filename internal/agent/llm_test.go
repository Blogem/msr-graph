package agent_test

// Unit tests for the DeepSeek-backed LLMClient (task 1.1). These drive
// NewDeepSeekClient against an httptest.Server returning canned
// OpenAI-compatible /chat/completions responses; no test contacts a
// live DeepSeek endpoint (design D6).

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"testing"

	"github.com/blogem/msr-graph/internal/agent"
)

// wireRequest is the subset of the OpenAI /chat/completions request
// body this test asserts against; it is decoded independently of the
// package's unexported request type to keep the test black-box.
type wireRequest struct {
	Model    string `json:"model"`
	Messages []struct {
		Role    string `json:"role"`
		Content string `json:"content"`
	} `json:"messages"`
	Tools []struct {
		Type     string `json:"type"`
		Function struct {
			Name string `json:"name"`
		} `json:"function"`
	} `json:"tools"`
}

func TestDeepSeekClient_Complete(t *testing.T) {
	cases := []struct {
		name          string
		responseBody  string
		wantContent   string
		wantToolCalls []agent.ToolCall
	}{
		{
			name:         "plain final message",
			responseBody: `{"choices":[{"message":{"role":"assistant","content":"hello world"}}]}`,
			wantContent:  "hello world",
		},
		{
			name: "tool calls",
			responseBody: `{"choices":[{"message":{"role":"assistant","content":"",` +
				`"tool_calls":[{"id":"call_1","type":"function","function":` +
				`{"name":"sparql_query","arguments":"{\"mention\":\"FLiBe\"}"}}]}}]}`,
			wantToolCalls: []agent.ToolCall{
				{ID: "call_1", Name: "sparql_query", Arguments: `{"mention":"FLiBe"}`},
			},
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var gotAuth string
			var gotReq wireRequest

			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				gotAuth = r.Header.Get("Authorization")
				body, err := io.ReadAll(r.Body)
				if err != nil {
					t.Fatalf("read request body: %v", err)
				}
				if err := json.Unmarshal(body, &gotReq); err != nil {
					t.Fatalf("decode request body: %v", err)
				}
				w.Header().Set("Content-Type", "application/json")
				_, _ = w.Write([]byte(tc.responseBody))
			}))
			defer server.Close()

			cfg := agent.LLMConfig{
				BaseURL: server.URL,
				Model:   "deepseek-v4-pro",
				APIKey:  "secret-key",
			}
			client := agent.NewDeepSeekClient(cfg, nil)

			tools := []agent.ToolSpec{
				{
					Name:        "sparql_query",
					Description: "grounds a mention via the core dataset",
					Parameters:  json.RawMessage(`{"type":"object"}`),
				},
			}
			msgs := []agent.Message{{Role: "user", Content: "density of FLiBe at 900K"}}

			got, err := client.Complete(context.Background(), "system prompt", msgs, tools)
			if err != nil {
				t.Fatalf("Complete returned error: %v", err)
			}

			if gotAuth != "Bearer secret-key" {
				t.Errorf("Authorization header = %q, want %q", gotAuth, "Bearer secret-key")
			}
			if gotReq.Model != "deepseek-v4-pro" {
				t.Errorf("request model = %q, want %q", gotReq.Model, "deepseek-v4-pro")
			}
			if len(gotReq.Tools) != 1 || gotReq.Tools[0].Function.Name != "sparql_query" {
				t.Errorf("request tools = %+v, want one tool named sparql_query", gotReq.Tools)
			}
			if len(gotReq.Messages) == 0 || gotReq.Messages[0].Role != "system" {
				t.Errorf("request messages[0] = %+v, want a leading system message", gotReq.Messages)
			}

			if got.Content != tc.wantContent {
				t.Errorf("Completion.Content = %q, want %q", got.Content, tc.wantContent)
			}
			if len(got.ToolCalls) == 0 && len(tc.wantToolCalls) == 0 {
				return
			}
			if !reflect.DeepEqual(got.ToolCalls, tc.wantToolCalls) {
				t.Errorf("Completion.ToolCalls = %+v, want %+v", got.ToolCalls, tc.wantToolCalls)
			}
		})
	}
}

func TestNewDeepSeekClient_DefaultsModel(t *testing.T) {
	var gotReq wireRequest
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(body, &gotReq)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"choices":[{"message":{"role":"assistant","content":"ok"}}]}`))
	}))
	defer server.Close()

	client := agent.NewDeepSeekClient(agent.LLMConfig{BaseURL: server.URL}, nil)
	if _, err := client.Complete(context.Background(), "sys", nil, nil); err != nil {
		t.Fatalf("Complete returned error: %v", err)
	}
	if gotReq.Model != "deepseek-v4-pro" {
		t.Errorf("default model = %q, want %q", gotReq.Model, "deepseek-v4-pro")
	}
}
