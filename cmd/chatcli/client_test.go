package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// TestRunTurn_SendsWellFormedRequestBody drives runTurn against an
// httptest.Server that returns a canned SSE stream, and asserts the
// request is a well-formed {"messages":[…]} POST with the expected
// headers, and that the rendered output and returned final text
// reflect the streamed "text" event.
func TestRunTurn_SendsWellFormedRequestBody(t *testing.T) {
	var gotBody chatRequest
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Errorf("method = %s, want POST", r.Method)
		}
		if ct := r.Header.Get("Content-Type"); ct != "application/json" {
			t.Errorf("Content-Type = %q, want application/json", ct)
		}
		if accept := r.Header.Get("Accept"); accept != "text/event-stream" {
			t.Errorf("Accept = %q, want text/event-stream", accept)
		}
		if err := json.NewDecoder(r.Body).Decode(&gotBody); err != nil {
			t.Fatalf("decode request body: %v", err)
		}

		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		fmt.Fprint(w, "event: text\ndata: {\"type\":\"text\",\"text\":\"hi there\"}\n\n")
		fmt.Fprint(w, "event: done\ndata: {\"type\":\"done\"}\n\n")
	}))
	defer srv.Close()

	var out strings.Builder
	text, err := runTurn(srv.Client(), srv.URL, []Message{{Role: "user", Content: "hello"}}, &out)
	if err != nil {
		t.Fatalf("runTurn error: %v", err)
	}
	if text != "hi there" {
		t.Errorf("final text = %q, want %q", text, "hi there")
	}
	if len(gotBody.Messages) != 1 || gotBody.Messages[0] != (Message{Role: "user", Content: "hello"}) {
		t.Errorf("request body messages = %+v, want [{user hello}]", gotBody.Messages)
	}
	if !strings.Contains(out.String(), "hi there") {
		t.Errorf("rendered output missing streamed text, got: %q", out.String())
	}
	if !strings.Contains(out.String(), "end of turn") {
		t.Errorf("rendered output missing done marker, got: %q", out.String())
	}
}

// TestRunTurn_NonOKStatusReturnsError asserts a non-2xx response from
// the server surfaces as an error rather than being parsed as an SSE
// stream.
func TestRunTurn_NonOKStatusReturnsError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "malformed request body: boom", http.StatusBadRequest)
	}))
	defer srv.Close()

	var out strings.Builder
	_, err := runTurn(srv.Client(), srv.URL, []Message{{Role: "user", Content: "hello"}}, &out)
	if err == nil {
		t.Fatal("runTurn error = nil, want non-nil for a 400 response")
	}
}

// TestRunREPL_ResendsFullHistoryOnSecondTurn asserts the REPL's
// stateless contract: the second turn's request body must contain the
// first turn's user line and the assistant's final text alongside the
// new user line, not just the new line by itself (spec "Stateless POST
// /api/chat endpoint").
func TestRunREPL_ResendsFullHistoryOnSecondTurn(t *testing.T) {
	var requests []chatRequest
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body chatRequest
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatalf("decode request body: %v", err)
		}
		requests = append(requests, body)

		answer := fmt.Sprintf("answer %d", len(requests))
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		data, err := json.Marshal(Event{Type: EventText, Text: answer})
		if err != nil {
			t.Fatalf("marshal event: %v", err)
		}
		fmt.Fprintf(w, "event: text\ndata: %s\n\n", data)
		fmt.Fprint(w, "event: done\ndata: {\"type\":\"done\"}\n\n")
	}))
	defer srv.Close()

	in := strings.NewReader("first question\nsecond question\nexit\n")
	var out strings.Builder
	runREPL(srv.Client(), srv.URL, in, &out)

	if len(requests) != 2 {
		t.Fatalf("got %d requests, want 2: %+v", len(requests), requests)
	}

	if want := []Message{{Role: "user", Content: "first question"}}; !messagesEqual(requests[0].Messages, want) {
		t.Errorf("turn 1 messages = %+v, want %+v", requests[0].Messages, want)
	}

	want := []Message{
		{Role: "user", Content: "first question"},
		{Role: "assistant", Content: "answer 1"},
		{Role: "user", Content: "second question"},
	}
	if !messagesEqual(requests[1].Messages, want) {
		t.Errorf("turn 2 messages = %+v, want %+v", requests[1].Messages, want)
	}
}

func messagesEqual(got, want []Message) bool {
	if len(got) != len(want) {
		return false
	}
	for i := range got {
		if got[i] != want[i] {
			return false
		}
	}
	return true
}
