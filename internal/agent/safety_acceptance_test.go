package agent_test

// Safety-branch acceptance suite for the ingest-iaea-safety change (chunk
// 11, tasks 6.2 / 8.7). Design D7 ("The agent answers the stakeholder
// questions with no new tools") states the Safety branch reaches the
// agent purely through the cached KG-schema system prompt: no new tool
// code, no hardcoded safety terms. These tests therefore drive the SAME
// assembled agent.New(...).Run(...) loop and the SAME real tool
// constructors (agent.NewSPARQLTool, agent.NewSQLTool,
// agent.NewPythonTool) as acceptance_test.go, wired to safety-shaped
// fakes -- a fakeSelector returning the evidence-chain / evidence-gap
// SPARQL traversal results the safety genre would produce, and a
// scriptedSandbox for the requirement-satisfaction margin computation.
// No agent/tool code changes are exercised or required; this file only
// pins that the EXISTING machinery is safety-generic.
//
// This file reuses, unqualified, the shared fakes/helpers declared in
// acceptance_test.go and sparql_test.go (same package agent_test):
// fakeSelector, scriptedLLM, scriptedSandbox, sandboxResponse,
// acceptanceBinding, measurementRow, openSeededStoreDB,
// runAssembledAgent, eventTypesOf, indexOfEventType, countEventType,
// finalText.
//
// Scenarios (design D4/D7, spec analysis-agent "Safety-traceability
// answers over the grown Safety branch" / "Evidence-gap disclosure" /
// "Requirement satisfaction computed in the sandbox with the
// soft-criterion caveat"):
//
//   - Evidence chain: SafetyFunction -servedByProperty-> PhysicalProperty
//     <-forProperty- PropertyMeasurement -ofSalt-> MoltenSalt, each fact's
//     prov:wasDerivedFrom source surfaced, final answer stamped grounded.
//   - Evidence gap: a FILTER NOT EXISTS query for a servedByProperty-linked
//     property lacking a PropertyMeasurement -- the agent reports the gap,
//     never fabricates a value.
//   - Requirement satisfaction: a sandbox run_python script computes the
//     434 vs 500 margin; the answer states the margin AND the
//     soft-criterion caveat (a selection preference, not a licensing
//     limit).
//   - Ungrounded stamp: a requirement-satisfaction question with no
//     resolvable threshold source is stamped ungrounded, with no
//     fabricated satisfaction verdict.

import (
	"encoding/json"
	"strconv"
	"strings"
	"testing"

	"github.com/blogem/msr-graph/internal/agent"
	"github.com/blogem/msr-graph/internal/graph"
)

// --- shared safety IRIs/fixtures ---

const (
	safetyFunctionConfinementIRI = "https://w3id.org/msr-kg/data#sf-confinement"
	safetyVaporPressurePropIRI   = "https://w3id.org/msr-kg/ontology#vaporPressure"
	safetyFLiBeSaltIRI           = "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"
	safetyMeasurementIRI         = "https://w3id.org/msr-kg/data#measurement-FLiBe-vaporPressure"
	safetyFunctionDocIRI         = "https://w3id.org/msr-kg/data#GIF-Holcomb-MSR-safety"
	safetyMeasurementDocIRI      = "https://w3id.org/msr-kg/data#ORNL-TM-2316"
	safetyVaporPressureLocator   = "nist-srd27/vaporPressure#BeF2-LiF|34.0-66.0"
)

// jsonArgs marshals a {"query": q} tool-call argument via encoding/json
// (rather than hand-rolled string concatenation), so a SPARQL query
// containing quotes or newlines round-trips safely into a
// agent.ToolCall.Arguments raw JSON string.
func jsonArgs(t *testing.T, query string) string {
	t.Helper()
	encoded, err := json.Marshal(map[string]string{"query": query})
	if err != nil {
		t.Fatalf("jsonArgs: marshal: %v", err)
	}
	return string(encoded)
}

// --- 6.2 + 8.7: evidence-chain traversal returns the value + provenance chain, stamped grounded ---

// safetyEvidenceChainQuery is the agent-usable SPARQL example for task
// 6.2's evidence-chain traversal: SafetyFunction -servedByProperty->
// PhysicalProperty <-forProperty- PropertyMeasurement -ofSalt-> MoltenSalt,
// with each fact's prov:wasDerivedFrom source bound alongside it (design
// D7's "plus the prov:wasDerivedFrom chain").
const safetyEvidenceChainQuery = `PREFIX msr:  <https://w3id.org/msr-kg/ontology#>
PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX prov: <http://www.w3.org/ns/prov#>
SELECT ?function ?property ?measurement ?salt ?dataLocator ?functionDocCitedIn ?measurementDocCitedIn WHERE {
  ?function a msr:SafetyFunction ; msr:servedByProperty ?property ; prov:wasDerivedFrom ?functionDocCitedIn .
  ?measurement a msr:PropertyMeasurement ; msr:forProperty ?property ; msr:ofSalt ?salt ;
      msr:dataLocator ?dataLocator ; prov:wasDerivedFrom ?measurementDocCitedIn .
  FILTER(?function = msrd:sf-confinement && ?salt = msrd:salt-BeF2-LiF-34.0-66.0)
}`

// safetyEvidenceChainResults builds the fake SPARQL grounding result for
// the evidence-chain traversal: the confinement safety function's
// servedByProperty link to vaporPressure (design D4's real grounding
// example, "msrd:sf-confinement msr:servedByProperty msr:vaporPressure",
// GIF Holcomb: "low pressure ... large margin to boiling"), joined to the
// FLiBe PropertyMeasurement, with each fact's own prov:wasDerivedFrom
// document bound distinctly (functionDocCitedIn: the safety Document;
// measurementDocCitedIn: the NIST/ORNL measurement source).
func safetyEvidenceChainResults() *graph.Results {
	results := &graph.Results{}
	results.Head.Vars = []string{"function", "property", "measurement", "salt", "dataLocator", "functionDocCitedIn", "measurementDocCitedIn"}
	results.Results.Bindings = []map[string]graph.Binding{
		{
			"function":              {Type: "uri", Value: safetyFunctionConfinementIRI},
			"property":              {Type: "uri", Value: safetyVaporPressurePropIRI},
			"measurement":           {Type: "uri", Value: safetyMeasurementIRI},
			"salt":                  {Type: "uri", Value: safetyFLiBeSaltIRI},
			"dataLocator":           acceptanceBinding(safetyVaporPressureLocator),
			"functionDocCitedIn":    {Type: "uri", Value: safetyFunctionDocIRI},
			"measurementDocCitedIn": {Type: "uri", Value: safetyMeasurementDocIRI},
		},
	}
	return results
}

func TestSafetyAcceptance_EvidenceChainGroundedAnswer(t *testing.T) {
	sel := &fakeSelector{results: safetyEvidenceChainResults()}
	db := openSeededStoreDB(t, []measurementRow{
		{locator: safetyVaporPressureLocator, salt: "BeF2-LiF|34.0-66.0", property: "vaporPressure", c0: 0.9, c1: -3.0e-4, tMin: 800, tMax: 1080, equationForm: "Linear"},
	})
	sandbox := &scriptedSandbox{responses: []sandboxResponse{
		{stdout: `{"vapor_pressure_atm": 0.63}`, exitCode: 0},
	}}

	llm := &scriptedLLM{completions: []agent.Completion{
		// (a) the evidence-chain traversal: function -> servedByProperty ->
		// property <- forProperty <- measurement -> ofSalt -> salt, plus
		// each fact's prov:wasDerivedFrom source (task 6.2's agent-usable
		// example).
		{ToolCalls: []agent.ToolCall{{ID: "1", Name: "sparql_query", Arguments: jsonArgs(t, safetyEvidenceChainQuery)}}},
		// (b) coefficients by dataLocator
		{ToolCalls: []agent.ToolCall{{ID: "2", Name: "sql_query", Arguments: `{"query":"SELECT c0, c1 FROM measurement_value WHERE locator = '` + safetyVaporPressureLocator + `'"}`}}},
		// (c) compute in the sandbox (no model arithmetic)
		{ToolCalls: []agent.ToolCall{{ID: "3", Name: "run_python", Arguments: `{"script":"import json; print(json.dumps({'vapor_pressure_atm': 0.9 + -3.0e-4*900}))"}`}}},
		// (d) final answer, citing the value, dataLocator, and both
		// provenance sources (the safety Document for the function->property
		// link, the NIST/ORNL source for the measurement).
		{Content: "The vapor pressure supporting the confinement safety function for FLiBe is approximately 0.63 atm " +
			"(dataLocator " + safetyVaporPressureLocator + "), derived from " + safetyFunctionDocIRI + " (the servedByProperty link) " +
			"and " + safetyMeasurementDocIRI + " (the measurement)."},
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

	// The evidence-chain traversal is the exact SPARQL pattern of design
	// D7 / task 6.2: servedByProperty, forProperty, ofSalt, and the
	// prov:wasDerivedFrom chain must all appear in the tool-call argument
	// actually issued.
	sparqlCallIdx := indexOfEventType(events, agent.EventToolCall)
	if sparqlCallIdx == -1 || events[sparqlCallIdx].ToolCall.Name != "sparql_query" {
		t.Fatalf("expected first tool_call to be sparql_query, got %+v", eventTypesOf(events))
	}
	issuedQuery := events[sparqlCallIdx].ToolCall.Arguments
	for _, want := range []string{"servedByProperty", "forProperty", "ofSalt", "wasDerivedFrom", "SafetyFunction"} {
		if !strings.Contains(issuedQuery, want) {
			t.Errorf("evidence-chain sparql_query argument = %q, want it to contain %q", issuedQuery, want)
		}
	}

	scriptRunIdx := indexOfEventType(events, agent.EventScriptRun)
	if scriptRunIdx == -1 {
		t.Fatalf("no script_run event in trace: %v", eventTypesOf(events))
	}

	got := finalText(t, events)
	if !strings.Contains(got, "0.63") {
		t.Errorf("final answer = %q, want it to contain the script's vapor-pressure value 0.63", got)
	}
	if !strings.Contains(got, safetyVaporPressureLocator) {
		t.Errorf("final answer = %q, want it to surface the dataLocator %q", got, safetyVaporPressureLocator)
	}

	// Spec "Safety-traceability answers over the grown Safety branch":
	// the answer must be stamped grounded, and the aggregated provenance
	// chain must carry BOTH the safety Document (the servedByProperty
	// link's source) and the NIST/ORNL measurement source, plus the
	// dataLocator used.
	answerIdx := indexOfEventType(events, agent.EventAnswer)
	if answerIdx == -1 {
		t.Fatalf("no answer event in trace: %v", eventTypesOf(events))
	}
	answer := events[answerIdx].Answer
	if !answer.Grounded {
		t.Fatalf("answer.Grounded = false, want true: an evidence-chain traversal with a resolvable prov:wasDerivedFrom chain must be stamped grounded")
	}
	if answer.Provenance == nil {
		t.Fatalf("answer.Provenance = nil, want a populated provenance chain for a grounded answer")
	}
	if len(answer.Provenance.DataLocators) != 1 || answer.Provenance.DataLocators[0] != safetyVaporPressureLocator {
		t.Errorf("answer.Provenance.DataLocators = %v, want [%q]", answer.Provenance.DataLocators, safetyVaporPressureLocator)
	}
	wantCitedIn := map[string]bool{safetyFunctionDocIRI: true, safetyMeasurementDocIRI: true}
	if len(answer.Provenance.CitedIn) != len(wantCitedIn) {
		t.Errorf("answer.Provenance.CitedIn = %v, want exactly %v", answer.Provenance.CitedIn, wantCitedIn)
	}
	for _, doc := range answer.Provenance.CitedIn {
		if !wantCitedIn[doc] {
			t.Errorf("answer.Provenance.CitedIn contains unexpected document %q", doc)
		}
	}
	for doc := range wantCitedIn {
		found := false
		for _, got := range answer.Provenance.CitedIn {
			if got == doc {
				found = true
			}
		}
		if !found {
			t.Errorf("answer.Provenance.CitedIn = %v, missing expected document %q", answer.Provenance.CitedIn, doc)
		}
	}
}

// --- 6.2: evidence-gap disclosure via FILTER NOT EXISTS ---

// safetyEvidenceGapQuery is the agent-usable SPARQL example for task
// 6.2's evidence-gap disclosure: a FILTER NOT EXISTS for a
// PropertyMeasurement of a servedByProperty-linked property, for a given
// salt.
const safetyEvidenceGapQuery = `PREFIX msr:  <https://w3id.org/msr-kg/ontology#>
PREFIX msrd: <https://w3id.org/msr-kg/data#>
SELECT ?function ?property WHERE {
  ?function a msr:SafetyFunction ; msr:servedByProperty ?property .
  FILTER NOT EXISTS {
    ?measurement a msr:PropertyMeasurement ; msr:forProperty ?property ; msr:ofSalt msrd:salt-BeF2-LiF-34.0-66.0 .
  }
}`

func TestSafetyAcceptance_EvidenceGapReportedNotFabricated(t *testing.T) {
	// The gap query's missing-property set: msr:specificHeat is
	// servedByProperty-linked to a safety function but has no
	// PropertyMeasurement for FLiBe -- no dataLocator/citedIn/doi var is
	// bound anywhere in this result, mirroring an unresolved fact (there
	// is, by construction, nothing to cite for an absent measurement).
	results := &graph.Results{}
	results.Head.Vars = []string{"function", "property"}
	results.Results.Bindings = []map[string]graph.Binding{
		{
			"function": {Type: "uri", Value: safetyFunctionConfinementIRI},
			"property": {Type: "uri", Value: "https://w3id.org/msr-kg/ontology#specificHeat"},
		},
	}
	sel := &fakeSelector{results: results}

	llm := &scriptedLLM{completions: []agent.Completion{
		{ToolCalls: []agent.ToolCall{{ID: "1", Name: "sparql_query", Arguments: jsonArgs(t, safetyEvidenceGapQuery)}}},
		{Content: "There is a measurement gap: specificHeat is linked to the confinement safety function, but no " +
			"PropertyMeasurement of specificHeat exists for FLiBe in the graph. I cannot report a value for it."},
	}}

	// run_python is offered (a realistic tool roster) but must never be
	// called: there is no value to compute for a disclosed gap.
	sandbox := &scriptedSandbox{responses: []sandboxResponse{{stdout: "999", exitCode: 0}}}
	tools := []agent.Tool{
		agent.NewSPARQLTool(sel),
		agent.NewPythonTool(sandbox),
	}

	events, err := runAssembledAgent(t, llm, tools, agent.DefaultConfig())
	if err != nil {
		t.Fatalf("Run returned error: %v", err)
	}

	sparqlCallIdx := indexOfEventType(events, agent.EventToolCall)
	if sparqlCallIdx == -1 || events[sparqlCallIdx].ToolCall.Name != "sparql_query" {
		t.Fatalf("expected first tool_call to be sparql_query, got %+v", eventTypesOf(events))
	}
	if !strings.Contains(events[sparqlCallIdx].ToolCall.Arguments, "FILTER NOT EXISTS") {
		t.Errorf("evidence-gap sparql_query argument = %q, want it to contain a FILTER NOT EXISTS clause", events[sparqlCallIdx].ToolCall.Arguments)
	}

	if n := countEventType(events, agent.EventScriptRun); n != 0 {
		t.Fatalf("got %d script_run events, want 0: an evidence-gap answer must not fabricate a computed value", n)
	}
	if sandbox.calls != 0 {
		t.Fatalf("sandbox.Run called %d times, want 0", sandbox.calls)
	}

	got := strings.ToLower(finalText(t, events))
	if !strings.Contains(got, "specificheat") {
		t.Errorf("final answer = %q, want it to name the gapped property (specificHeat)", got)
	}
	disclosesGap := false
	for _, want := range []string{"gap", "no ", "cannot"} {
		if strings.Contains(got, want) {
			disclosesGap = true
			break
		}
	}
	if !disclosesGap {
		t.Errorf("final answer = %q, want it to disclose the measurement gap in plain language", got)
	}
	if strings.Contains(got, "999") {
		t.Errorf("final answer = %q, must not present the sandbox's fake stdout as if it were a real measurement", got)
	}
}

// --- 6.3 / 8.7: requirement satisfaction computed in the sandbox, with the soft-criterion caveat ---

// safetyRequirementQuery is the agent-usable SPARQL example fetching a
// Requirement's stated threshold and the corresponding measurement's
// dataLocator (design D7: "sparql_query to fetch thresholds +
// measurements, then run_python ... to compute margins").
const safetyRequirementQuery = `PREFIX msr:  <https://w3id.org/msr-kg/ontology#>
PREFIX prov: <http://www.w3.org/ns/prov#>
SELECT ?requirement ?thresholdValue ?thresholdComparator ?measurement ?dataLocator ?requirementDocCitedIn WHERE {
  ?requirement a msr:Requirement ; msr:thresholdValue ?thresholdValue ; msr:thresholdComparator ?thresholdComparator ;
      prov:wasDerivedFrom ?requirementDocCitedIn .
  ?measurement a msr:PropertyMeasurement ; msr:forProperty msr:meltingPoint ; msr:dataLocator ?dataLocator .
}`

func TestSafetyAcceptance_RequirementSatisfactionMarginWithSoftCriterionCaveat(t *testing.T) {
	const locator = "nist-srd27/meltingPoint#BeF2-LiF|34.0-66.0"
	const requirementDoc = "https://w3id.org/msr-kg/data#ORNL-TM-2006-12"

	results := &graph.Results{}
	results.Head.Vars = []string{"requirement", "thresholdValue", "thresholdComparator", "measurement", "dataLocator", "requirementDocCitedIn"}
	results.Results.Bindings = []map[string]graph.Binding{
		{
			"requirement":           {Type: "uri", Value: "https://w3id.org/msr-kg/data#req-liquidus-preference"},
			"thresholdValue":        acceptanceBinding("500"),
			"thresholdComparator":   {Type: "uri", Value: "https://w3id.org/msr-kg/ontology#lt"},
			"measurement":           {Type: "uri", Value: "https://w3id.org/msr-kg/data#measurement-FLiBe-meltingPoint"},
			"dataLocator":           acceptanceBinding(locator),
			"requirementDocCitedIn": {Type: "uri", Value: requirementDoc},
		},
	}
	sel := &fakeSelector{results: results}

	sandbox := &scriptedSandbox{responses: []sandboxResponse{
		{stdout: `{"measured_c": 434, "threshold_c": 500, "margin_c": 66, "satisfied": true}`, exitCode: 0},
	}}

	llm := &scriptedLLM{completions: []agent.Completion{
		{ToolCalls: []agent.ToolCall{{ID: "1", Name: "sparql_query", Arguments: jsonArgs(t, safetyRequirementQuery)}}},
		{ToolCalls: []agent.ToolCall{{ID: "2", Name: "run_python", Arguments: `{"script":"import json; measured=434; threshold=500; print(json.dumps({'measured_c': measured, 'threshold_c': threshold, 'margin_c': threshold-measured, 'satisfied': measured < threshold}))"}`}}},
		{Content: "FLiBe's liquidus (434 degC) is 66 degC below the stated 500 degC coolant liquidus preference -- " +
			"satisfied, with a 66 degC margin. Note: the 500 degC figure is a selection preference, not a licensing limit."},
	}}

	tools := []agent.Tool{
		agent.NewSPARQLTool(sel),
		agent.NewPythonTool(sandbox),
	}

	events, err := runAssembledAgent(t, llm, tools, agent.DefaultConfig())
	if err != nil {
		t.Fatalf("Run returned error: %v", err)
	}

	scriptRunIdx := indexOfEventType(events, agent.EventScriptRun)
	if scriptRunIdx == -1 {
		t.Fatalf("no script_run event in trace: %v", eventTypesOf(events))
	}
	var scriptOut struct {
		MarginC   float64 `json:"margin_c"`
		Satisfied bool    `json:"satisfied"`
	}
	if err := json.Unmarshal([]byte(events[scriptRunIdx].ScriptRun.Stdout), &scriptOut); err != nil {
		t.Fatalf("script_run.Stdout is not valid JSON: %v", err)
	}
	if scriptOut.MarginC != 66 || !scriptOut.Satisfied {
		t.Fatalf("test fixture bug: script margin/satisfied = %v/%v, want 66/true", scriptOut.MarginC, scriptOut.Satisfied)
	}

	got := strings.ToLower(finalText(t, events))
	if !strings.Contains(got, strconv.Itoa(int(scriptOut.MarginC))) {
		t.Errorf("final answer = %q, want it to report the script's margin (%v)", got, scriptOut.MarginC)
	}
	// Soft-criterion caveat: the threshold is a selection preference, not
	// a licensing/regulatory limit (design D5).
	if !strings.Contains(got, "preference") {
		t.Errorf("final answer = %q, want it to state the threshold is a selection preference", got)
	}
	if !strings.Contains(got, "not a licensing") && !strings.Contains(got, "not a regulatory") {
		t.Errorf("final answer = %q, want it to explicitly caveat that the threshold is NOT a licensing/regulatory limit", got)
	}

	// A resolvable threshold source (prov:wasDerivedFrom the requirement
	// Document) makes this a grounded requirement-satisfaction answer.
	answerIdx := indexOfEventType(events, agent.EventAnswer)
	if answerIdx == -1 {
		t.Fatalf("no answer event in trace: %v", eventTypesOf(events))
	}
	answer := events[answerIdx].Answer
	if !answer.Grounded {
		t.Fatalf("answer.Grounded = false, want true: a requirement-satisfaction answer with a resolvable threshold source must be stamped grounded")
	}
}

// --- 8.7: requirement satisfaction with no resolvable threshold source is stamped ungrounded ---

func TestSafetyAcceptance_RequirementSatisfactionWithoutThresholdSourceIsStampedUngrounded(t *testing.T) {
	// The same requirement-satisfaction query, but no matching Requirement
	// exists in the graph: empty result set, so no dataLocator/citedIn/doi
	// var is ever bound -- there is no resolvable threshold source.
	results := &graph.Results{}
	results.Head.Vars = []string{"requirement", "thresholdValue", "thresholdComparator", "measurement", "dataLocator", "requirementDocCitedIn"}
	results.Results.Bindings = nil
	sel := &fakeSelector{results: results}

	sandbox := &scriptedSandbox{responses: []sandboxResponse{{stdout: `{"satisfied": true}`, exitCode: 0}}}

	llm := &scriptedLLM{completions: []agent.Completion{
		{ToolCalls: []agent.ToolCall{{ID: "1", Name: "sparql_query", Arguments: jsonArgs(t, safetyRequirementQuery)}}},
		{Content: "I cannot assert whether this requirement is satisfied: no resolvable threshold source was found in the graph, so no verdict is given."},
	}}

	tools := []agent.Tool{
		agent.NewSPARQLTool(sel),
		// run_python is offered but must never be called: there is no
		// threshold to compare against.
		agent.NewPythonTool(sandbox),
	}

	events, err := runAssembledAgent(t, llm, tools, agent.DefaultConfig())
	if err != nil {
		t.Fatalf("Run returned error: %v", err)
	}

	if n := countEventType(events, agent.EventScriptRun); n != 0 {
		t.Fatalf("got %d script_run events, want 0: no satisfaction verdict may be computed without a resolvable threshold source", n)
	}
	if sandbox.calls != 0 {
		t.Fatalf("sandbox.Run called %d times, want 0", sandbox.calls)
	}

	answerIdx := indexOfEventType(events, agent.EventAnswer)
	if answerIdx == -1 {
		t.Fatalf("no answer event in trace: %v", eventTypesOf(events))
	}
	answer := events[answerIdx].Answer
	if answer.Grounded {
		t.Fatalf("answer.Grounded = true, want false: a requirement-satisfaction answer with no resolvable threshold source must be stamped ungrounded")
	}
	if answer.Provenance != nil {
		t.Errorf("answer.Provenance = %+v, want nil for an ungrounded answer", answer.Provenance)
	}

	got := strings.ToLower(finalText(t, events))
	if !strings.Contains(got, "cannot") && !strings.Contains(got, "no resolvable") && !strings.Contains(got, "no verdict") {
		t.Errorf("final answer = %q, want it to explicitly decline to assert satisfaction", got)
	}
	if strings.Contains(got, "satisfied") && !strings.Contains(got, "cannot assert whether") {
		t.Errorf("final answer = %q, must not present a satisfaction verdict without a resolvable threshold source", got)
	}
}
