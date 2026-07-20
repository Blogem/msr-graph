package agent_test

// Unit tests for the sparql_query tool (task 2.1). Every test drives a
// fake GraphSelector -- no test contacts a live GraphDB instance
// (mirroring design D6's "stubbed, offline" test strategy).

import (
	"context"
	"encoding/json"
	"errors"
	"sort"
	"strings"
	"testing"

	"github.com/blogem/msr-graph/internal/agent"
	"github.com/blogem/msr-graph/internal/graph"
)

// fakeSelector is a minimal agent.GraphSelector driven by a closure, so
// each test can script exactly the Select behavior it needs (a canned
// *graph.Results or an error) without touching a real GraphDB endpoint.
type fakeSelector struct {
	results *graph.Results
	err     error
	// gotQuery captures the query string passed to Select, so a test can
	// assert on it if needed.
	gotQuery string
}

func (f *fakeSelector) Select(_ context.Context, query string) (*graph.Results, error) {
	f.gotQuery = query
	if f.err != nil {
		return nil, f.err
	}
	return f.results, nil
}

// binding is a small helper for building graph.Binding values in test
// fixtures.
func binding(value string) graph.Binding {
	return graph.Binding{Type: "literal", Value: value}
}

func TestSPARQLTool_GroundingQueryReturnsVarsAndRows(t *testing.T) {
	results := &graph.Results{}
	results.Head.Vars = []string{"salt", "dataLocator", "equationForm", "validTempMin", "validTempMax"}
	results.Results.Bindings = []map[string]graph.Binding{
		{
			"salt":         {Type: "uri", Value: "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"},
			"dataLocator":  binding("nist-srd27/density#BeF2-LiF|34.0-66.0"),
			"equationForm": {Type: "uri", Value: "https://w3id.org/msr-kg/ontology#linear"},
			"validTempMin": binding("700"),
			"validTempMax": binding("1000"),
		},
	}

	sel := &fakeSelector{results: results}
	tool := agent.NewSPARQLTool(sel)

	args := `{"query": "SELECT ?salt ?dataLocator ?equationForm ?validTempMin ?validTempMax WHERE { ?salt <https://w3id.org/msr-kg/ontology#hasMeasurement> ?m }"}`
	got, err := tool.Call(context.Background(), args, nil)
	if err != nil {
		t.Fatalf("Call returned error: %v", err)
	}

	var decoded struct {
		Vars []string            `json:"vars"`
		Rows []map[string]string `json:"rows"`
	}
	if err := json.Unmarshal([]byte(got), &decoded); err != nil {
		t.Fatalf("result did not parse as JSON: %v\nresult: %s", err, got)
	}

	wantVars := []string{"salt", "dataLocator", "equationForm", "validTempMin", "validTempMax"}
	gotVars := append([]string(nil), decoded.Vars...)
	sort.Strings(gotVars)
	sort.Strings(wantVars)
	if !equalStrings(gotVars, wantVars) {
		t.Errorf("vars = %v, want (unordered) %v", decoded.Vars, wantVars)
	}

	if len(decoded.Rows) != 1 {
		t.Fatalf("rows = %d, want 1", len(decoded.Rows))
	}
	row := decoded.Rows[0]
	if row["salt"] != "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0" {
		t.Errorf("row[salt] = %q, want the salt IRI", row["salt"])
	}
	if row["dataLocator"] != "nist-srd27/density#BeF2-LiF|34.0-66.0" {
		t.Errorf("row[dataLocator] = %q, want the seed dataLocator", row["dataLocator"])
	}
	if row["equationForm"] != "https://w3id.org/msr-kg/ontology#linear" {
		t.Errorf("row[equationForm] = %q, want the equation-form IRI", row["equationForm"])
	}
	if row["validTempMin"] != "700" || row["validTempMax"] != "1000" {
		t.Errorf("validTempMin/Max = %q/%q, want 700/1000", row["validTempMin"], row["validTempMax"])
	}

	if sel.gotQuery != mustDecodeQuery(t, args) {
		t.Errorf("Select called with query %q, want the decoded query argument", sel.gotQuery)
	}
}

func TestSPARQLTool_ProvenanceEventEmittedFromVariableNames(t *testing.T) {
	results := &graph.Results{}
	results.Head.Vars = []string{"dataLocator", "citedIn", "doi"}
	results.Results.Bindings = []map[string]graph.Binding{
		{
			"dataLocator": binding("nist-srd27/density#BeF2-LiF|34.0-66.0"),
			"citedIn":     {Type: "uri", Value: "https://w3id.org/msr-kg/data#doc-nist-srd27"},
			"doi":         binding("10.1000/example-doi"),
		},
	}

	sel := &fakeSelector{results: results}
	tool := agent.NewSPARQLTool(sel)

	var events []agent.Event
	emit := func(e agent.Event) { events = append(events, e) }

	_, err := tool.Call(context.Background(), `{"query": "SELECT ?dataLocator ?citedIn ?doi WHERE {}"}`, emit)
	if err != nil {
		t.Fatalf("Call returned error: %v", err)
	}

	var provEvents []agent.Event
	for _, e := range events {
		if e.Type == agent.EventProvenance {
			provEvents = append(provEvents, e)
		}
	}
	if len(provEvents) != 1 {
		t.Fatalf("provenance events emitted = %d, want exactly 1 (events: %+v)", len(provEvents), events)
	}

	p := provEvents[0].Provenance
	if p == nil {
		t.Fatal("provenance event carried a nil Provenance payload")
	}
	if !equalStrings(p.DataLocators, []string{"nist-srd27/density#BeF2-LiF|34.0-66.0"}) {
		t.Errorf("DataLocators = %v, want [nist-srd27/density#BeF2-LiF|34.0-66.0]", p.DataLocators)
	}
	if !equalStrings(p.CitedIn, []string{"https://w3id.org/msr-kg/data#doc-nist-srd27"}) {
		t.Errorf("CitedIn = %v, want [https://w3id.org/msr-kg/data#doc-nist-srd27]", p.CitedIn)
	}
	if !equalStrings(p.DatasetDOIs, []string{"10.1000/example-doi"}) {
		t.Errorf("DatasetDOIs = %v, want [10.1000/example-doi]", p.DatasetDOIs)
	}
	if p.OntologyVersion != "" {
		t.Errorf("OntologyVersion = %q, want empty (the loop stamps it)", p.OntologyVersion)
	}
}

func TestSPARQLTool_NoProvenanceEventWhenNoMatchingVars(t *testing.T) {
	results := &graph.Results{}
	results.Head.Vars = []string{"salt", "label"}
	results.Results.Bindings = []map[string]graph.Binding{
		{"salt": {Type: "uri", Value: "https://w3id.org/msr-kg/data#salt-x"}, "label": binding("FLiBe")},
	}

	sel := &fakeSelector{results: results}
	tool := agent.NewSPARQLTool(sel)

	var events []agent.Event
	_, err := tool.Call(context.Background(), `{"query": "SELECT ?salt ?label WHERE {}"}`, func(e agent.Event) {
		events = append(events, e)
	})
	if err != nil {
		t.Fatalf("Call returned error: %v", err)
	}
	for _, e := range events {
		if e.Type == agent.EventProvenance {
			t.Fatalf("unexpected provenance event for vars with no locator/cited/doi convention: %+v", e)
		}
	}
}

func TestSPARQLTool_SelectErrorIsReturnedNotPanicked(t *testing.T) {
	sel := &fakeSelector{err: errors.New("graph: Select does not accept queries with a FROM/FROM NAMED clause")}
	tool := agent.NewSPARQLTool(sel)

	_, err := tool.Call(context.Background(), `{"query": "SELECT * FROM <urn:msr:staging> WHERE {}"}`, nil)
	if err == nil {
		t.Fatal("expected an error to be returned, got nil")
	}
	if !strings.Contains(err.Error(), "FROM/FROM NAMED") {
		t.Errorf("error = %v, want it to surface the underlying Select error", err)
	}
}

func TestSPARQLTool_BadArgumentsReturnError(t *testing.T) {
	tool := agent.NewSPARQLTool(&fakeSelector{})

	if _, err := tool.Call(context.Background(), `not json`, nil); err == nil {
		t.Fatal("expected an error for invalid JSON arguments, got nil")
	}
	if _, err := tool.Call(context.Background(), `{}`, nil); err == nil {
		t.Fatal("expected an error for a missing \"query\" argument, got nil")
	}
	if _, err := tool.Call(context.Background(), `{"query": "   "}`, nil); err == nil {
		t.Fatal("expected an error for a blank \"query\" argument, got nil")
	}
}

func TestSPARQLTool_SpecDescribesGroundingAndForbidsFrom(t *testing.T) {
	tool := agent.NewSPARQLTool(&fakeSelector{})
	spec := tool.Spec()

	if spec.Name != "sparql_query" {
		t.Errorf("Spec().Name = %q, want sparql_query", spec.Name)
	}

	desc := strings.ToLower(spec.Description)
	for _, want := range []string{
		// D2/D3: salts ground via a real msr:Mention's surfaceForm,
		// following msr:linksTo to the salt, with msr:inDocument as the
		// traceable evidence.
		"msr:linksto", "msr:surfaceform", "msr:indocument",
		// D2/D6: properties ground by matching the query term against a
		// msr:PhysicalProperty's own rdfs:label -- no concept hop.
		"rdfs:label", "msr:physicalproperty",
		// FROM-forbidden guidance: the tool does not inject prefixes and
		// rejects any query supplying its own FROM/FROM NAMED clause.
		"from", "prefix",
	} {
		if !strings.Contains(desc, want) {
			t.Errorf("Spec().Description missing %q; got: %s", want, spec.Description)
		}
	}

	// D2/D6: skos:closeMatch is a SKOS range abuse (its domain/range is
	// skos:Concept; neither a MoltenSalt individual nor a
	// PhysicalProperty term is one) and must not appear anywhere in the
	// grounding recipe -- neither salt<->concept nor property<->concept.
	if strings.Contains(desc, "skos:closematch") {
		t.Errorf("Spec().Description reintroduced skos:closeMatch grounding; got: %s", spec.Description)
	}

	var schema map[string]any
	if err := json.Unmarshal(spec.Parameters, &schema); err != nil {
		t.Fatalf("Spec().Parameters did not parse as JSON: %v", err)
	}
	props, _ := schema["properties"].(map[string]any)
	if _, ok := props["query"]; !ok {
		t.Errorf("Spec().Parameters missing \"query\" property: %s", spec.Parameters)
	}
	required, _ := schema["required"].([]any)
	if len(required) != 1 || required[0] != "query" {
		t.Errorf("Spec().Parameters \"required\" = %v, want [\"query\"]", required)
	}
}

// equalStrings reports whether a and b contain the same strings (order
// sensitive; callers sort first when order doesn't matter).
func equalStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

// mustDecodeQuery extracts the "query" field from a JSON args string,
// for asserting Select was called with the decoded (not raw JSON)
// query text.
func mustDecodeQuery(t *testing.T, args string) string {
	t.Helper()
	var parsed struct {
		Query string `json:"query"`
	}
	if err := json.Unmarshal([]byte(args), &parsed); err != nil {
		t.Fatalf("test fixture args did not parse: %v", err)
	}
	return parsed.Query
}
