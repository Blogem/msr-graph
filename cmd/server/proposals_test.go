package main

// Unit tests for the proposal review HTTP API (openspec/changes/
// apply-ontology-changes, chunk 9/task 5.5), pinned against fake
// implementations of the newMux(chat, reader, prop, ckpt) handler
// interfaces -- no live GraphDB, mirroring internal/proposal's own
// fake-client tests (shacl_rollback_test.go) and this package's existing
// chat_test.go / handler_test.go style (httptest.NewRecorder + a mux built
// via newMux).
//
// Because this file is written in parallel with the coder's handler
// implementation (pass 1), the exact SPARQL variable names the queue/
// detail handlers select are not yet known. Canned bindings below hedge
// across the most plausible variable-naming choices (e.g. both "id" and
// "proposal"/"s" bound to the same value) so the tests exercise real
// handler behavior rather than an accidental naming coincidence. See the
// handoff report for the exact aliases used, for reconciliation in pass 2.

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"

	"github.com/blogem/msr-graph/internal/graph"
	"github.com/blogem/msr-graph/internal/proposal"
)

const xsdInteger = "http://www.w3.org/2001/XMLSchema#integer"

// Compile-time contract pins: these fail to compile until the coder's
// handler.go declares graphReader/proposalService with exactly this method
// set (task 5.1-5.3). That is the expected pass-1 state (see package
// doc-comment above); the assertions start passing once the branches
// merge.
var (
	_ graphReader     = (*fakeProposalReader)(nil)
	_ proposalService = (*fakeProposalService)(nil)
)

// --- chatStub: a minimal http.Handler passed as newMux's chat argument so
// /api/chat and /healthz can be asserted unaffected by the new routes. ---

type chatStub struct{ calls int }

func (c *chatStub) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	c.calls++
	w.WriteHeader(http.StatusOK)
}

// --- fakeProposalReader: the graphReader fake used by the queue/detail
// GET handlers. ---

// fakeProposalReader is a functional double for graphReader
// ({SelectRaw, Select}(ctx, query) (*graph.Results, error)): each test
// configures selectRawFn/selectFn to return canned bindings for whichever
// query the handler under test is expected to issue, and records how many
// times each method was called so a test can assert the staging-inclusive-
// path requirement (queue/detail reads go through SelectRaw, never the
// core-dataset Select).
type fakeProposalReader struct {
	selectRawFn func(query string) (*graph.Results, error)
	selectFn    func(query string) (*graph.Results, error)

	selectRawCalls []string
	selectCalls    []string
}

func (f *fakeProposalReader) SelectRaw(_ context.Context, query string) (*graph.Results, error) {
	f.selectRawCalls = append(f.selectRawCalls, query)
	if f.selectRawFn != nil {
		return f.selectRawFn(query)
	}
	return &graph.Results{}, nil
}

func (f *fakeProposalReader) Select(_ context.Context, query string) (*graph.Results, error) {
	f.selectCalls = append(f.selectCalls, query)
	if f.selectFn != nil {
		return f.selectFn(query)
	}
	return &graph.Results{}, nil
}

// --- fakeProposalService: the proposalService fake used by the
// approve/reject/edit handlers. ---

// fakeProposalService is a functional double for proposalService
// ({Approve, Reject, Edit}), following the same canned-response pattern
// internal/proposal's own shacl_rollback_test.go uses for its fake
// GraphClient: a *graph.ValidationError (or a sentinel like
// proposal.ErrNotFound / proposal.ErrInvalidTransition) is returned exactly
// as the real Engine would surface it, and every call is counted so a test
// can assert "no mutation" for a rejected request (malformed body, wrong
// method).
type fakeProposalService struct {
	approveFn func(id string, req proposal.ApproveRequest) error
	rejectFn  func(id string) error
	editFn    func(id string, triples string) error

	approveCalls int
	rejectCalls  int
	editCalls    int
}

func (f *fakeProposalService) Approve(_ context.Context, id string, req proposal.ApproveRequest) error {
	f.approveCalls++
	if f.approveFn != nil {
		return f.approveFn(id, req)
	}
	return nil
}

func (f *fakeProposalService) Reject(_ context.Context, id string) error {
	f.rejectCalls++
	if f.rejectFn != nil {
		return f.rejectFn(id)
	}
	return nil
}

func (f *fakeProposalService) Edit(_ context.Context, id string, triples string) error {
	f.editCalls++
	if f.editFn != nil {
		return f.editFn(id, triples)
	}
	return nil
}

// --- canned data builders ---

func bindingsResult(rows ...map[string]graph.Binding) *graph.Results {
	r := &graph.Results{}
	r.Results.Bindings = rows
	return r
}

// queueCanned returns three msr:ChangeProposal rows spanning all three
// review statuses (pending/approved/rejected), each keyed under several
// plausible SPARQL variable-name aliases for the resource identifier
// ("id", the deterministic short slug; "proposal"/"s", the full
// msrd:proposal-{id} IRI) so the test exercises the handler's actual
// status-filtering/rendering logic regardless of which alias it reads.
func queueCanned() *graph.Results {
	row := func(id, kind, status, term, freq string) map[string]graph.Binding {
		full := "https://w3id.org/msr-kg/data#proposal-" + id
		return map[string]graph.Binding{
			"id":           {Type: "literal", Value: id},
			"proposal":     {Type: "uri", Value: full},
			"s":            {Type: "uri", Value: full},
			"kind":         {Type: "literal", Value: kind},
			"status":       {Type: "literal", Value: status},
			"term":         {Type: "literal", Value: term},
			"docFrequency": {Type: "literal", Value: freq, Datatype: xsdInteger},
			"frequency":    {Type: "literal", Value: freq, Datatype: xsdInteger},
		}
	}
	return bindingsResult(
		row("property-solubility", "property", "pending", "solubility", "5"),
		row("property-density", "property", "approved", "density", "12"),
		row("instance-flibe", "instance", "rejected", "FLiBe", "3"),
	)
}

const detailKnownID = "property-solubility"
const detailUnknownID = "does-not-exist"

func detailTriplesCanned() *graph.Results {
	solubilityIRI := "https://w3id.org/msr-kg/ontology#solubility"
	row := func(s, p string, o graph.Binding) map[string]graph.Binding {
		return map[string]graph.Binding{
			"subject": {Type: "uri", Value: s}, "s": {Type: "uri", Value: s},
			"predicate": {Type: "uri", Value: p}, "p": {Type: "uri", Value: p},
			"object": o, "o": o,
		}
	}
	return bindingsResult(
		row(solubilityIRI, "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
			graph.Binding{Type: "uri", Value: "http://www.w3.org/2002/07/owl#DatatypeProperty"}),
		row(solubilityIRI, "http://www.w3.org/2000/01/rdf-schema#label",
			graph.Binding{Type: "literal", Value: "solubility", XMLLang: "en"}),
	)
}

func detailEvidenceCanned() *graph.Results {
	return bindingsResult(map[string]graph.Binding{
		"text":         {Type: "literal", Value: "The solubility of BeF2 in FLiBe was measured at 850 C."},
		"evidenceText": {Type: "literal", Value: "The solubility of BeF2 in FLiBe was measured at 850 C."},
		"citedIn":      {Type: "uri", Value: "https://w3id.org/msr-kg/data#doc-ORNL-TM-2316"},
		"startOffset":  {Type: "literal", Value: "120", Datatype: xsdInteger},
		"endOffset":    {Type: "literal", Value: "145", Datatype: xsdInteger},
	})
}

func detailNeighborhoodCanned() *graph.Results {
	return bindingsResult(map[string]graph.Binding{
		"subject":   {Type: "uri", Value: "https://w3id.org/msr-kg/ontology#solubility"},
		"s":         {Type: "uri", Value: "https://w3id.org/msr-kg/ontology#solubility"},
		"predicate": {Type: "uri", Value: "http://www.w3.org/2000/01/rdf-schema#domain"},
		"p":         {Type: "uri", Value: "http://www.w3.org/2000/01/rdf-schema#domain"},
		"object":    {Type: "uri", Value: "https://w3id.org/msr-kg/ontology#Salt"},
		"o":         {Type: "uri", Value: "https://w3id.org/msr-kg/ontology#Salt"},
	})
}

// newDetailReader builds a fakeProposalReader that dispatches SelectRaw by
// query text: a query naming the unknown id returns zero bindings (the
// 404 path); a query scoped to the proposal graph (urn:msr:proposal/{id})
// returns the proposal's triples; the one-hop ontology-neighborhood lookup
// -- issued via SelectRaw too (an explicit multi-graph FILTER(?g IN (...))
// over the core graphs, rather than the restricted Select) -- is matched
// on the stable "FILTER(?g IN" substring so it is robust to whitespace/
// formatting differences in the real query; any other query mentioning the
// known id (the evidence lookup, keyed off the msrd:proposal-{id}
// resource) returns the evidence rows.
func newDetailReader() *fakeProposalReader {
	return &fakeProposalReader{
		selectRawFn: func(query string) (*graph.Results, error) {
			switch {
			case strings.Contains(query, detailUnknownID):
				return &graph.Results{}, nil
			case strings.Contains(query, "urn:msr:proposal/"+detailKnownID):
				return detailTriplesCanned(), nil
			case strings.Contains(query, "FILTER(?g IN"):
				return detailNeighborhoodCanned(), nil
			case strings.Contains(query, detailKnownID):
				return detailEvidenceCanned(), nil
			default:
				return nil, fmt.Errorf("fakeProposalReader: unexpected SelectRaw query: %s", query)
			}
		},
	}
}

// --- JSON decode helpers ---

func decodeJSONObject(t *testing.T, body []byte) map[string]any {
	t.Helper()
	var m map[string]any
	if err := json.Unmarshal(body, &m); err != nil {
		t.Fatalf("decode JSON object: %v (body: %s)", err, body)
	}
	return m
}

// numString normalizes a decoded JSON number/string field to its string
// form, since it is not yet known (pass 1) whether the handler emits
// docFrequency/startOffset/endOffset as a JSON number or a passthrough
// string.
func numString(v any) string {
	switch t := v.(type) {
	case float64:
		return strconv.FormatFloat(t, 'f', -1, 64)
	case string:
		return t
	case nil:
		return ""
	default:
		return fmt.Sprintf("%v", t)
	}
}

func asSlice(t *testing.T, v any, field string) []any {
	t.Helper()
	s, ok := v.([]any)
	if !ok {
		t.Fatalf("field %q = %#v, want a JSON array", field, v)
	}
	return s
}

// --- newTestMux: builds a mux with a fresh chatStub plus the given
// reader/prop/ckpt fakes. ---

func newTestMux(reader graphReader, prop proposalService, ckpt checkpointService) (http.Handler, *chatStub) {
	stub := &chatStub{}
	return newMux(stub, reader, prop, ckpt), stub
}

// --- 1. Queue filtering + JSON shape (task 5.5 scenario 1) ---

func TestProposalsQueue_FiltersByStatusAndListsAll(t *testing.T) {
	tests := []struct {
		name    string
		query   string
		wantIDs map[string]struct {
			kind, status, term, freq string
		}
	}{
		{
			name:  "no filter returns every status",
			query: "",
			wantIDs: map[string]struct{ kind, status, term, freq string }{
				"property-solubility": {"property", "pending", "solubility", "5"},
				"property-density":    {"property", "approved", "density", "12"},
				"instance-flibe":      {"instance", "rejected", "FLiBe", "3"},
			},
		},
		{
			name:  "status=pending narrows to pending only",
			query: "?status=pending",
			wantIDs: map[string]struct{ kind, status, term, freq string }{
				"property-solubility": {"property", "pending", "solubility", "5"},
			},
		},
		{
			name:  "status=approved narrows to approved only",
			query: "?status=approved",
			wantIDs: map[string]struct{ kind, status, term, freq string }{
				"property-density": {"property", "approved", "density", "12"},
			},
		},
		{
			name:  "status=rejected narrows to rejected only",
			query: "?status=rejected",
			wantIDs: map[string]struct{ kind, status, term, freq string }{
				"instance-flibe": {"instance", "rejected", "FLiBe", "3"},
			},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			reader := &fakeProposalReader{selectRawFn: func(string) (*graph.Results, error) {
				return queueCanned(), nil
			}}
			mux, _ := newTestMux(reader, &fakeProposalService{}, &fakeCheckpointService{})

			req := httptest.NewRequest(http.MethodGet, "/api/proposals"+tt.query, nil)
			rec := httptest.NewRecorder()
			mux.ServeHTTP(rec, req)

			if rec.Code != http.StatusOK {
				t.Fatalf("status = %d, want 200 (body: %s)", rec.Code, rec.Body.String())
			}

			body := decodeJSONObject(t, rec.Body.Bytes())
			proposals := asSlice(t, body["proposals"], "proposals")
			if len(proposals) != len(tt.wantIDs) {
				t.Fatalf("got %d proposals, want %d (body: %s)", len(proposals), len(tt.wantIDs), rec.Body.String())
			}

			seen := map[string]bool{}
			for _, raw := range proposals {
				entry, ok := raw.(map[string]any)
				if !ok {
					t.Fatalf("proposal entry = %#v, want a JSON object", raw)
				}
				id, _ := entry["id"].(string)
				want, ok := tt.wantIDs[id]
				if !ok {
					t.Errorf("unexpected proposal id %q in response", id)
					continue
				}
				seen[id] = true
				if got := entry["kind"]; got != want.kind {
					t.Errorf("proposal %q kind = %v, want %q", id, got, want.kind)
				}
				if got := entry["status"]; got != want.status {
					t.Errorf("proposal %q status = %v, want %q", id, got, want.status)
				}
				if got := entry["term"]; got != want.term {
					t.Errorf("proposal %q term = %v, want %q", id, got, want.term)
				}
				if got := numString(entry["docFrequency"]); got != want.freq {
					t.Errorf("proposal %q docFrequency = %v, want %q", id, got, want.freq)
				}
			}
			for id := range tt.wantIDs {
				if !seen[id] {
					t.Errorf("expected proposal id %q missing from response", id)
				}
			}

			// Requirement "Reads use the staging-inclusive path only": the
			// queue endpoint must never fall back to the core-dataset
			// Select for its listing read.
			if len(reader.selectCalls) != 0 {
				t.Errorf("queue handler called core Select %d times, want 0 (staging-inclusive path only)", len(reader.selectCalls))
			}
			if len(reader.selectRawCalls) == 0 {
				t.Errorf("queue handler never called SelectRaw")
			}
		})
	}
}

// --- 2 & 3. Detail payload shape + 404 on unknown id (task 5.5 scenarios
// 2, 3) ---

func TestProposalDetail_ReturnsShapeForKnownID(t *testing.T) {
	reader := newDetailReader()
	mux, _ := newTestMux(reader, &fakeProposalService{}, &fakeCheckpointService{})

	req := httptest.NewRequest(http.MethodGet, "/api/proposals/"+detailKnownID, nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 (body: %s)", rec.Code, rec.Body.String())
	}

	body := decodeJSONObject(t, rec.Body.Bytes())
	for _, key := range []string{"triples", "evidence", "neighborhood"} {
		v, ok := body[key]
		if !ok {
			t.Fatalf("response missing key %q (body: %s)", key, rec.Body.String())
		}
		if arr := asSlice(t, v, key); len(arr) == 0 {
			t.Errorf("response %q is empty, want at least one entry", key)
		}
	}

	raw := rec.Body.String()
	for _, want := range []string{
		"https://w3id.org/msr-kg/ontology#solubility", // triples subject
		"DatatypeProperty",                            // triples object (row 1)
		"ORNL-TM-2316",                                // evidence citedIn
		"120", "145",                                  // evidence offsets
		"Salt", // neighborhood object
	} {
		if !strings.Contains(raw, want) {
			t.Errorf("response body missing expected content %q (body: %s)", want, raw)
		}
	}
}

func TestProposalDetail_UnknownIDReturns404(t *testing.T) {
	reader := newDetailReader()
	mux, _ := newTestMux(reader, &fakeProposalService{}, &fakeCheckpointService{})

	req := httptest.NewRequest(http.MethodGet, "/api/proposals/"+detailUnknownID, nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404 (body: %s)", rec.Code, rec.Body.String())
	}
}

// --- 4. 405 on wrong method for a proposal route (task 5.5 scenario 4) ---

func TestProposalsRoute_WrongMethodIs405AndDoesNotMutate(t *testing.T) {
	reader := newDetailReader()
	prop := &fakeProposalService{}
	mux, _ := newTestMux(reader, prop, &fakeCheckpointService{})

	req := httptest.NewRequest(http.MethodDelete, "/api/proposals/"+detailKnownID, nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusMethodNotAllowed {
		t.Fatalf("status = %d, want 405 (body: %s)", rec.Code, rec.Body.String())
	}
	if got := rec.Header().Get("Allow"); got == "" {
		t.Errorf("Allow header missing on 405 response")
	}
	if prop.approveCalls != 0 || prop.rejectCalls != 0 || prop.editCalls != 0 {
		t.Errorf("service calls = approve:%d reject:%d edit:%d, want all 0 (no mutation on 405)",
			prop.approveCalls, prop.rejectCalls, prop.editCalls)
	}
}

// --- 5. 400 on malformed edit body (task 5.5 scenario 5) ---

func TestProposalEditGraph_MalformedBodyReturns400(t *testing.T) {
	tests := []struct {
		name string
		body string
	}{
		{"invalid JSON", `not json`},
		{"missing triples field", `{}`},
		{"triples wrong type", `{"triples": 123}`},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			prop := &fakeProposalService{}
			mux, _ := newTestMux(&fakeProposalReader{}, prop, &fakeCheckpointService{})

			req := httptest.NewRequest(http.MethodPut, "/api/proposals/"+detailKnownID+"/graph", strings.NewReader(tt.body))
			rec := httptest.NewRecorder()
			mux.ServeHTTP(rec, req)

			if rec.Code != http.StatusBadRequest {
				t.Fatalf("status = %d, want 400 (body: %s)", rec.Code, rec.Body.String())
			}
			if prop.editCalls != 0 {
				t.Errorf("Edit called %d times, want 0 on malformed body", prop.editCalls)
			}
		})
	}
}

func TestProposalEditGraph_ValidBodyReturns200AndCallsEdit(t *testing.T) {
	prop := &fakeProposalService{}
	mux, _ := newTestMux(&fakeProposalReader{}, prop, &fakeCheckpointService{})

	body := `{"triples": "msr:solubility a owl:DatatypeProperty ."}`
	req := httptest.NewRequest(http.MethodPut, "/api/proposals/"+detailKnownID+"/graph", strings.NewReader(body))
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 (body: %s)", rec.Code, rec.Body.String())
	}
	if prop.editCalls != 1 {
		t.Errorf("Edit called %d times, want 1", prop.editCalls)
	}
}

// --- 6. SHACL rejection surfaces as a typed 422 error (task 5.5 scenario
// 6) ---

func TestProposalApprove_SHACLValidationErrorReturns422StructuredBody(t *testing.T) {
	validationErr := &graph.ValidationError{
		Report: `[] a sh:ValidationReport ; sh:conforms false .`,
		Violations: []graph.Violation{
			{
				FocusNode:                 "https://w3id.org/msr-kg/data#test-solubility",
				SourceConstraintComponent: "sh:MinCountConstraintComponent",
				Message:                   "Less than 1 values on msr:forProperty",
			},
		},
	}
	prop := &fakeProposalService{approveFn: func(string, proposal.ApproveRequest) error {
		return validationErr
	}}
	mux, _ := newTestMux(&fakeProposalReader{}, prop, &fakeCheckpointService{})

	body := `{"reviewer":"alice@example.com","timestamp":"2026-07-20T12:00:00Z"}`
	req := httptest.NewRequest(http.MethodPost, "/api/proposals/"+detailKnownID+"/approve", strings.NewReader(body))
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnprocessableEntity {
		t.Fatalf("status = %d, want 422 (body: %s)", rec.Code, rec.Body.String())
	}

	raw := rec.Body.String()
	if strings.Contains(raw, "goroutine") || strings.Contains(raw, ".go:") {
		t.Errorf("response body looks like a raw stack trace, not a structured error: %s", raw)
	}

	respBody := decodeJSONObject(t, rec.Body.Bytes())
	if got, _ := respBody["error"].(string); got != "validation" {
		t.Errorf(`response "error" field = %q, want "validation" (body: %s)`, got, raw)
	}
	for _, want := range []string{"test-solubility", "Less than 1 values on msr:forProperty"} {
		if !strings.Contains(raw, want) {
			t.Errorf("response body missing violation detail %q (body: %s)", want, raw)
		}
	}
	if prop.approveCalls != 1 {
		t.Errorf("Approve called %d times, want 1", prop.approveCalls)
	}
}

// --- 7. Sentinel error -> status code mapping (task 5.5 scenario 7) ---

func TestProposalApprove_NotFoundReturns404(t *testing.T) {
	prop := &fakeProposalService{approveFn: func(string, proposal.ApproveRequest) error {
		return proposal.ErrNotFound
	}}
	mux, _ := newTestMux(&fakeProposalReader{}, prop, &fakeCheckpointService{})

	body := `{"reviewer":"alice@example.com","timestamp":"2026-07-20T12:00:00Z"}`
	req := httptest.NewRequest(http.MethodPost, "/api/proposals/"+detailUnknownID+"/approve", strings.NewReader(body))
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404 (body: %s)", rec.Code, rec.Body.String())
	}
}

func TestProposalApprove_InvalidTransitionReturns409(t *testing.T) {
	prop := &fakeProposalService{approveFn: func(string, proposal.ApproveRequest) error {
		return proposal.ErrInvalidTransition
	}}
	mux, _ := newTestMux(&fakeProposalReader{}, prop, &fakeCheckpointService{})

	body := `{"reviewer":"alice@example.com","timestamp":"2026-07-20T12:00:00Z"}`
	req := httptest.NewRequest(http.MethodPost, "/api/proposals/"+detailKnownID+"/approve", strings.NewReader(body))
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusConflict {
		t.Fatalf("status = %d, want 409 (body: %s)", rec.Code, rec.Body.String())
	}
}

func TestProposalApprove_Success200(t *testing.T) {
	prop := &fakeProposalService{}
	mux, _ := newTestMux(&fakeProposalReader{}, prop, &fakeCheckpointService{})

	body := `{"reviewer":"alice@example.com","timestamp":"2026-07-20T12:00:00Z"}`
	req := httptest.NewRequest(http.MethodPost, "/api/proposals/"+detailKnownID+"/approve", strings.NewReader(body))
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 (body: %s)", rec.Code, rec.Body.String())
	}
	if prop.approveCalls != 1 {
		t.Errorf("Approve called %d times, want 1", prop.approveCalls)
	}
}

func TestProposalReject_NotFoundReturns404(t *testing.T) {
	prop := &fakeProposalService{rejectFn: func(string) error {
		return proposal.ErrNotFound
	}}
	mux, _ := newTestMux(&fakeProposalReader{}, prop, &fakeCheckpointService{})

	req := httptest.NewRequest(http.MethodPost, "/api/proposals/"+detailUnknownID+"/reject", nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404 (body: %s)", rec.Code, rec.Body.String())
	}
}

func TestProposalReject_Success200(t *testing.T) {
	prop := &fakeProposalService{}
	mux, _ := newTestMux(&fakeProposalReader{}, prop, &fakeCheckpointService{})

	req := httptest.NewRequest(http.MethodPost, "/api/proposals/"+detailKnownID+"/reject", nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 (body: %s)", rec.Code, rec.Body.String())
	}
	if prop.rejectCalls != 1 {
		t.Errorf("Reject called %d times, want 1", prop.rejectCalls)
	}
}

// --- Chat/health routes unaffected by the new registrations ---

func TestChatAndHealthzUnaffectedByProposalRoutes(t *testing.T) {
	mux, stub := newTestMux(&fakeProposalReader{}, &fakeProposalService{}, &fakeCheckpointService{})

	req := httptest.NewRequest(http.MethodPost, "/api/chat", strings.NewReader(`{}`))
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Errorf("/api/chat status = %d, want 200 (body: %s)", rec.Code, rec.Body.String())
	}
	if stub.calls != 1 {
		t.Errorf("chat stub calls = %d, want 1", stub.calls)
	}

	req = httptest.NewRequest(http.MethodGet, "/healthz", nil)
	rec = httptest.NewRecorder()
	mux.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK {
		t.Errorf("/healthz status = %d, want 200 (body: %s)", rec.Code, rec.Body.String())
	}
	if rec.Body.String() != "ok" {
		t.Errorf("/healthz body = %q, want %q", rec.Body.String(), "ok")
	}
}
