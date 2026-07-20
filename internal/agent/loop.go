package agent

import (
	"context"
	"errors"
	"fmt"
	"strings"
)

// SystemInstructions is appended to every turn's system prompt (after
// the caller-supplied, schema-derived SystemPrompt). It encodes the
// behavioral invariants that are not implied by the schema alone: no
// model-side arithmetic, mandatory grounding before naming a salt or
// property, and refusing rather than extrapolating out-of-range
// temperatures (design D1, D3, D7; spec "All computation happens in
// sandbox scripts" and "Grounded temperature-range enforcement").
const SystemInstructions = `Rules for answering questions about molten-salt properties:

1. You MUST NOT compute any number yourself. Every numeric answer you
   report must be the stdout of a run_python script, reported verbatim
   (do not round, re-derive, or adjust it). If a question needs a
   computation, write and run the script before answering; do not
   answer with a number that did not come from a script's stdout.
2. Before naming a salt or a property in your answer, ground it with
   sparql_query: resolve the mention to a salt individual and its
   PropertyMeasurement, and fetch that measurement's coefficients from
   sql_query or run_python by its dataLocator. Do not answer from
   memory or guess an identifier.
3. Every measurement has a valid temperature range (validTempMin,
   validTempMax) returned by grounding. If the requested temperature
   falls outside that range, refuse or clearly flag the request as
   out-of-range instead of extrapolating and presenting a computed
   value as if it were a valid measurement.
4. When you answer, surface provenance: the dataLocator(s) used, any
   citedIn documents, and the dataset DOI, so the answer is traceable
   back to its source.`

// Agent runs the bounded tool-use loop described by design D1: it
// drives an injected LLMClient, offering it a fixed set of Tools, until
// the model returns a final answer with no further tool calls or the
// iteration bound trips.
type Agent struct {
	llm   LLMClient
	tools []Tool
	cfg   Config
}

// New builds an Agent over llm and tools, bounded by cfg.
func New(llm LLMClient, tools []Tool, cfg Config) *Agent {
	return &Agent{llm: llm, tools: tools, cfg: cfg}
}

// RunRequest is one turn's input: the caller-supplied system prompt
// (the cached KG-schema prompt from a later wave), the conversation so
// far, and the ontology version in effect for this request (used to
// stamp any ProvenanceEvent a tool leaves blank).
type RunRequest struct {
	SystemPrompt    string
	Messages        []Message
	OntologyVersion string
}

// errMaxIterations is returned by Run when the loop exhausts
// cfg.MaxIterations without the model producing a final answer.
var errMaxIterations = errors.New("agent: max iterations exceeded")

// truncateLimit and truncateMaxLines bound the Content/Stdout/Stderr
// text inlined into trace events (design D5): tool_result and
// script_run payloads are capped for the trace while the full result
// still reaches the model.
const (
	truncateLimit    = 4096
	truncateMaxLines = 50
)

// truncateForTrace caps s to at most truncateMaxLines lines and
// truncateLimit bytes, whichever triggers first, returning the
// (possibly shortened) text and whether it was shortened.
func truncateForTrace(s string) (string, bool) {
	truncated := false
	out := s

	lines := strings.SplitAfter(out, "\n")
	if len(lines) > truncateMaxLines {
		out = strings.Join(lines[:truncateMaxLines], "")
		truncated = true
	}

	if len(out) > truncateLimit {
		out = out[:truncateLimit]
		truncated = true
	}

	return out, truncated
}

// Run drives one turn to completion, emitting trace events via emit as
// it goes. It returns a non-nil error if the LLM call fails or the
// max-iterations guard trips; in both cases an EventError followed by
// an EventDone is emitted before returning, matching the chat API's
// event contract (every turn ends in a done event).
func (a *Agent) Run(ctx context.Context, req RunRequest, emit Emitter) error {
	system := req.SystemPrompt + "\n\n" + SystemInstructions

	if a.cfg.TurnDeadline > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, a.cfg.TurnDeadline)
		defer cancel()
	}

	// Per-turn grounding state, accumulated by wrappedEmit below and
	// consumed by the answer stamp (design D4) and the compute-time
	// locator linkage (design D5). anyProvenance/*Set track the union
	// of every ProvenanceEvent emitted this turn; surfacedLocators is
	// the subset (just the locator strings) retained for scanning each
	// run_python script's source (5.1).
	var anyProvenance bool
	locatorSet := map[string]bool{}
	citedSet := map[string]bool{}
	doiSet := map[string]bool{}
	surfacedLocators := map[string]bool{}

	// Wrap emit so it can (1) stamp any ProvenanceEvent a tool leaves
	// without an OntologyVersion from the request (design D4's
	// per-request version check feeds req.OntologyVersion; individual
	// tools don't need to know it), (2) fold that event's
	// locators/citedIn/DOIs into the turn's aggregates, and (3) when a
	// ScriptRunEvent passes through, scan its source for any locator
	// surfaced so far and attach the matched subset (design D5) before
	// forwarding. Order matters: a ProvenanceEvent must be folded in
	// before any later ScriptRunEvent is scanned, which holds here
	// because tools emit provenance from sparql_query before the model
	// can issue a run_python call that reads it.
	wrappedEmit := func(e Event) {
		if e.Type == EventProvenance && e.Provenance != nil {
			if e.Provenance.OntologyVersion == "" {
				e.Provenance.OntologyVersion = req.OntologyVersion
			}
			anyProvenance = true
			for _, l := range e.Provenance.DataLocators {
				locatorSet[l] = true
				surfacedLocators[l] = true
			}
			for _, c := range e.Provenance.CitedIn {
				citedSet[c] = true
			}
			for _, d := range e.Provenance.DatasetDOIs {
				doiSet[d] = true
			}
		}

		if e.Type == EventScriptRun && e.ScriptRun != nil {
			matched := map[string]bool{}
			for locator := range surfacedLocators {
				if strings.Contains(e.ScriptRun.Source, locator) {
					matched[locator] = true
					locatorSet[locator] = true
				}
			}
			if len(matched) > 0 {
				e.ScriptRun.DataLocators = sortedKeys(matched)
			}
		}

		emit(e)
	}

	toolByName := make(map[string]Tool, len(a.tools))
	specs := make([]ToolSpec, 0, len(a.tools))
	for _, t := range a.tools {
		spec := t.Spec()
		toolByName[spec.Name] = t
		specs = append(specs, spec)
	}

	msgs := make([]Message, len(req.Messages))
	copy(msgs, req.Messages)

	for i := 0; i < a.cfg.MaxIterations; i++ {
		completion, err := a.llm.Complete(ctx, system, msgs, specs)
		if err != nil {
			wrappedEmit(Event{Type: EventError, Error: err.Error()})
			wrappedEmit(Event{Type: EventDone})
			return fmt.Errorf("agent: llm completion failed: %w", err)
		}

		if completion.Content != "" {
			wrappedEmit(Event{Type: EventText, Text: completion.Content})
		}

		if len(completion.ToolCalls) == 0 {
			msgs = append(msgs, Message{Role: "assistant", Content: completion.Content})

			// The answer stamp is enforced here, in the loop, for every
			// final-answer turn -- independent of what the model asserted
			// in its text (design D4). An ungrounded turn (no
			// ProvenanceEvent seen) is stamped with Provenance left nil:
			// there is no chain to aggregate for a bare, unsourced
			// answer.
			answer := &AnswerEvent{Grounded: anyProvenance}
			if anyProvenance {
				answer.Provenance = &ProvenanceEvent{
					DataLocators:    sortedKeys(locatorSet),
					CitedIn:         sortedKeys(citedSet),
					DatasetDOIs:     sortedKeys(doiSet),
					OntologyVersion: req.OntologyVersion,
				}
			}
			wrappedEmit(Event{Type: EventAnswer, Answer: answer})

			wrappedEmit(Event{Type: EventDone})
			return nil
		}

		msgs = append(msgs, Message{
			Role:      "assistant",
			Content:   completion.Content,
			ToolCalls: completion.ToolCalls,
		})

		for _, tc := range completion.ToolCalls {
			wrappedEmit(Event{
				Type: EventToolCall,
				ToolCall: &ToolCallEvent{
					ID:        tc.ID,
					Name:      tc.Name,
					Arguments: tc.Arguments,
				},
			})

			var resultContent string
			tool, ok := toolByName[tc.Name]
			if !ok {
				resultContent = fmt.Sprintf("error: unknown tool %q", tc.Name)
			} else {
				result, callErr := tool.Call(ctx, tc.Arguments, wrappedEmit)
				if callErr != nil {
					// A tool error is not a crash: surface it as the
					// tool-result content so the model can react.
					resultContent = fmt.Sprintf("error: %s", callErr.Error())
				} else {
					resultContent = result
				}
			}

			traceContent, truncated := truncateForTrace(resultContent)
			wrappedEmit(Event{
				Type: EventToolResult,
				ToolResult: &ToolResultEvent{
					Name:      tc.Name,
					Content:   traceContent,
					Truncated: truncated,
				},
			})

			// The model always receives the full, untruncated result.
			msgs = append(msgs, Message{
				Role:       "tool",
				Content:    resultContent,
				ToolCallID: tc.ID,
			})
		}
	}

	wrappedEmit(Event{Type: EventError, Error: errMaxIterations.Error()})
	wrappedEmit(Event{Type: EventDone})
	return errMaxIterations
}
