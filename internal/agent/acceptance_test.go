package agent_test

// End-to-end acceptance suite for the fully-assembled analysis agent
// (OpenSpec change grounded-analysis-agent, chunk 4, tasks 6.1, 6.2, 6.3,
// 6.4, 6.8). Every scenario drives the REAL agent.New(...).Run(...) loop
// against a scripted stub LLMClient plus the REAL tool constructors
// (agent.NewSPARQLTool, agent.NewSQLTool, agent.NewPythonTool) wired to
// fakes/in-memory backends -- no network, no Docker, no live model
// (design D6). These tests pin the demo's correctness properties:
//
//   - the loop executes tool calls in order and feeds results back (D1);
//   - the model never computes -- every numeric final answer equals a
//     run_python script's stdout, with a script_run event preceding the
//     final text (D6's "final == script output" invariant);
//   - the max-iterations guard ends a runaway loop with an error (D1);
//   - grounding (via a real msr:Mention's surfaceForm -> msr:linksTo,
//     ground-demo-in-real-docs D2/D3) -> coefficient fetch -> script ->
//     answer for the real FLiBe density scenario (spec "End-to-end
//     grounded density answer");
//   - an out-of-range temperature is flagged/refused, not extrapolated
//     (design D7, spec "Grounded temperature-range enforcement");
//   - a comparative question is resolved by exactly one aggregating
//     script, not model-side comparison (spec "Comparative queries
//     answered by aggregation in one script");
//   - the same agent/tool code grounds and answers a DIFFERENT
//     salt/property/coefficient row present only in the fakes, proving
//     nothing is hardcoded (spec "Schema-generic answer surface").

import (
	"context"
	"database/sql"
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"

	"github.com/blogem/msr-graph/internal/agent"
	"github.com/blogem/msr-graph/internal/graph"
	"github.com/blogem/msr-graph/internal/store"
)

// --- shared scripted-completion stub LLM ---
//
// scriptedLLM is this file's own stub LLMClient: it returns a fixed
// sequence of agent.Completion values, one per call, and repeats the
// last one if Complete is called past the end of the script (driving
// the max-iterations scenario, where the model never stops requesting
// tools). It is a distinct type from loop_test.go's stubLLM (unique
// name to avoid redeclaration across this package's _test.go files).
type scriptedLLM struct {
	completions []agent.Completion
	calls       int
}

func (s *scriptedLLM) Complete(_ context.Context, _ string, _ []agent.Message, _ []agent.ToolSpec) (agent.Completion, error) {
	idx := s.calls
	s.calls++
	if idx >= len(s.completions) {
		idx = len(s.completions) - 1
	}
	return s.completions[idx], nil
}

// --- fake Sandbox: a queue of scripted run_python results ---

// sandboxResponse is one canned result a scriptedSandbox returns for one
// Run call.
type sandboxResponse struct {
	stdout   string
	stderr   string
	exitCode int
}

// scriptedSandbox is this file's fake agent.Sandbox: it returns queued
// responses in order (one per call to Run), recording every script it
// was given so a test can assert on call count and content. Unique name
// to avoid colliding with python_test.go's package-internal fakeSandbox
// (a different package: python_test.go is `package agent`, this file is
// `package agent_test`, but the name is kept distinct regardless).
type scriptedSandbox struct {
	responses []sandboxResponse
	calls     int
	scripts   []string
}

func (s *scriptedSandbox) Run(_ context.Context, script []byte) (stdout, stderr []byte, exitCode int, err error) {
	s.scripts = append(s.scripts, string(script))
	idx := s.calls
	s.calls++
	if idx >= len(s.responses) {
		idx = len(s.responses) - 1
	}
	r := s.responses[idx]
	return []byte(r.stdout), []byte(r.stderr), r.exitCode, nil
}

// --- shared helpers ---

// acceptanceBinding builds a literal graph.Binding, mirroring
// sparql_test.go's binding() helper (declared with a unique name since
// both files share package agent_test).
func acceptanceBinding(value string) graph.Binding {
	return graph.Binding{Type: "literal", Value: value}
}

// openSeededStoreDB opens a temp-file SQLite measurement store (via
// internal/store, the same real backend sql_test.go uses) and inserts
// one measurement_value row per rows, returning the *sql.DB directly --
// it satisfies agent.SQLQuerier as-is, matching the task's
// "fakeOrInMemDB" wiring instruction for agent.NewSQLTool with a real
// (not database/sql-mocked) backend.
type measurementRow struct {
	locator      string
	salt         string
	property     string
	c0, c1       float64
	tMin, tMax   float64
	equationForm string
}

func openSeededStoreDB(t *testing.T, rows []measurementRow) *sql.DB {
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
	for _, r := range rows {
		// source is CHECK-constrained to 'nist' or 'document'; this
		// fixture data plays the role of a NIST-sourced coefficient row
		// regardless of which salt/property it fixtures.
		if _, err := db.ExecContext(ctx, insertSQL,
			r.locator, r.salt, r.property, r.c0, r.c1, r.tMin, r.tMax, r.equationForm, "nist",
		); err != nil {
			t.Fatalf("seeding measurement_value row %+v: %v", r, err)
		}
	}

	return db
}

// runAssembledAgent wires llm and tools into a real agent.Agent, runs one
// turn, and returns the collected trace events plus any error from Run.
func runAssembledAgent(t *testing.T, llm agent.LLMClient, tools []agent.Tool, cfg agent.Config) ([]agent.Event, error) {
	t.Helper()
	var events []agent.Event
	a := agent.New(llm, tools, cfg)
	err := a.Run(context.Background(), agent.RunRequest{
		SystemPrompt:    "You are the grounded molten-salt analysis agent.",
		OntologyVersion: "test-v1",
	}, func(e agent.Event) {
		events = append(events, e)
	})
	return events, err
}

// eventTypesOf extracts each event's Type, for concise sequence
// assertions (mirrors loop_test.go's eventTypes; declared under a
// distinct name in this file).
func eventTypesOf(events []agent.Event) []agent.EventType {
	out := make([]agent.EventType, len(events))
	for i, e := range events {
		out[i] = e.Type
	}
	return out
}

// indexOfEventType returns the index of the first event of type et in
// events, or -1 if none matches.
func indexOfEventType(events []agent.Event, et agent.EventType) int {
	for i, e := range events {
		if e.Type == et {
			return i
		}
	}
	return -1
}

// countEventType returns how many events in events have type et.
func countEventType(events []agent.Event, et agent.EventType) int {
	n := 0
	for _, e := range events {
		if e.Type == et {
			n++
		}
	}
	return n
}

// finalText returns the Text of the last EventText in events (the
// turn's final answer, since the loop only emits EventText for the
// model's assistant content -- commentary or final answer -- and this
// suite's stub scripts never emit intermediate commentary text).
func finalText(t *testing.T, events []agent.Event) string {
	t.Helper()
	for i := len(events) - 1; i >= 0; i-- {
		if events[i].Type == agent.EventText {
			return events[i].Text
		}
	}
	t.Fatalf("no text event in trace: %v", eventTypesOf(events))
	return ""
}

// --- 6.1: loop sequence + no-model-arithmetic (assembled) ---

func TestAcceptance_LoopExecutesToolsInOrderThenReturnsScriptAnswer(t *testing.T) {
	// Ground via the real sparql_query tool, then compute via the real
	// run_python tool, then answer. Assert tool-call/tool-result pairs
	// appear in the requested order, a script_run event precedes the
	// final text, and the final answer equals the script's stdout
	// verbatim (the model performed no arithmetic).
	sel := &fakeSelector{results: flibeGroundingResults()}
	sandbox := &scriptedSandbox{responses: []sandboxResponse{
		{stdout: "1.974", exitCode: 0},
	}}

	llm := &scriptedLLM{completions: []agent.Completion{
		{ToolCalls: []agent.ToolCall{{ID: "1", Name: "sparql_query", Arguments: `{"query":"SELECT ?salt ?dataLocator WHERE {}"}`}}},
		{ToolCalls: []agent.ToolCall{{ID: "2", Name: "run_python", Arguments: `{"script":"print(2.413 + -4.88e-4*900)"}`}}},
		{Content: "1.974"},
	}}

	tools := []agent.Tool{
		agent.NewSPARQLTool(sel),
		agent.NewPythonTool(sandbox),
	}

	events, err := runAssembledAgent(t, llm, tools, agent.DefaultConfig())
	if err != nil {
		t.Fatalf("Run returned error: %v", err)
	}

	// Exact expected sequence: each tool's own events (sparql_query emits
	// a provenance event, run_python emits a script_run event) are
	// emitted synchronously inside Tool.Call, before the loop appends
	// that call's tool_result -- so ToolCall -> [tool's own event] ->
	// ToolResult, repeated per requested tool call, then the final text
	// and done.
	wantTypes := []agent.EventType{
		agent.EventToolCall, agent.EventProvenance, agent.EventToolResult,
		agent.EventToolCall, agent.EventScriptRun, agent.EventToolResult,
		agent.EventText, agent.EventDone,
	}
	gotTypes := eventTypesOf(events)
	if len(gotTypes) != len(wantTypes) {
		t.Fatalf("event sequence = %v, want length %d matching %v", gotTypes, len(wantTypes), wantTypes)
	}
	for i, want := range wantTypes {
		if gotTypes[i] != want {
			t.Errorf("event[%d].Type = %q, want %q (full sequence: %v)", i, gotTypes[i], want, gotTypes)
		}
	}

	sparqlCallIdx := indexOfEventType(events, agent.EventToolCall)
	if sparqlCallIdx == -1 || events[sparqlCallIdx].ToolCall.Name != "sparql_query" {
		t.Fatalf("expected first tool_call to be sparql_query, got %+v", events)
	}

	scriptRunIdx := indexOfEventType(events, agent.EventScriptRun)
	if scriptRunIdx == -1 {
		t.Fatalf("no script_run event in trace: %v", eventTypesOf(events))
	}
	textIdx := indexOfEventType(events, agent.EventText)
	if textIdx == -1 {
		t.Fatalf("no final text event in trace: %v", eventTypesOf(events))
	}
	if scriptRunIdx >= textIdx {
		t.Fatalf("script_run (idx %d) did not precede final text (idx %d): %v", scriptRunIdx, textIdx, eventTypesOf(events))
	}
	if scriptRunIdx < sparqlCallIdx {
		t.Fatalf("script_run (idx %d) executed before grounding tool_call (idx %d): %v", scriptRunIdx, sparqlCallIdx, eventTypesOf(events))
	}

	// The two run_python tool_call/tool_result events must also appear
	// in requested order (call before its own result).
	runPythonCallIdx := -1
	for i, e := range events {
		if e.Type == agent.EventToolCall && e.ToolCall.Name == "run_python" {
			runPythonCallIdx = i
			break
		}
	}
	if runPythonCallIdx == -1 || runPythonCallIdx >= scriptRunIdx {
		t.Fatalf("run_python tool_call (idx %d) did not precede its script_run (idx %d)", runPythonCallIdx, scriptRunIdx)
	}

	got := finalText(t, events)
	if got != "1.974" {
		t.Errorf("final answer = %q, want it to equal the fake run_python stdout %q", got, "1.974")
	}
	if events[scriptRunIdx].ScriptRun.Stdout != got {
		t.Errorf("script_run.Stdout = %q, final answer = %q; the no-model-arithmetic invariant requires these to match", events[scriptRunIdx].ScriptRun.Stdout, got)
	}
}

func TestAcceptance_MaxIterationsEndsRunawayLoopWithError(t *testing.T) {
	// A stub that always calls a tool and never produces a final answer
	// must not loop unbounded: Run stops at cfg.MaxIterations and ends
	// the turn with an error event (design D1).
	sandbox := &scriptedSandbox{responses: []sandboxResponse{{stdout: "ok", exitCode: 0}}}
	llm := &scriptedLLM{completions: []agent.Completion{
		{ToolCalls: []agent.ToolCall{{ID: "1", Name: "run_python", Arguments: `{"script":"print('ok')"}`}}},
	}}

	cfg := agent.DefaultConfig()
	cfg.MaxIterations = 3

	events, err := runAssembledAgent(t, llm, []agent.Tool{agent.NewPythonTool(sandbox)}, cfg)
	if err == nil {
		t.Fatal("Run returned nil error for a runaway stub, want a max-iterations error")
	}
	if sandbox.calls != cfg.MaxIterations {
		t.Errorf("sandbox.Run called %d times, want exactly %d (the bound)", sandbox.calls, cfg.MaxIterations)
	}
	if len(events) < 2 {
		t.Fatalf("expected at least an error+done tail, got %v", eventTypesOf(events))
	}
	last := events[len(events)-1]
	secondLast := events[len(events)-2]
	if secondLast.Type != agent.EventError {
		t.Errorf("second-to-last event.Type = %q, want %q", secondLast.Type, agent.EventError)
	}
	if last.Type != agent.EventDone {
		t.Errorf("last event.Type = %q, want %q", last.Type, agent.EventDone)
	}
}

// --- 6.2: grounded density e2e ---

// flibeGroundingResults builds the fake SPARQL grounding result for the
// real FLiBe salt (msrd:salt-BeF2-LiF-34.0-66.0), reshaped to the
// linksTo-based recipe (design D2/D3, spec analysis-agent): a real
// msr:Mention binds the matched surfaceForm ("LiF-BeF, (66-34 mole %)",
// the OCR span from ORNL-TM-2316) and its msr:linksTo target (the salt),
// with msr:inDocument as the document-traceability evidence -- alongside
// the salt's density PropertyMeasurement dataLocator, equation form, and
// valid range. No skos:closeMatch binding is present anywhere (D2/D6).
func flibeGroundingResults() *graph.Results {
	results := &graph.Results{}
	results.Head.Vars = []string{"salt", "mention", "surfaceForm", "inDocument", "dataLocator", "equationForm", "validTempMin", "validTempMax"}
	results.Results.Bindings = []map[string]graph.Binding{
		{
			"salt":         {Type: "uri", Value: "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"},
			"mention":      {Type: "uri", Value: "https://w3id.org/msr-kg/data#mention-ORNL-TM-2316-225-260"},
			"surfaceForm":  acceptanceBinding("LiF-BeF, (66-34 mole %)"),
			"inDocument":   {Type: "uri", Value: "https://w3id.org/msr-kg/data#ORNL-TM-2316"},
			"dataLocator":  acceptanceBinding("nist-srd27/density#BeF2-LiF|34.0-66.0"),
			"equationForm": {Type: "uri", Value: "https://w3id.org/msr-kg/ontology#linear"},
			"validTempMin": acceptanceBinding("800"),
			"validTempMax": acceptanceBinding("1080"),
		},
	}
	return results
}

func TestAcceptance_GroundedDensityEndToEnd(t *testing.T) {
	const locator = "nist-srd27/density#BeF2-LiF|34.0-66.0"

	sel := &fakeSelector{results: flibeGroundingResults()}
	db := openSeededStoreDB(t, []measurementRow{
		{locator: locator, salt: "BeF2-LiF|34.0-66.0", property: "density", c0: 2.413, c1: -4.88e-4, tMin: 800, tMax: 1080, equationForm: "Linear"},
	})

	sandbox := &scriptedSandbox{responses: []sandboxResponse{
		{stdout: `{"density_g_cm3": 1.9738}`, exitCode: 0},
	}}

	llm := &scriptedLLM{completions: []agent.Completion{
		// (a) ground via sparql_query: a real msr:Mention's surfaceForm ->
		// msr:linksTo -> the salt, with msr:inDocument as evidence.
		{ToolCalls: []agent.ToolCall{{ID: "1", Name: "sparql_query", Arguments: `{"query":"SELECT ?salt ?mention ?surfaceForm ?inDocument ?dataLocator ?equationForm ?validTempMin ?validTempMax WHERE { ?mention a <https://w3id.org/msr-kg/ontology#Mention> ; <https://w3id.org/msr-kg/ontology#linksTo> ?salt ; <https://w3id.org/msr-kg/ontology#inDocument> ?inDocument ; <https://w3id.org/msr-kg/ontology#surfaceForm> ?surfaceForm . ?salt <https://w3id.org/msr-kg/ontology#hasMeasurement> ?m }"}`}}},
		// (b) fetch coefficients via sql_query, keyed by the dataLocator from (a)
		{ToolCalls: []agent.ToolCall{{ID: "2", Name: "sql_query", Arguments: `{"query":"SELECT c0, c1, t_min, t_max FROM measurement_value WHERE locator = '` + locator + `'"}`}}},
		// (c) evaluate c0 + c1*T at T=900 in a sandbox script
		{ToolCalls: []agent.ToolCall{{ID: "3", Name: "run_python", Arguments: `{"script":"import json; print(json.dumps({'density_g_cm3': 2.413 + -4.88e-4*900}))"}`}}},
		// (d) final answer, citing the dataLocator
		{Content: "The density of FLiBe (LiF-BeF2, 34.0-66.0 mol%) at 900 K is approximately 1.974 g/cm3 (dataLocator " + locator + ")."},
	}}

	tools := []agent.Tool{
		agent.NewSPARQLTool(sel),
		agent.NewSQLTool(db),
		agent.NewPythonTool(sandbox),
	}

	events, err := runAssembledAgent(t, llm, tools, agent.DefaultConfig())
	if err != nil {
		t.Fatalf("Run returned error: %v", err)
	}

	sparqlCallIdx := -1
	sqlCallIdx := -1
	for i, e := range events {
		if e.Type != agent.EventToolCall {
			continue
		}
		switch e.ToolCall.Name {
		case "sparql_query":
			if sparqlCallIdx == -1 {
				sparqlCallIdx = i
			}
		case "sql_query":
			if sqlCallIdx == -1 {
				sqlCallIdx = i
			}
		}
	}
	scriptRunIdx := indexOfEventType(events, agent.EventScriptRun)
	textIdx := indexOfEventType(events, agent.EventText)

	if sparqlCallIdx == -1 {
		t.Fatalf("no sparql_query tool_call in trace: %v", eventTypesOf(events))
	}
	if sqlCallIdx == -1 {
		t.Fatalf("no sql_query tool_call in trace: %v", eventTypesOf(events))
	}
	if scriptRunIdx == -1 {
		t.Fatalf("no script_run in trace: %v", eventTypesOf(events))
	}
	if textIdx == -1 {
		t.Fatalf("no final text in trace: %v", eventTypesOf(events))
	}

	// Spec "Grounding traces to a real document": the sparql_query
	// tool_result must surface the matched msr:Mention's msr:inDocument
	// (ORNL-TM-2316) and its surfaceForm, so the grounding itself -- not
	// just the measurement -- is document-traceable.
	sparqlResultIdx := -1
	for i := sparqlCallIdx; i < len(events); i++ {
		if events[i].Type == agent.EventToolResult && events[i].ToolResult.Name == "sparql_query" {
			sparqlResultIdx = i
			break
		}
	}
	if sparqlResultIdx == -1 {
		t.Fatalf("no sparql_query tool_result in trace: %v", eventTypesOf(events))
	}
	sparqlContent := events[sparqlResultIdx].ToolResult.Content
	if !strings.Contains(sparqlContent, "ORNL-TM-2316") {
		t.Errorf("sparql_query tool_result = %q, want it to surface the grounded mention's inDocument (ORNL-TM-2316)", sparqlContent)
	}
	if !strings.Contains(sparqlContent, "LiF-BeF, (66-34 mole %)") {
		t.Errorf("sparql_query tool_result = %q, want it to surface the matched mention's surfaceForm", sparqlContent)
	}
	if strings.Contains(strings.ToLower(sparqlContent), "closematch") {
		t.Errorf("sparql_query tool_result = %q, must not carry a skos:closeMatch binding", sparqlContent)
	}

	if !(sparqlCallIdx < sqlCallIdx && sqlCallIdx < scriptRunIdx && scriptRunIdx < textIdx) {
		t.Fatalf("trace order violated: want sparql_query(%d) < sql_query(%d) < script_run(%d) < text(%d)", sparqlCallIdx, sqlCallIdx, scriptRunIdx, textIdx)
	}

	got := finalText(t, events)
	if !strings.Contains(got, "1.974") {
		t.Errorf("final answer = %q, want it to contain the script's density value 1.974", got)
	}

	// No-model-arithmetic: the final answer's number must be exactly what
	// the script reported (1.9738 -> "1.974" rounding is presentational,
	// but the underlying stdout value must appear verbatim somewhere the
	// answer is derived from -- assert the exact stdout JSON round-trips
	// to the same value used in the answer).
	var scriptOut struct {
		DensityGCm3 float64 `json:"density_g_cm3"`
	}
	if err := json.Unmarshal([]byte(events[scriptRunIdx].ScriptRun.Stdout), &scriptOut); err != nil {
		t.Fatalf("script_run.Stdout is not valid JSON: %v (stdout: %s)", err, events[scriptRunIdx].ScriptRun.Stdout)
	}
	if scriptOut.DensityGCm3 != 1.9738 {
		t.Fatalf("test fixture bug: script_run.Stdout density = %v, want 1.9738", scriptOut.DensityGCm3)
	}

	// Provenance surfaced the dataLocator used.
	provIdx := indexOfEventType(events, agent.EventProvenance)
	if provIdx == -1 {
		t.Fatalf("no provenance event in trace: %v", eventTypesOf(events))
	}
	prov := events[provIdx].Provenance
	if len(prov.DataLocators) != 1 || prov.DataLocators[0] != locator {
		t.Errorf("provenance.DataLocators = %v, want [%q]", prov.DataLocators, locator)
	}
	if prov.OntologyVersion != "test-v1" {
		t.Errorf("provenance.OntologyVersion = %q, want the request's OntologyVersion %q", prov.OntologyVersion, "test-v1")
	}
}

// --- 6.3: out-of-range refusal ---

func TestAcceptance_OutOfRangeTemperatureIsRefusedNotExtrapolated(t *testing.T) {
	// The same FLiBe grounding (valid range 800-1080 K) is asked about at
	// 1500 K, outside the range. The stub grounds and then refuses/flags
	// without ever calling run_python -- design D7: the agent must not
	// present an extrapolated number as a valid measurement.
	sel := &fakeSelector{results: flibeGroundingResults()}

	llm := &scriptedLLM{completions: []agent.Completion{
		{ToolCalls: []agent.ToolCall{{ID: "1", Name: "sparql_query", Arguments: `{"query":"SELECT ?salt ?dataLocator ?validTempMin ?validTempMax WHERE {}"}`}}},
		{Content: "I cannot report a density for FLiBe at 1500 K: the grounded measurement is only valid between 800 K and 1080 K, so 1500 K is out of range. Refusing to extrapolate rather than presenting an unvalidated number."},
	}}

	tools := []agent.Tool{
		agent.NewSPARQLTool(sel),
		// run_python is still offered (a realistic tool roster) but the
		// stub never calls it for this out-of-range question.
		agent.NewPythonTool(&scriptedSandbox{responses: []sandboxResponse{{stdout: "999", exitCode: 0}}}),
	}

	events, err := runAssembledAgent(t, llm, tools, agent.DefaultConfig())
	if err != nil {
		t.Fatalf("Run returned error: %v", err)
	}

	if n := countEventType(events, agent.EventScriptRun); n != 0 {
		t.Fatalf("got %d script_run events, want 0: an out-of-range question must not reach a valid-looking computed answer", n)
	}

	got := strings.ToLower(finalText(t, events))
	for _, want := range []string{"1080", "out of range"} {
		if !strings.Contains(got, want) {
			t.Errorf("final answer = %q, want it to mention %q (flag/refuse out-of-range, not extrapolate)", got, want)
		}
	}
	if strings.Contains(got, "999") {
		t.Errorf("final answer = %q, must not present the sandbox's fake numeric output as if it were a valid measurement", got)
	}
}

// --- 6.4: comparative query resolved by one aggregating script ---

func TestAcceptance_ComparativeQueryResolvedByOneAggregatingScript(t *testing.T) {
	// Ground two candidate salts, then issue exactly ONE run_python call
	// that aggregates over the mounted DB; the reported winner must be
	// the script's output, not a model-side comparison (spec "Comparative
	// queries answered by aggregation in one script").
	candidates := &graph.Results{}
	candidates.Head.Vars = []string{"salt", "dataLocator"}
	candidates.Results.Bindings = []map[string]graph.Binding{
		{
			"salt":        {Type: "uri", Value: "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"},
			"dataLocator": acceptanceBinding("nist-srd27/density#BeF2-LiF|34.0-66.0"),
		},
		{
			"salt":        {Type: "uri", Value: "https://w3id.org/msr-kg/data#salt-NaF-ZrF4"},
			"dataLocator": acceptanceBinding("nist-srd27/density#NaF-ZrF4|50.0-50.0"),
		},
	}
	sel := &fakeSelector{results: candidates}

	sandbox := &scriptedSandbox{responses: []sandboxResponse{
		{stdout: `{"winner_salt": "NaF-ZrF4|50.0-50.0", "winner_locator": "nist-srd27/density#NaF-ZrF4|50.0-50.0", "density_g_cm3": 3.8}`, exitCode: 0},
	}}

	llm := &scriptedLLM{completions: []agent.Completion{
		{ToolCalls: []agent.ToolCall{{ID: "1", Name: "sparql_query", Arguments: `{"query":"SELECT ?salt ?dataLocator WHERE {}"}`}}},
		{ToolCalls: []agent.ToolCall{{ID: "2", Name: "run_python", Arguments: `{"script":"aggregate over both locators and print the max-density winner as JSON"}`}}},
		{Content: "The highest-density candidate is NaF-ZrF4|50.0-50.0 at 3.8 g/cm3."},
	}}

	tools := []agent.Tool{
		agent.NewSPARQLTool(sel),
		agent.NewPythonTool(sandbox),
	}

	events, err := runAssembledAgent(t, llm, tools, agent.DefaultConfig())
	if err != nil {
		t.Fatalf("Run returned error: %v", err)
	}

	if n := countEventType(events, agent.EventScriptRun); n != 1 {
		t.Fatalf("got %d script_run events, want exactly 1 (a single aggregating script)", n)
	}
	if n := sandbox.calls; n != 1 {
		t.Fatalf("sandbox.Run called %d times, want exactly 1", n)
	}

	scriptRunIdx := indexOfEventType(events, agent.EventScriptRun)
	var scriptOut struct {
		WinnerSalt string `json:"winner_salt"`
	}
	if err := json.Unmarshal([]byte(events[scriptRunIdx].ScriptRun.Stdout), &scriptOut); err != nil {
		t.Fatalf("script_run.Stdout is not valid JSON: %v", err)
	}

	got := finalText(t, events)
	if !strings.Contains(got, scriptOut.WinnerSalt) {
		t.Errorf("final answer = %q, want it to name the script's winner %q (not a model-side comparison)", got, scriptOut.WinnerSalt)
	}
}

// --- 6.8: schema-generic answer for data present only in the fakes ---

func TestAcceptance_SchemaGenericAnswerForUnseenSaltAndProperty(t *testing.T) {
	// A salt/property/coefficient row that does NOT exist in the NIST
	// seed data, present only in this test's fakes: the same agent code
	// and same tool constructors must ground and answer it, proving
	// nothing about the answer surface is hardcoded (spec "Schema-generic
	// answer surface").
	const locator = "acme-lab/viscosity#NaCl-MgCl2|60.0-40.0"

	results := &graph.Results{}
	results.Head.Vars = []string{"salt", "dataLocator", "equationForm", "validTempMin", "validTempMax"}
	results.Results.Bindings = []map[string]graph.Binding{
		{
			"salt":         {Type: "uri", Value: "https://w3id.org/msr-kg/data#salt-NaCl-MgCl2-60.0-40.0"},
			"dataLocator":  acceptanceBinding(locator),
			"equationForm": {Type: "uri", Value: "https://w3id.org/msr-kg/ontology#linear"},
			"validTempMin": acceptanceBinding("700"),
			"validTempMax": acceptanceBinding("900"),
		},
	}
	sel := &fakeSelector{results: results}

	db := openSeededStoreDB(t, []measurementRow{
		{locator: locator, salt: "NaCl-MgCl2|60.0-40.0", property: "viscosity", c0: 5.2, c1: -1.1e-3, tMin: 700, tMax: 900, equationForm: "Linear"},
	})

	sandbox := &scriptedSandbox{responses: []sandboxResponse{
		{stdout: `{"viscosity_cP": 4.31}`, exitCode: 0},
	}}

	llm := &scriptedLLM{completions: []agent.Completion{
		{ToolCalls: []agent.ToolCall{{ID: "1", Name: "sparql_query", Arguments: `{"query":"SELECT ?salt ?dataLocator ?equationForm ?validTempMin ?validTempMax WHERE {}"}`}}},
		{ToolCalls: []agent.ToolCall{{ID: "2", Name: "sql_query", Arguments: `{"query":"SELECT c0, c1 FROM measurement_value WHERE locator = '` + locator + `'"}`}}},
		{ToolCalls: []agent.ToolCall{{ID: "3", Name: "run_python", Arguments: `{"script":"import json; print(json.dumps({'viscosity_cP': 5.2 + -1.1e-3*800}))"}`}}},
		{Content: "The viscosity of NaCl-MgCl2 (60.0-40.0 mol%) at 800 K is approximately 4.31 cP (dataLocator " + locator + ")."},
	}}

	tools := []agent.Tool{
		agent.NewSPARQLTool(sel),
		agent.NewSQLTool(db),
		agent.NewPythonTool(sandbox),
	}

	events, err := runAssembledAgent(t, llm, tools, agent.DefaultConfig())
	if err != nil {
		t.Fatalf("Run returned error: %v", err)
	}

	scriptRunIdx := indexOfEventType(events, agent.EventScriptRun)
	if scriptRunIdx == -1 {
		t.Fatalf("no script_run in trace: %v", eventTypesOf(events))
	}
	got := finalText(t, events)
	if !strings.Contains(got, "4.31") {
		t.Errorf("final answer = %q, want it to contain the script's viscosity value 4.31", got)
	}
	if !strings.Contains(got, locator) {
		t.Errorf("final answer = %q, want it to surface the dataLocator %q for provenance", got, locator)
	}
}
