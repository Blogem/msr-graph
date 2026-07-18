package graph_test

// Unit tests for internal/graph (task 6.2). These run unconditionally -- no
// GraphDB, no env dependence -- using an injected *http.Client with a fake
// http.RoundTripper for dependency injection, per
// openspec/changes/bootstrap-graph-infra/specs/core-dataset-access/spec.md.

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"testing"

	"github.com/blogem/msr-graph/internal/graph"
)

// fakeRoundTripper is a minimal http.RoundTripper double that records what
// the client sends (or confirms it never sends anything) without touching a
// real GraphDB.
type fakeRoundTripper struct {
	calls    int
	lastReq  *http.Request
	lastBody []byte

	statusCode int
	body       string
	err        error
}

func (f *fakeRoundTripper) RoundTrip(req *http.Request) (*http.Response, error) {
	f.calls++
	f.lastReq = req
	if req.Body != nil {
		b, _ := io.ReadAll(req.Body)
		f.lastBody = b
		req.Body = io.NopCloser(bytes.NewReader(b))
	}
	if f.err != nil {
		return nil, f.err
	}
	status := f.statusCode
	if status == 0 {
		status = http.StatusOK
	}
	body := f.body
	if body == "" {
		body = `{"head":{"vars":[]},"results":{"bindings":[]}}`
	}
	return &http.Response{
		StatusCode: status,
		Status:     http.StatusText(status),
		Body:       io.NopCloser(strings.NewReader(body)),
		Header:     http.Header{"Content-Type": []string{"application/sparql-results+json"}},
		Request:    req,
	}, nil
}

func newTestClient(rt *fakeRoundTripper) *graph.Client {
	return graph.New("http://graphdb.invalid:7200", "msr", &http.Client{Transport: rt})
}

// datasetParams extracts the default-graph-uri / named-graph-uri values from
// a captured request. It checks both the URL query string and a
// form-encoded body since the pinned contract fixes the protocol parameter
// names, not which HTTP method/encoding the client uses to send them.
func datasetParams(req *http.Request, body []byte) (defaultGraphs, namedGraphs []string) {
	values := req.URL.Query()
	if len(values["default-graph-uri"]) == 0 && len(values["named-graph-uri"]) == 0 && len(body) > 0 {
		if v, err := url.ParseQuery(string(body)); err == nil {
			values = v
		}
	}
	return values["default-graph-uri"], values["named-graph-uri"]
}

func sameSet(got, want []string) bool {
	if len(got) != len(want) {
		return false
	}
	counts := make(map[string]int, len(want))
	for _, w := range want {
		counts[w]++
	}
	for _, g := range got {
		counts[g]--
	}
	for _, c := range counts {
		if c != 0 {
			return false
		}
	}
	return true
}

var coreGraphIRIs = []string{string(graph.Ontology), string(graph.Data), string(graph.Vocab)}

// TestSelect_DatasetClauseGuard pins core-dataset-access spec.md's "Smuggled
// FROM is a loud error" and "Case variations are caught" scenarios, plus the
// task 6.2 requirement that clean queries (no FROM) are accepted and reach
// the transport.
func TestSelect_DatasetClauseGuard(t *testing.T) {
	tests := []struct {
		name       string
		query      string
		wantReject bool
	}{
		{"plain select, no dataset clause", "SELECT * WHERE { ?s ?p ?o }", false},
		{"select with GRAPH pattern, no FROM", "SELECT * WHERE { GRAPH ?g { ?s ?p ?o } }", false},
		{"uppercase FROM", "SELECT * FROM <urn:msr:data> WHERE { ?s ?p ?o }", true},
		{"lowercase from", "select * from <urn:msr:data> where { ?s ?p ?o }", true},
		{"mixed-case From", "SELECT * From <urn:msr:data> WHERE { ?s ?p ?o }", true},
		{"uppercase FROM NAMED", "SELECT * FROM NAMED <urn:msr:staging> WHERE { ?s ?p ?o }", true},
		{"lowercase from named", "select * from named <urn:msr:staging> where { ?s ?p ?o }", true},
		{"mixed-case From Named", "SELECT * From Named <urn:msr:staging> WHERE { ?s ?p ?o }", true},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			rt := &fakeRoundTripper{}
			c := newTestClient(rt)

			_, err := c.Select(context.Background(), tc.query)

			if tc.wantReject {
				if err == nil {
					t.Fatalf("expected Select to reject query %q, got nil error", tc.query)
				}
				if !strings.Contains(err.Error(), "SelectRaw") {
					t.Errorf("expected rejection error to mention SelectRaw, got: %v", err)
				}
				if rt.calls != 0 {
					t.Errorf("expected rejection to happen without any HTTP call, got %d calls", rt.calls)
				}
				return
			}

			if err != nil {
				t.Fatalf("unexpected error for clean query %q: %v", tc.query, err)
			}
			if rt.calls != 1 {
				t.Errorf("expected clean query to reach the transport, got %d calls", rt.calls)
			}
		})
	}
}

// TestSelectRaw_AllowsDatasetClauses confirms SelectRaw is the unguarded
// escape hatch: it must not reject queries carrying their own FROM clause.
func TestSelectRaw_AllowsDatasetClauses(t *testing.T) {
	rt := &fakeRoundTripper{}
	c := newTestClient(rt)

	_, err := c.SelectRaw(context.Background(), "SELECT * FROM <urn:msr:staging> WHERE { ?s ?p ?o }")
	if err != nil {
		t.Fatalf("SelectRaw must not reject queries with FROM clauses: %v", err)
	}
	if rt.calls != 1 {
		t.Fatalf("expected SelectRaw to reach the transport, got %d calls", rt.calls)
	}
}

// TestSelect_SendsCoreDatasetProtocolParams pins D1 / core-dataset-access
// spec.md's core requirement: the three core graphs are sent as BOTH
// default-graph-uri and named-graph-uri protocol parameters, three each.
func TestSelect_SendsCoreDatasetProtocolParams(t *testing.T) {
	rt := &fakeRoundTripper{}
	c := newTestClient(rt)

	if _, err := c.Select(context.Background(), "SELECT * WHERE { ?s ?p ?o }"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if rt.calls != 1 {
		t.Fatalf("expected exactly one HTTP call, got %d", rt.calls)
	}

	defaults, named := datasetParams(rt.lastReq, rt.lastBody)
	if len(defaults) != 3 {
		t.Errorf("expected exactly 3 default-graph-uri params, got %d (%v)", len(defaults), defaults)
	}
	if len(named) != 3 {
		t.Errorf("expected exactly 3 named-graph-uri params, got %d (%v)", len(named), named)
	}
	if !sameSet(defaults, coreGraphIRIs) {
		t.Errorf("default-graph-uri = %v, want the three core graphs %v", defaults, coreGraphIRIs)
	}
	if !sameSet(named, coreGraphIRIs) {
		t.Errorf("named-graph-uri = %v, want the three core graphs %v", named, coreGraphIRIs)
	}
}

// TestSelectRaw_SendsNoDatasetProtocolParams pins the contrast half of the
// same requirement: SelectRaw must send neither protocol parameter.
func TestSelectRaw_SendsNoDatasetProtocolParams(t *testing.T) {
	rt := &fakeRoundTripper{}
	c := newTestClient(rt)

	if _, err := c.SelectRaw(context.Background(), "SELECT * WHERE { ?s ?p ?o }"); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if rt.calls != 1 {
		t.Fatalf("expected exactly one HTTP call, got %d", rt.calls)
	}

	defaults, named := datasetParams(rt.lastReq, rt.lastBody)
	if len(defaults) != 0 {
		t.Errorf("SelectRaw must send no default-graph-uri params, got %v", defaults)
	}
	if len(named) != 0 {
		t.Errorf("SelectRaw must send no named-graph-uri params, got %v", named)
	}
}

// TestPutGraph_RefusesUnknownIRI pins "Unknown graph IRI refused": PutGraph
// with an IRI outside {Ontology,Data,Vocab,Staging} must fail without
// sending any request to GraphDB.
func TestPutGraph_RefusesUnknownIRI(t *testing.T) {
	rt := &fakeRoundTripper{}
	c := newTestClient(rt)

	err := c.PutGraph(context.Background(), graph.GraphIRI("urn:msr:not-a-real-graph"), []byte("<urn:s> <urn:p> <urn:o> ."))
	if err == nil {
		t.Fatal("expected an error for a graph IRI outside the exported constant set")
	}
	if rt.calls != 0 {
		t.Errorf("expected no HTTP request for an unknown graph IRI, got %d calls", rt.calls)
	}
}

// TestPutGraph_AcceptsKnownIRIs is the contrast case: every exported graph
// IRI constant must be accepted and reach the transport.
func TestPutGraph_AcceptsKnownIRIs(t *testing.T) {
	for _, iri := range []graph.GraphIRI{graph.Ontology, graph.Data, graph.Vocab, graph.Staging} {
		t.Run(string(iri), func(t *testing.T) {
			rt := &fakeRoundTripper{statusCode: http.StatusNoContent}
			c := newTestClient(rt)

			if err := c.PutGraph(context.Background(), iri, []byte("<urn:s> <urn:p> <urn:o> .")); err != nil {
				t.Fatalf("unexpected error for known graph IRI %s: %v", iri, err)
			}
			if rt.calls != 1 {
				t.Errorf("expected known graph IRI %s to reach the transport, got %d calls", iri, rt.calls)
			}
		})
	}
}

// TestPutGraph_TransportErrorPropagates is a small sanity check that
// PutGraph surfaces transport failures rather than swallowing them,
// exercised via the same fake RoundTripper DI seam.
func TestPutGraph_TransportErrorPropagates(t *testing.T) {
	rt := &fakeRoundTripper{err: fmt.Errorf("boom")}
	c := newTestClient(rt)

	if err := c.PutGraph(context.Background(), graph.Data, []byte("<urn:s> <urn:p> <urn:o> .")); err == nil {
		t.Fatal("expected the transport error to propagate")
	}
}
