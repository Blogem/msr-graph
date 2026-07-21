// Package agent implements the grounded analysis agent: a bounded
// tool-use loop that drives an injected, OpenAI-compatible LLM client
// against three read-only tools (sparql_query, sql_query, run_python).
// The model orchestrates which tool to call and with what arguments; it
// never performs computation itself -- every numeric answer must be the
// verbatim output of a run_python script (design D1, D6 in
// openspec/changes/grounded-analysis-agent).
package agent

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// defaultLLMTimeout bounds requests made by the default HTTP client used
// when NewDeepSeekClient is called with a nil httpClient.
const defaultLLMTimeout = 60 * time.Second

// defaultModel is the DeepSeek model id used when LLMConfig.Model is
// empty. It is config-overridable (LLM_MODEL_ANALYSIS); no code contract
// depends on the literal id (design Open Questions).
const defaultModel = "deepseek-v4-pro"

// Message is one turn in the conversation sent to and received from the
// LLM client. It mirrors the OpenAI chat-completions message shape: a
// "user" or "system" message carries only Content; an "assistant"
// message may additionally carry ToolCalls it requested; a "tool"
// message carries the result of one prior tool call, keyed back to it
// by ToolCallID.
type Message struct {
	Role       string     `json:"role"` // "user" | "assistant" | "tool"
	Content    string     `json:"content"`
	ToolCalls  []ToolCall `json:"tool_calls,omitempty"`
	ToolCallID string     `json:"tool_call_id,omitempty"`
}

// ToolCall is one tool invocation requested by the model on an
// assistant turn. Arguments is the raw JSON object string the model
// produced for the tool's parameters -- it is passed through verbatim
// to the tool rather than re-encoded, so the tool sees exactly what the
// model emitted.
type ToolCall struct {
	ID        string
	Name      string
	Arguments string
}

// ToolSpec is the schema advertised to the model for one tool: its name,
// a natural-language description (which, for run_python, must state the
// runtime contract -- see internal/agent/tools.go), and a JSON Schema
// describing its arguments.
type ToolSpec struct {
	Name        string
	Description string
	Parameters  json.RawMessage // JSON Schema for the tool arguments
}

// Completion is one assistant turn returned by the LLM: either final
// text content, one or more requested tool calls, or both (a model may
// emit commentary alongside tool calls). Reasoning holds the model's
// chain-of-thought when present -- separated out of Content so it is
// never shown as, or fed back as, the answer (see splitReasoning and the
// deepSeekClient.Complete reasoning handling).
type Completion struct {
	Content   string
	Reasoning string
	ToolCalls []ToolCall
}

// LLMClient is the injected seam over the language model. Production
// code talks to DeepSeek via NewDeepSeekClient; every test in this
// package drives a stub implementation instead, so no test ever
// contacts a live model (design D6).
type LLMClient interface {
	// Complete sends the system prompt, the conversation so far, and the
	// tool schemas available this turn, and returns the model's next
	// assistant turn.
	Complete(ctx context.Context, system string, msgs []Message, tools []ToolSpec) (Completion, error)
}

// LLMConfig configures the DeepSeek-backed LLMClient.
type LLMConfig struct {
	// BaseURL is the DeepSeek (or OpenAI-compatible) API base, e.g.
	// "https://api.deepseek.com". DEEPSEEK_BASE_URL at the server layer.
	BaseURL string
	// Model is the model id sent as the "model" field. Defaults to
	// "deepseek-v4-pro" (LLM_MODEL_ANALYSIS) when empty.
	Model string
	// APIKey is sent as an "Authorization: Bearer <APIKey>" header.
	APIKey string
}

// deepSeekClient is a hand-rolled, non-streaming OpenAI-compatible
// /chat/completions client. No OpenAI SDK is vendored; requests and
// responses are built with encoding/json against the wire shapes below.
type deepSeekClient struct {
	cfg        LLMConfig
	httpClient *http.Client
}

// NewDeepSeekClient builds an LLMClient that POSTs to
// "<cfg.BaseURL>/chat/completions". httpClient may be nil, in which case
// a client with a sane default timeout is used; tests inject a client
// with a custom Transport (or point BaseURL at an httptest.Server) for
// dependency injection.
func NewDeepSeekClient(cfg LLMConfig, httpClient *http.Client) LLMClient {
	if cfg.Model == "" {
		cfg.Model = defaultModel
	}
	if httpClient == nil {
		httpClient = &http.Client{Timeout: defaultLLMTimeout}
	}
	return &deepSeekClient{cfg: cfg, httpClient: httpClient}
}

// --- OpenAI-compatible wire shapes (request/response) ---

// oaFunction is the "function" object nested under an OpenAI "tool".
type oaFunction struct {
	Name        string          `json:"name"`
	Description string          `json:"description,omitempty"`
	Parameters  json.RawMessage `json:"parameters,omitempty"`
}

// oaTool is one entry in the request's "tools" array.
type oaTool struct {
	Type     string     `json:"type"` // always "function"
	Function oaFunction `json:"function"`
}

// oaToolCallFunction carries the requested function name and its raw
// JSON-encoded arguments.
type oaToolCallFunction struct {
	Name      string `json:"name"`
	Arguments string `json:"arguments"`
}

// oaToolCall is one tool call as encoded on an OpenAI assistant message.
type oaToolCall struct {
	ID       string             `json:"id"`
	Type     string             `json:"type"` // always "function"
	Function oaToolCallFunction `json:"function"`
}

// oaMessage is one message in the request/response "messages" arrays.
// ReasoningContent is response-only: DeepSeek reasoning models return
// chain-of-thought in this dedicated field alongside Content. It is never
// sent on a request (DeepSeek rejects it as input), so it stays
// omitempty and toOAMessage never sets it.
type oaMessage struct {
	Role             string       `json:"role"`
	Content          string       `json:"content,omitempty"`
	ReasoningContent string       `json:"reasoning_content,omitempty"`
	ToolCalls        []oaToolCall `json:"tool_calls,omitempty"`
	ToolCallID       string       `json:"tool_call_id,omitempty"`
}

// oaRequest is the /chat/completions request body.
type oaRequest struct {
	Model    string      `json:"model"`
	Messages []oaMessage `json:"messages"`
	Tools    []oaTool    `json:"tools,omitempty"`
}

// oaChoice is one entry in the response's "choices" array. Only the
// first choice is used (non-streaming, n=1 usage).
type oaChoice struct {
	Message oaMessage `json:"message"`
}

// oaResponse is the /chat/completions response body.
type oaResponse struct {
	Choices []oaChoice `json:"choices"`
	Error   *oaError   `json:"error,omitempty"`
}

// oaError is the OpenAI-compatible error envelope returned in place of
// (or alongside) choices on failure.
type oaError struct {
	Message string `json:"message"`
}

// toOAMessage translates one internal Message to the OpenAI wire shape.
func toOAMessage(m Message) oaMessage {
	out := oaMessage{
		Role:       m.Role,
		Content:    m.Content,
		ToolCallID: m.ToolCallID,
	}
	for _, tc := range m.ToolCalls {
		out.ToolCalls = append(out.ToolCalls, oaToolCall{
			ID:   tc.ID,
			Type: "function",
			Function: oaToolCallFunction{
				Name:      tc.Name,
				Arguments: tc.Arguments,
			},
		})
	}
	return out
}

// toOATool translates one ToolSpec to the OpenAI "tools" entry shape.
func toOATool(t ToolSpec) oaTool {
	return oaTool{
		Type: "function",
		Function: oaFunction{
			Name:        t.Name,
			Description: t.Description,
			Parameters:  t.Parameters,
		},
	}
}

// Complete implements LLMClient by POSTing a non-streaming
// /chat/completions request and parsing the first choice into a
// Completion.
func (c *deepSeekClient) Complete(ctx context.Context, system string, msgs []Message, tools []ToolSpec) (Completion, error) {
	req := oaRequest{Model: c.cfg.Model}
	req.Messages = append(req.Messages, oaMessage{Role: "system", Content: system})
	for _, m := range msgs {
		req.Messages = append(req.Messages, toOAMessage(m))
	}
	for _, t := range tools {
		req.Tools = append(req.Tools, toOATool(t))
	}

	body, err := json.Marshal(req)
	if err != nil {
		return Completion{}, fmt.Errorf("agent: encode deepseek request: %w", err)
	}

	url := c.cfg.BaseURL + "/chat/completions"
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return Completion{}, fmt.Errorf("agent: build deepseek request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Authorization", "Bearer "+c.cfg.APIKey)

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return Completion{}, fmt.Errorf("agent: deepseek request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return Completion{}, fmt.Errorf("agent: read deepseek response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return Completion{}, fmt.Errorf("agent: deepseek returned status %d: %s", resp.StatusCode, string(respBody))
	}

	var oaResp oaResponse
	if err := json.Unmarshal(respBody, &oaResp); err != nil {
		return Completion{}, fmt.Errorf("agent: decode deepseek response: %w", err)
	}
	if oaResp.Error != nil {
		return Completion{}, fmt.Errorf("agent: deepseek error: %s", oaResp.Error.Message)
	}
	if len(oaResp.Choices) == 0 {
		return Completion{}, fmt.Errorf("agent: deepseek response had no choices")
	}

	choice := oaResp.Choices[0].Message

	// Separate any chain-of-thought from the answer. Two channels may
	// carry it: inline <think>...</think> blocks embedded in Content, and
	// DeepSeek's dedicated reasoning_content field. Strip the inline
	// blocks out of the answer, then fold the dedicated field in, so
	// Content is reasoning-free and Reasoning holds whatever was present.
	cleanContent, inlineReasoning := splitReasoning(choice.Content)
	out := Completion{Content: cleanContent, Reasoning: inlineReasoning}
	if rc := strings.TrimSpace(choice.ReasoningContent); rc != "" {
		if out.Reasoning != "" {
			out.Reasoning += "\n\n" + rc
		} else {
			out.Reasoning = rc
		}
	}
	for _, tc := range choice.ToolCalls {
		out.ToolCalls = append(out.ToolCalls, ToolCall{
			ID:        tc.ID,
			Name:      tc.Function.Name,
			Arguments: tc.Function.Arguments,
		})
	}
	return out, nil
}
