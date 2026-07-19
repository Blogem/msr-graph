// Command chatcli is a manual-verification playground for the
// grounded-analysis agent (chunk 4 of the grounded-analysis-agent
// OpenSpec change): it POSTs a question to a running POST /api/chat,
// consumes the SSE trace it streams back, and pretty-prints each trace
// event to the terminal — a stand-in for chunk 10's UI.
//
// It knows only the documented wire format (a JSON request body of
// {"messages":[{"role","content"}, …]} and SSE frames of
// "event: <type>\ndata: <json>\n\n") and deliberately does not import
// internal/agent, so it stays a thin client of that contract rather
// than coupling to server internals.
//
// Usage:
//
//	go run ./cmd/chatcli                  # interactive REPL
//	go run ./cmd/chatcli -q "question"    # one-shot
//	go run ./cmd/chatcli -url http://host:8080/api/chat -q "..."
package main

import (
	"bufio"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
)

func main() {
	url := flag.String("url", "http://localhost:8080/api/chat", "base URL of the POST /api/chat endpoint")
	question := flag.String("q", "", "ask a single question and exit (one-shot mode); if empty, start an interactive REPL")
	flag.Parse()

	client := &http.Client{}

	if *question != "" {
		if _, err := runTurn(client, *url, []Message{{Role: "user", Content: *question}}, os.Stdout); err != nil {
			fmt.Fprintf(os.Stderr, "chatcli: %v\n", err)
			os.Exit(1)
		}
		return
	}

	runREPL(client, *url, os.Stdin, os.Stdout)
}

// runREPL reads user turns from in, one per line, and drives the
// stateless POST /api/chat contract exactly as chunk 10's UI will:
// every turn re-sends the full conversation so far, appending the
// previous turn's user line and the assistant's final text to an
// in-memory history rather than relying on server-side session state
// (spec "Stateless POST /api/chat endpoint"). "exit", "quit", or EOF
// (Ctrl-D) ends the session.
func runREPL(client *http.Client, url string, in io.Reader, out io.Writer) {
	fmt.Fprintln(out, "chatcli REPL - one question per line; 'exit' or 'quit' (or Ctrl-D) to leave.")

	var messages []Message
	scanner := bufio.NewScanner(in)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)

	for {
		fmt.Fprint(out, "> ")
		if !scanner.Scan() {
			fmt.Fprintln(out)
			return
		}

		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		if line == "exit" || line == "quit" {
			return
		}

		messages = append(messages, Message{Role: "user", Content: line})

		finalText, err := runTurn(client, url, messages, out)
		if err != nil {
			fmt.Fprintf(out, "chatcli: %v\n", err)
			continue
		}
		if finalText != "" {
			messages = append(messages, Message{Role: "assistant", Content: finalText})
		}
	}
}
