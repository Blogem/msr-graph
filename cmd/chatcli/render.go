package main

import (
	"fmt"
	"io"
)

// renderEvent pretty-prints one trace event to w. Each event type gets
// a visually distinct rendering so a plain terminal reads clearly with
// no color required: assistant text streams inline, tool calls/results
// are arrowed, script_run shows source and stdout/stderr, provenance is
// rendered as a "chips" line, done marks the end of the turn, and
// errors are called out with a bang prefix.
func renderEvent(w io.Writer, ev Event) {
	switch ev.Type {
	case EventText:
		fmt.Fprint(w, ev.Text)

	case EventReasoning:
		fmt.Fprintf(w, "\n  [thinking] %s\n", ev.Reasoning)

	case EventToolCall:
		if tc := ev.ToolCall; tc != nil {
			fmt.Fprintf(w, "\n  -> %s(%s)\n", tc.Name, tc.Arguments)
		}

	case EventToolResult:
		if tr := ev.ToolResult; tr != nil {
			trunc := ""
			if tr.Truncated {
				trunc = " [truncated]"
			}
			fmt.Fprintf(w, "  <- %s result%s: %s\n", tr.Name, trunc, tr.Content)
		}

	case EventScriptRun:
		if sr := ev.ScriptRun; sr != nil {
			fmt.Fprintf(w, "\n  --- script_run (sandbox=%s exit=%d) ---\n", sr.SandboxID, sr.ExitCode)
			fmt.Fprintf(w, "  %s\n", sr.Source)
			fmt.Fprintf(w, "  stdout: %s\n", sr.Stdout)
			if sr.Stderr != "" {
				fmt.Fprintf(w, "  stderr: %s\n", sr.Stderr)
			}
			if sr.Truncated {
				fmt.Fprintln(w, "  [truncated]")
			}
		}

	case EventProvenance:
		if p := ev.Provenance; p != nil {
			fmt.Fprintf(w, "\n  [provenance] locators=%v cited_in=%v dataset_dois=%v ontology_version=%s\n",
				p.DataLocators, p.CitedIn, p.DatasetDOIs, p.OntologyVersion)
		}

	case EventDone:
		fmt.Fprintln(w, "\n--- end of turn ---")

	case EventError:
		fmt.Fprintf(w, "\n!! error: %s\n", ev.Error)

	default:
		fmt.Fprintf(w, "\n[unrecognized event type %q]\n", ev.Type)
	}
}
