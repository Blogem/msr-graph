package agent_test

// Event-schema tests for openspec/changes/provenance-model task 6.4: the
// chat-API contract's "answer" event shape and the script_run event's new
// data_locators field.
//
// These tests are written against the task contract's agreed symbols
// (agent.EventAnswer, agent.AnswerEvent{Grounded bool, Provenance
// ProvenanceEvent}, and a new agent.ScriptRunEvent.DataLocators
// []string field) and are expected to fail to compile on this isolated
// pass-1 branch until the coder's events.go changes land (design D4/D5;
// spec "chat-api" MODIFIED requirement "SSE trace-event stream").
//
// ASSUMPTION (pass-1, flagged in the tester handoff report for
// reconciliation at merge): AnswerEvent.Provenance is pinned as a plain
// (non-pointer) ProvenanceEvent value -- design D4 describes the payload
// as "{ grounded bool, provenance ProvenanceEvent }", i.e. the aggregated
// chain is always present (possibly empty when ungrounded), not optional.
// If the coder instead makes it a *ProvenanceEvent, this file's
// construction (and the loop_test.go answer-stamp tests) need updating at
// merge.

import (
	"encoding/json"
	"testing"

	"github.com/blogem/msr-graph/internal/agent"
)

// TestEvent_AnswerJSONShape covers 6.4's "answer" event marshaling
// contract: an Event{Type: EventAnswer, Answer: &AnswerEvent{...}} must
// marshal with "type":"answer" and an "answer" object carrying "grounded"
// and "provenance".
func TestEvent_AnswerJSONShape(t *testing.T) {
	ev := agent.Event{
		Type: agent.EventAnswer,
		Answer: &agent.AnswerEvent{
			Grounded: true,
			Provenance: agent.ProvenanceEvent{
				DataLocators: []string{"nist-srd27/density#BeF2-LiF|34.0-66.0"},
				DatasetDOIs:  []string{"doi:10.18434/mds2-2298"},
			},
		},
	}

	encoded, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("Marshal: %v", err)
	}

	var decoded map[string]any
	if err := json.Unmarshal(encoded, &decoded); err != nil {
		t.Fatalf("Unmarshal into map: %v (encoded: %s)", err, encoded)
	}

	if decoded["type"] != "answer" {
		t.Errorf(`decoded["type"] = %v, want "answer"`, decoded["type"])
	}

	answer, ok := decoded["answer"].(map[string]any)
	if !ok {
		t.Fatalf(`decoded["answer"] = %v (%T), want an object`, decoded["answer"], decoded["answer"])
	}
	if grounded, ok := answer["grounded"].(bool); !ok || !grounded {
		t.Errorf(`answer["grounded"] = %v, want true`, answer["grounded"])
	}
	provenance, ok := answer["provenance"]
	if !ok {
		t.Fatal(`answer object missing "provenance" key`)
	}
	provenanceObj, ok := provenance.(map[string]any)
	if !ok {
		t.Fatalf(`answer["provenance"] = %v (%T), want an object`, provenance, provenance)
	}
	locators, ok := provenanceObj["data_locators"].([]any)
	if !ok || len(locators) != 1 || locators[0] != "nist-srd27/density#BeF2-LiF|34.0-66.0" {
		t.Errorf(`answer["provenance"]["data_locators"] = %v, want ["nist-srd27/density#BeF2-LiF|34.0-66.0"]`, provenanceObj["data_locators"])
	}
}

// TestEvent_AnswerJSONShape_Ungrounded covers the ungrounded-answer
// scenario's JSON shape: grounded:false still marshals a well-formed
// answer object (an aggregated, but empty, provenance chain).
func TestEvent_AnswerJSONShape_Ungrounded(t *testing.T) {
	ev := agent.Event{
		Type: agent.EventAnswer,
		Answer: &agent.AnswerEvent{
			Grounded: false,
		},
	}

	encoded, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("Marshal: %v", err)
	}

	var decoded map[string]any
	if err := json.Unmarshal(encoded, &decoded); err != nil {
		t.Fatalf("Unmarshal into map: %v (encoded: %s)", err, encoded)
	}

	answer, ok := decoded["answer"].(map[string]any)
	if !ok {
		t.Fatalf(`decoded["answer"] = %v (%T), want an object`, decoded["answer"], decoded["answer"])
	}
	if grounded, ok := answer["grounded"].(bool); !ok || grounded {
		t.Errorf(`answer["grounded"] = %v, want false`, answer["grounded"])
	}
}

// TestScriptRunEvent_DataLocatorsPresentWhenSet covers 6.4's script_run
// data_locators contract: a ScriptRunEvent with DataLocators set marshals
// a "data_locators" array (design D5).
func TestScriptRunEvent_DataLocatorsPresentWhenSet(t *testing.T) {
	ev := agent.Event{
		Type: agent.EventScriptRun,
		ScriptRun: &agent.ScriptRunEvent{
			Source:       "print(42)",
			DataLocators: []string{"nist-srd27/density#BeF2-LiF|34.0-66.0"},
		},
	}

	encoded, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("Marshal: %v", err)
	}

	var decoded map[string]any
	if err := json.Unmarshal(encoded, &decoded); err != nil {
		t.Fatalf("Unmarshal into map: %v (encoded: %s)", err, encoded)
	}

	scriptRun, ok := decoded["script_run"].(map[string]any)
	if !ok {
		t.Fatalf(`decoded["script_run"] = %v (%T), want an object`, decoded["script_run"], decoded["script_run"])
	}
	locators, ok := scriptRun["data_locators"].([]any)
	if !ok || len(locators) != 1 || locators[0] != "nist-srd27/density#BeF2-LiF|34.0-66.0" {
		t.Errorf(`script_run["data_locators"] = %v, want ["nist-srd27/density#BeF2-LiF|34.0-66.0"]`, scriptRun["data_locators"])
	}
}

// TestScriptRunEvent_DataLocatorsOmittedWhenEmpty covers 6.4's "omitted
// when empty" clause: a ScriptRunEvent with no DataLocators must not
// serialize a "data_locators" key at all (omitempty), matching the
// existing truncation-style fields' convention on this struct.
func TestScriptRunEvent_DataLocatorsOmittedWhenEmpty(t *testing.T) {
	ev := agent.Event{
		Type: agent.EventScriptRun,
		ScriptRun: &agent.ScriptRunEvent{
			Source: "print(42)",
		},
	}

	encoded, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("Marshal: %v", err)
	}

	var decoded map[string]any
	if err := json.Unmarshal(encoded, &decoded); err != nil {
		t.Fatalf("Unmarshal into map: %v (encoded: %s)", err, encoded)
	}

	scriptRun, ok := decoded["script_run"].(map[string]any)
	if !ok {
		t.Fatalf(`decoded["script_run"] = %v (%T), want an object`, decoded["script_run"], decoded["script_run"])
	}
	if _, present := scriptRun["data_locators"]; present {
		t.Errorf(`script_run object unexpectedly has "data_locators" key when empty: %v`, scriptRun)
	}
}
