package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

// Message is one turn in the conversation, mirroring the OpenAI-style
// shape POST /api/chat expects (see cmd/server/chat.go's chatRequest of
// the same shape, which decodes into agent.Message with identical JSON
// tags).
type Message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// chatRequest is the request body sent to POST /api/chat: the full
// conversation so far. The server holds no session state, so every
// request — including every REPL turn — carries the complete
// conversation (spec "Stateless POST /api/chat endpoint").
type chatRequest struct {
	Messages []Message `json:"messages"`
}

// runTurn POSTs messages as a chatRequest to url, streams the SSE trace
// response and renders each event to w as it arrives, and returns the
// concatenation of every EventText event's content — the assistant's
// turn, which the REPL folds back into history for the next request.
//
// A non-nil error is returned if the request fails to build or send, if
// the response status is not 2xx, if the SSE stream fails to parse, or
// if the trace ends in an EventError (the partial assistant text
// accumulated so far, if any, is still returned in that case).
func runTurn(client *http.Client, url string, messages []Message, w io.Writer) (string, error) {
	body, err := json.Marshal(chatRequest{Messages: messages})
	if err != nil {
		return "", fmt.Errorf("encode request body: %w", err)
	}

	req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return "", fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "text/event-stream")

	resp, err := client.Do(req)
	if err != nil {
		return "", fmt.Errorf("POST %s: %w", url, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		b, _ := io.ReadAll(resp.Body)
		return "", fmt.Errorf("POST %s: unexpected status %d: %s", url, resp.StatusCode, string(b))
	}

	var text bytes.Buffer
	var turnErr error
	parseErr := ParseSSE(resp.Body, func(ev Event) {
		renderEvent(w, ev)
		switch ev.Type {
		case EventText:
			text.WriteString(ev.Text)
		case EventError:
			turnErr = fmt.Errorf("agent error: %s", ev.Error)
		}
	})
	if parseErr != nil {
		return text.String(), fmt.Errorf("parse SSE stream: %w", parseErr)
	}
	return text.String(), turnErr
}
