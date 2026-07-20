package main

// SSE chat-handler acceptance tests for the OpenSpec change
// grounded-analysis-agent (chunk 4, task 6.6). Every scenario drives the
// REAL newChatHandler (cmd/server/chat.go) over a REAL agent.Agent and
// REAL tool constructors (agent.NewSPARQLTool, agent.NewSQLTool,
// agent.NewPythonTool), wired to a scripted stub LLMClient and fake
// GraphSelector/Sandbox backends via httptest -- no network, no Docker,
// no live model (design D6). It pins the chat-api spec's contract
// (openspec/changes/grounded-analysis-agent/specs/chat-api/spec.md):
//
//   - the endpoint is stateless and accepts a full conversation body;
//   - a malformed body is rejected before any turn starts;
//   - every trace event type is emitted and well-formed across a
//     grounded turn (SPARQL -> SQL -> script -> answer);
//   - script_run carries source/stdout/stderr/exit_code/sandbox_id;
//   - provenance carries data_locators and a non-empty ontology_version
//     stamped from the prompt cache; cited_in/dataset_dois are empty in
//     this fixture (ground-demo-in-real-docs D7: no fabricated citedIn/
//     DOI -- document traceability instead comes from the grounded
//     msr:Mention's msr:inDocument surfaced in the sparql_query result);
//   - nothing is written to a store while serving a chat request.
//
// Helper names are prefixed sse* (or otherwise distinct) to avoid
// redeclaration against chat_test.go's stubLLM/fakeSchemaSource -- this
// file lives in the same package main.

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/blogem/msr-graph/internal/agent"
	"github.com/blogem/msr-graph/internal/graph"
	"github.com/blogem/msr-graph/internal/store"
)

// --- fakes/stubs (unique names within package main) ---

// sseScriptedLLM is a scripted agent.LLMClient: it returns a fixed
// sequence of Completions, one per call, repeating the last one past the
// end of the script.
type sseScriptedLLM struct {
	completions []agent.Completion
	calls       int
}

func (s *sseScriptedLLM) Complete(_ context.Context, _ string, _ []agent.Message, _ []agent.ToolSpec) (agent.Completion, error) {
	idx := s.calls
	s.calls++
	if idx >= len(s.completions) {
		idx = len(s.completions) - 1
	}
	return s.completions[idx], nil
}

// sseFakeSelector is a fake agent.GraphSelector: it returns the same
// scripted *graph.Results for any query, so the sparql_query tool's
// grounding call comes back deterministic.
type sseFakeSelector struct {
	results *graph.Results
}

func (f *sseFakeSelector) Select(_ context.Context, _ string) (*graph.Results, error) {
	return f.results, nil
}

// sseFakeSandbox is a fake agent.Sandbox: it returns a fixed
// stdout/stderr/exitCode for every run_python call, recording call count.
type sseFakeSandbox struct {
	stdout   string
	stderr   string
	exitCode int
	calls    int
}

func (f *sseFakeSandbox) Run(_ context.Context, _ []byte) (stdout, stderr []byte, exitCode int, err error) {
	f.calls++
	return []byte(f.stdout), []byte(f.stderr), f.exitCode, nil
}

// sseFakeSchemaSource is a fake agent.SchemaSource for the PromptCache:
// it answers the owl:versionInfo detection query with a fixed version
// and every other schema query with an empty result set, which is
// enough for PromptCache.Get/BuildSchemaPrompt to succeed without
// contacting a live GraphDB.
type sseFakeSchemaSource struct {
	version string
}

func (s sseFakeSchemaSource) Select(_ context.Context, query string) (*graph.Results, error) {
	res := &graph.Results{}
	if strings.Contains(query, "versionInfo") {
		res.Head.Vars = []string{"version"}
		res.Results.Bindings = []map[string]graph.Binding{
			{"version": {Type: "literal", Value: s.version}},
		}
	}
	return res, nil
}

// sseOpenSeededStore opens a temp-file SQLite measurement store (the real
// internal/store backend, not a database/sql mock) and inserts one
// measurement_value row for locator, returning the open *sql.DB (which
// satisfies agent.SQLQuerier as-is) plus the file path so tests can
// snapshot it.
func sseOpenSeededStore(t *testing.T, locator string) (*sql.DB, string) {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "measurements.db")

	db, err := store.Open(path)
	if err != nil {
		t.Fatalf("store.Open: %v", err)
	}
	t.Cleanup(func() { db.Close() })

	ctx := context.Background()
	if err := store.Init(ctx, db); err != nil {
		t.Fatalf("store.Init: %v", err)
	}

	const insertSQL = `INSERT INTO measurement_value
		(locator, salt, property, c0, c1, t_min, t_max, equation_form, source)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
	if _, err := db.ExecContext(ctx, insertSQL,
		locator, "BeF2-LiF|34.0-66.0", "density", 2.413, -4.88e-4, 800.0, 1080.0, "Linear", "nist",
	); err != nil {
		t.Fatalf("seeding measurement_value row: %v", err)
	}

	return db, path
}

// --- SSE frame parsing ---

// sseFrame is one parsed "event: <type>\ndata: <json>\n\n" frame.
type sseFrame struct {
	event string
	data  []byte
}

// parseSSEFrames splits an SSE response body into individual frames on
// the blank-line frame separator (matching cmd/server/sse.go's
// newSSEEmitter framing) and extracts the "event:"/"data:" lines of
// each. It fails the test if a non-empty frame is missing a data line.
func parseSSEFrames(t *testing.T, body string) []sseFrame {
	t.Helper()
	body = strings.TrimRight(body, "\n")
	if strings.TrimSpace(body) == "" {
		return nil
	}

	raw := strings.Split(body, "\n\n")
	frames := make([]sseFrame, 0, len(raw))
	for _, chunk := range raw {
		if strings.TrimSpace(chunk) == "" {
			continue
		}
		var f sseFrame
		for _, line := range strings.Split(chunk, "\n") {
			switch {
			case strings.HasPrefix(line, "event: "):
				f.event = strings.TrimPrefix(line, "event: ")
			case strings.HasPrefix(line, "data: "):
				f.data = []byte(strings.TrimPrefix(line, "data: "))
			}
		}
		if f.data == nil {
			t.Fatalf("SSE frame missing a data line: %q", chunk)
		}
		frames = append(frames, f)
	}
	return frames
}

// parseSSEEvents parses body into agent.Event values, verifying each
// frame's "event:" field agrees with its JSON payload's "type" field
// (an SSE well-formedness check beyond mere JSON validity).
func parseSSEEvents(t *testing.T, body string) []agent.Event {
	t.Helper()
	frames := parseSSEFrames(t, body)
	events := make([]agent.Event, 0, len(frames))
	for _, f := range frames {
		var e agent.Event
		if err := json.Unmarshal(f.data, &e); err != nil {
			t.Fatalf("decoding SSE frame data %q: %v", f.data, err)
		}
		if string(e.Type) != f.event {
			t.Fatalf("SSE frame event field %q does not match payload type %q", f.event, e.Type)
		}
		events = append(events, e)
	}
	return events
}

// eventTypesOfSSE extracts each event's Type, for concise failure
// messages.
func eventTypesOfSSE(events []agent.Event) []agent.EventType {
	out := make([]agent.EventType, len(events))
	for i, e := range events {
		out[i] = e.Type
	}
	return out
}

// --- shared setup ---

const (
	sseTestLocator = "nist-srd27/density#BeF2-LiF|34.0-66.0"
	sseTestVersion = "sse-test-v1"
	sseChatBody    = `{"messages": [{"role": "user", "content": "What is the density of FLiBe at 900 K?"}]}`
)

// newSSEMinimalSetup builds a handler over a single-completion stub (a
// final answer, no tool calls) and no tools -- enough to exercise the
// stateless-request and malformed-body scenarios without needing a
// grounded, multi-tool turn.
func newSSEMinimalSetup(t *testing.T) (http.Handler, *sseScriptedLLM) {
	t.Helper()
	llm := &sseScriptedLLM{completions: []agent.Completion{
		{Content: "hello from the stub model"},
	}}
	ag := agent.New(llm, nil, agent.DefaultConfig())
	pc := agent.NewPromptCache(sseFakeSchemaSource{version: sseTestVersion})
	return newChatHandler(ag, pc), llm
}

// newSSEFullTurnSetup wires a scripted turn that exercises all three
// tools in order -- sparql_query (grounding via a real msr:Mention's
// surfaceForm -> msr:linksTo -> salt, with msr:inDocument as the
// document-traceability evidence and dataLocator bound so a provenance
// event fires; ground-demo-in-real-docs D2/D3 -- no skos:closeMatch,
// no fabricated citedIn/doi), sql_query (a real temp SQLite measurement
// store), and run_python (a fake sandbox) -- then a final text answer.
// It returns the assembled handler, the store's file path (for the
// no-persistence check), and the fake sandbox (for call-count
// assertions).
func newSSEFullTurnSetup(t *testing.T) (http.Handler, string, *sseFakeSandbox) {
	t.Helper()

	grounding := &graph.Results{}
	grounding.Head.Vars = []string{"salt", "mention", "surfaceForm", "inDocument", "dataLocator", "validTempMin", "validTempMax"}
	grounding.Results.Bindings = []map[string]graph.Binding{
		{
			"salt":         {Type: "uri", Value: "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"},
			"mention":      {Type: "uri", Value: "https://w3id.org/msr-kg/data#mention-ORNL-TM-2316-225-260"},
			"surfaceForm":  {Type: "literal", Value: "LiF-BeF, (66-34 mole %)"},
			"inDocument":   {Type: "uri", Value: "https://w3id.org/msr-kg/data#ORNL-TM-2316"},
			"dataLocator":  {Type: "literal", Value: sseTestLocator},
			"validTempMin": {Type: "literal", Value: "800"},
			"validTempMax": {Type: "literal", Value: "1080"},
		},
	}
	sel := &sseFakeSelector{results: grounding}

	db, dbPath := sseOpenSeededStore(t, sseTestLocator)

	sb := &sseFakeSandbox{stdout: `{"density_g_cm3": 1.9738}`, exitCode: 0}

	llm := &sseScriptedLLM{completions: []agent.Completion{
		{ToolCalls: []agent.ToolCall{{ID: "1", Name: "sparql_query", Arguments: `{"query":"SELECT ?salt ?mention ?surfaceForm ?inDocument ?dataLocator ?validTempMin ?validTempMax WHERE {}"}`}}},
		{ToolCalls: []agent.ToolCall{{ID: "2", Name: "sql_query", Arguments: `{"query":"SELECT c0, c1, t_min, t_max FROM measurement_value WHERE locator = '` + sseTestLocator + `'"}`}}},
		{ToolCalls: []agent.ToolCall{{ID: "3", Name: "run_python", Arguments: `{"script":"import json; print(json.dumps({'density_g_cm3': 2.413 + -4.88e-4*900}))"}`}}},
		{Content: "The density of FLiBe (LiF-BeF2, 34.0-66.0 mol%) at 900 K is approximately 1.974 g/cm3 (dataLocator " + sseTestLocator + ")."},
	}}

	tools := []agent.Tool{
		agent.NewSPARQLTool(sel),
		agent.NewSQLTool(db),
		agent.NewPythonTool(sb),
	}

	ag := agent.New(llm, tools, agent.DefaultConfig())
	pc := agent.NewPromptCache(sseFakeSchemaSource{version: sseTestVersion})
	handler := newChatHandler(ag, pc)
	return handler, dbPath, sb
}

// --- 1: stateless shape accepted ---

func TestSSE_StatelessShapeAccepted(t *testing.T) {
	handler, llm := newSSEMinimalSetup(t)

	req := httptest.NewRequest(http.MethodPost, "/api/chat", strings.NewReader(sseChatBody))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d; body: %s", rec.Code, http.StatusOK, rec.Body.String())
	}
	if ct := rec.Header().Get("Content-Type"); ct != "text/event-stream" {
		t.Errorf("Content-Type = %q, want %q", ct, "text/event-stream")
	}
	if llm.calls == 0 {
		t.Error("llm.calls = 0, want at least 1 (a turn should have started from the request body alone)")
	}

	events := parseSSEEvents(t, rec.Body.String())
	if len(events) == 0 {
		t.Fatal("expected at least one SSE event, got none")
	}
	if last := events[len(events)-1]; last.Type != agent.EventDone {
		t.Errorf("last event.Type = %q, want terminating %q", last.Type, agent.EventDone)
	}
}

// --- 2: malformed body rejected ---

func TestSSE_MalformedBodyRejected(t *testing.T) {
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
			handler, llm := newSSEMinimalSetup(t)

			req := httptest.NewRequest(http.MethodPost, "/api/chat", strings.NewReader(tt.body))
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)

			if rec.Code < 400 || rec.Code >= 500 {
				t.Fatalf("status = %d, want 4xx; body: %s", rec.Code, rec.Body.String())
			}
			if ct := rec.Header().Get("Content-Type"); ct == "text/event-stream" {
				t.Errorf("Content-Type = %q, a malformed request must not start an SSE stream", ct)
			}
			if strings.Contains(rec.Body.String(), "data: ") {
				t.Errorf("body contains an SSE data frame for a malformed request, want none: %s", rec.Body.String())
			}
			if llm.calls != 0 {
				t.Errorf("llm.calls = %d, want 0 (no turn should start for a malformed body)", llm.calls)
			}
		})
	}
}

// --- 3: every event type emitted and well-formed ---

func TestSSE_AllEventTypesEmittedAndWellFormed(t *testing.T) {
	handler, _, _ := newSSEFullTurnSetup(t)

	req := httptest.NewRequest(http.MethodPost, "/api/chat", strings.NewReader(sseChatBody))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d; body: %s", rec.Code, http.StatusOK, rec.Body.String())
	}

	events := parseSSEEvents(t, rec.Body.String())
	if len(events) == 0 {
		t.Fatal("expected SSE events, got none")
	}

	seen := map[agent.EventType]bool{
		agent.EventText:       false,
		agent.EventToolCall:   false,
		agent.EventToolResult: false,
		agent.EventScriptRun:  false,
		agent.EventProvenance: false,
		agent.EventDone:       false,
	}
	for _, e := range events {
		if _, tracked := seen[e.Type]; tracked {
			seen[e.Type] = true
		}
		switch e.Type {
		case agent.EventText:
			if e.Text == "" {
				t.Errorf("text event has an empty text field: %+v", e)
			}
		case agent.EventToolCall:
			if e.ToolCall == nil || e.ToolCall.Name == "" {
				t.Errorf("tool_call event missing a well-formed tool_call payload: %+v", e)
			}
		case agent.EventToolResult:
			if e.ToolResult == nil || e.ToolResult.Name == "" {
				t.Errorf("tool_result event missing a well-formed tool_result payload: %+v", e)
			}
		case agent.EventScriptRun:
			if e.ScriptRun == nil {
				t.Errorf("script_run event missing a well-formed script_run payload: %+v", e)
			}
		case agent.EventProvenance:
			if e.Provenance == nil {
				t.Errorf("provenance event missing a well-formed provenance payload: %+v", e)
			}
		case agent.EventDone, agent.EventError:
			// no required sub-payload
		default:
			t.Errorf("unexpected event type in stream: %q", e.Type)
		}
	}

	for et, wasSeen := range seen {
		if !wasSeen {
			t.Errorf("event type %q was never emitted across the turn, got sequence: %v", et, eventTypesOfSSE(events))
		}
	}

	if last := events[len(events)-1]; last.Type != agent.EventDone {
		t.Errorf("last event.Type = %q, want terminating %q", last.Type, agent.EventDone)
	}
}

// --- 4: script_run fields ---

func TestSSE_ScriptRunFields(t *testing.T) {
	handler, _, _ := newSSEFullTurnSetup(t)

	req := httptest.NewRequest(http.MethodPost, "/api/chat", strings.NewReader(sseChatBody))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	events := parseSSEEvents(t, rec.Body.String())

	var found *agent.ScriptRunEvent
	for _, e := range events {
		if e.Type == agent.EventScriptRun {
			found = e.ScriptRun
			break
		}
	}
	if found == nil {
		t.Fatalf("no script_run event in the stream: %v", eventTypesOfSSE(events))
	}

	if found.Source == "" {
		t.Error("script_run.source is empty, want the run_python script source")
	}
	if found.Stdout == "" {
		t.Error("script_run.stdout is empty, want the sandbox's stdout")
	}
	if found.SandboxID == "" {
		t.Error("script_run.sandbox_id is empty, want a non-empty per-run correlation id")
	}
	if found.ExitCode != 0 {
		t.Errorf("script_run.exit_code = %d, want 0 for this fixture's successful run", found.ExitCode)
	}
	// Stderr has no non-empty requirement, but it must be present in the
	// decoded payload (already implied by parseSSEEvents succeeding, since
	// json.Unmarshal into ScriptRunEvent requires a well-formed object).
	if found.Stderr != "" {
		t.Errorf("script_run.stderr = %q, want empty for this fixture's successful run", found.Stderr)
	}
}

// --- 5: provenance fields ---

func TestSSE_ProvenanceFields(t *testing.T) {
	handler, _, _ := newSSEFullTurnSetup(t)

	req := httptest.NewRequest(http.MethodPost, "/api/chat", strings.NewReader(sseChatBody))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	events := parseSSEEvents(t, rec.Body.String())

	var found *agent.ProvenanceEvent
	for _, e := range events {
		if e.Type == agent.EventProvenance {
			found = e.Provenance
			break
		}
	}
	if found == nil {
		t.Fatalf("no provenance event in the stream: %v", eventTypesOfSSE(events))
	}

	if len(found.DataLocators) != 1 || found.DataLocators[0] != sseTestLocator {
		t.Errorf("provenance.data_locators = %v, want [%q]", found.DataLocators, sseTestLocator)
	}
	// ground-demo-in-real-docs D7: no fabricated citedIn/DOI binding is
	// present in this fixture (they pointed at a fake doc-nist-srd27 +
	// fake DOI); the provenance event still fires off dataLocator alone,
	// and document traceability comes from the grounded mention's
	// inDocument surfaced in the sparql_query tool_result, not from a
	// citedIn/dataset_dois provenance field.
	if len(found.CitedIn) != 0 {
		t.Errorf("provenance.cited_in = %v, want empty (no fabricated citedIn binding in this fixture)", found.CitedIn)
	}
	if len(found.DatasetDOIs) != 0 {
		t.Errorf("provenance.dataset_dois = %v, want empty (no fabricated DOI binding in this fixture)", found.DatasetDOIs)
	}
	if found.OntologyVersion == "" {
		t.Error("provenance.ontology_version is empty, want it stamped from the prompt cache's detected version")
	}
	if found.OntologyVersion != sseTestVersion {
		t.Errorf("provenance.ontology_version = %q, want %q (the version this test's fake schema source detected)", found.OntologyVersion, sseTestVersion)
	}
}

// --- 5b: grounding traces to a real document via the mention ---

func TestSSE_GroundingSurfacesDocumentMention(t *testing.T) {
	// Spec "Grounding traces to a real document": the sparql_query
	// tool_result must surface the matched msr:Mention's msr:inDocument
	// and surfaceForm, so the grounding itself -- not just the
	// measurement -- is traceable to ORNL-TM-2316. No skos:closeMatch
	// binding may appear anywhere in the trace (ground-demo-in-real-docs
	// D2/D6).
	handler, _, _ := newSSEFullTurnSetup(t)

	req := httptest.NewRequest(http.MethodPost, "/api/chat", strings.NewReader(sseChatBody))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	events := parseSSEEvents(t, rec.Body.String())

	var sparqlResult *agent.ToolResultEvent
	for _, e := range events {
		if e.Type == agent.EventToolResult && e.ToolResult != nil && e.ToolResult.Name == "sparql_query" {
			sparqlResult = e.ToolResult
			break
		}
	}
	if sparqlResult == nil {
		t.Fatalf("no sparql_query tool_result in the stream: %v", eventTypesOfSSE(events))
	}

	if !strings.Contains(sparqlResult.Content, "https://w3id.org/msr-kg/data#ORNL-TM-2316") {
		t.Errorf("sparql_query tool_result = %q, want it to surface the grounded mention's inDocument (ORNL-TM-2316)", sparqlResult.Content)
	}
	if !strings.Contains(sparqlResult.Content, "LiF-BeF, (66-34 mole %)") {
		t.Errorf("sparql_query tool_result = %q, want it to surface the matched mention's surfaceForm", sparqlResult.Content)
	}

	for _, e := range events {
		var raw string
		switch {
		case e.Type == agent.EventToolResult && e.ToolResult != nil:
			raw = e.ToolResult.Content
		case e.Type == agent.EventToolCall && e.ToolCall != nil:
			raw = e.ToolCall.Arguments
		default:
			continue
		}
		if strings.Contains(strings.ToLower(raw), "closematch") {
			t.Errorf("event carried a skos:closeMatch reference, want none anywhere in the trace: %+v", e)
		}
	}
}

// --- 6: no trace persisted ---

func TestSSE_NoTracePersisted(t *testing.T) {
	handler, dbPath, sb := newSSEFullTurnSetup(t)

	before, err := os.ReadFile(dbPath)
	if err != nil {
		t.Fatalf("reading store db before the turn: %v", err)
	}
	beforeHash := sha256.Sum256(before)

	req := httptest.NewRequest(http.MethodPost, "/api/chat", strings.NewReader(sseChatBody))
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d; body: %s", rec.Code, http.StatusOK, rec.Body.String())
	}
	if sb.calls == 0 {
		t.Fatal("sandbox.calls = 0, want at least 1 (the scripted turn should have run_python)")
	}

	after, err := os.ReadFile(dbPath)
	if err != nil {
		t.Fatalf("reading store db after the turn: %v", err)
	}
	afterHash := sha256.Sum256(after)

	if beforeHash != afterHash {
		t.Errorf("the measurement store file changed after serving a chat request (before %d bytes, after %d bytes): "+
			"the server must not write to any store while serving a chat request", len(before), len(after))
	}
}
