package graph_test

// Task 1.5 (apply-ontology-changes): unit tests for the repository-level
// graph ops -- ExportRepo, ClearRepo, ImportRepo -- and the ProposalGraph
// IRI builder (design D4). These are pure unit tests against an
// httptest.Server double, following the style of validation_error_test.go:
// no live GraphDB, no env dependence.
//
// This file references graph.ExportRepo, graph.ClearRepo, graph.ImportRepo,
// and graph.ProposalGraph, which do not exist until the coder's parallel
// branch lands task 1.1-1.4 -- so, until merge, this file (and therefore
// this whole package's test binary, per Go's per-package compilation) does
// not compile. This is expected pass-1 state.

import (
	"bytes"
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"

	"github.com/blogem/msr-graph/internal/graph"
)

// recordedRequest captures the one HTTP request a recording server's
// handler received, so assertions can inspect method/path/query/headers/
// body without a live GraphDB.
type recordedRequest struct {
	method      string
	path        string
	rawQuery    string
	accept      string
	contentType string
	body        []byte
}

// newRecordingServer returns an httptest.Server that records the request it
// receives and replies with statusCode/responseBody. Each call builds a
// fresh server and recorder, so tests never share state.
func newRecordingServer(t *testing.T, statusCode int, responseBody string) (*httptest.Server, *recordedRequest) {
	t.Helper()
	rec := &recordedRequest{}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		rec.method = r.Method
		rec.path = r.URL.Path
		rec.rawQuery = r.URL.RawQuery
		rec.accept = r.Header.Get("Accept")
		rec.contentType = r.Header.Get("Content-Type")
		rec.body = body
		w.WriteHeader(statusCode)
		if responseBody != "" {
			_, _ = w.Write([]byte(responseBody))
		}
	}))
	t.Cleanup(srv.Close)
	return srv, rec
}

const sampleTrig = `<urn:msr:data> {
    <urn:s> <urn:p> <urn:o> .
}`

// TestExportRepo_IssuesGetWithTrigAccept pins design D4's Export
// primitive: GET /repositories/{repo}/statements with an
// Accept: application/x-trig header, returning the response body
// verbatim.
func TestExportRepo_IssuesGetWithTrigAccept(t *testing.T) {
	srv, rec := newRecordingServer(t, http.StatusOK, sampleTrig)
	c := graph.New(srv.URL, "msr", srv.Client())

	got, err := c.ExportRepo(context.Background())
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if rec.method != http.MethodGet {
		t.Errorf("method = %q, want GET", rec.method)
	}
	if rec.path != "/repositories/msr/statements" {
		t.Errorf("path = %q, want /repositories/msr/statements", rec.path)
	}
	if rec.accept != "application/x-trig" {
		t.Errorf("Accept header = %q, want application/x-trig", rec.accept)
	}
	if !bytes.Equal(got, []byte(sampleTrig)) {
		t.Errorf("ExportRepo body = %q, want %q", got, sampleTrig)
	}
}

// TestExportRepo_NonSuccessStatusIsError confirms a non-2xx response is
// surfaced as a non-nil error rather than a partial/garbage export.
func TestExportRepo_NonSuccessStatusIsError(t *testing.T) {
	srv, _ := newRecordingServer(t, http.StatusInternalServerError, "boom")
	c := graph.New(srv.URL, "msr", srv.Client())

	if _, err := c.ExportRepo(context.Background()); err == nil {
		t.Fatal("expected an error for a non-2xx ExportRepo response")
	}
}

// TestClearRepo_IssuesContextlessDelete pins design D4's Clear primitive:
// DELETE /repositories/{repo}/statements with NO subject/predicate/
// object/context query parameters -- a context-less DELETE empties the
// whole repository, unlike a scoped Graph Store DELETE.
func TestClearRepo_IssuesContextlessDelete(t *testing.T) {
	srv, rec := newRecordingServer(t, http.StatusNoContent, "")
	c := graph.New(srv.URL, "msr", srv.Client())

	if err := c.ClearRepo(context.Background()); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if rec.method != http.MethodDelete {
		t.Errorf("method = %q, want DELETE", rec.method)
	}
	if rec.path != "/repositories/msr/statements" {
		t.Errorf("path = %q, want /repositories/msr/statements", rec.path)
	}
	if rec.rawQuery != "" {
		t.Errorf("RawQuery = %q, want empty (context-less DELETE: no subj/pred/obj/context params)", rec.rawQuery)
	}
}

// TestClearRepo_NonSuccessStatusIsError confirms a non-2xx response is
// surfaced as an error.
func TestClearRepo_NonSuccessStatusIsError(t *testing.T) {
	srv, _ := newRecordingServer(t, http.StatusInternalServerError, "boom")
	c := graph.New(srv.URL, "msr", srv.Client())

	if err := c.ClearRepo(context.Background()); err == nil {
		t.Fatal("expected an error for a non-2xx ClearRepo response")
	}
}

// TestImportRepo_IssuesPostWithTrigContentType pins design D4's Import
// primitive: POST /repositories/{repo}/statements with a
// Content-Type: application/x-trig header and the TriG bytes sent as the
// raw request body (no form-encoding).
func TestImportRepo_IssuesPostWithTrigContentType(t *testing.T) {
	trig := []byte(sampleTrig)
	srv, rec := newRecordingServer(t, http.StatusNoContent, "")
	c := graph.New(srv.URL, "msr", srv.Client())

	if err := c.ImportRepo(context.Background(), trig); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if rec.method != http.MethodPost {
		t.Errorf("method = %q, want POST", rec.method)
	}
	if rec.path != "/repositories/msr/statements" {
		t.Errorf("path = %q, want /repositories/msr/statements", rec.path)
	}
	if rec.contentType != "application/x-trig" {
		t.Errorf("Content-Type header = %q, want application/x-trig", rec.contentType)
	}
	if !bytes.Equal(rec.body, trig) {
		t.Errorf("request body = %q, want %q", rec.body, trig)
	}
}

// TestImportRepo_NonSuccessStatusIsError confirms a non-2xx response (e.g.
// malformed TriG rejected by GraphDB) is surfaced as an error.
func TestImportRepo_NonSuccessStatusIsError(t *testing.T) {
	trig := []byte(sampleTrig)
	srv, _ := newRecordingServer(t, http.StatusBadRequest, "malformed trig")
	c := graph.New(srv.URL, "msr", srv.Client())

	if err := c.ImportRepo(context.Background(), trig); err == nil {
		t.Fatal("expected an error for a non-2xx ImportRepo response")
	}
}

// TestPutProposalGraph_IssuesGraphStorePutWithTurtleBody pins
// PutProposalGraph's request shape (the injection-safe replacement for
// splicing a proposal edit into a SPARQL UPDATE string, per the
// security-review finding on Engine.Edit): a PUT to the Graph Store
// Protocol endpoint, ?graph=urn:msr:proposal/{id}, Content-Type:
// text/turtle, and turtle sent verbatim as the raw request body -- never
// form-encoded, never embedded in a query string GraphDB would parse as
// SPARQL.
func TestPutProposalGraph_IssuesGraphStorePutWithTurtleBody(t *testing.T) {
	turtle := []byte(`@prefix msr: <https://w3id.org/msr-kg/ontology#> .
msr:solubility a msr:PhysicalProperty .`)
	srv, rec := newRecordingServer(t, http.StatusNoContent, "")
	c := graph.New(srv.URL, "msr", srv.Client())

	if err := c.PutProposalGraph(context.Background(), "property-solubility", turtle); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if rec.method != http.MethodPut {
		t.Errorf("method = %q, want PUT", rec.method)
	}
	if rec.path != "/repositories/msr/rdf-graphs/service" {
		t.Errorf("path = %q, want /repositories/msr/rdf-graphs/service", rec.path)
	}
	query, err := url.ParseQuery(rec.rawQuery)
	if err != nil {
		t.Fatalf("parsing recorded query %q: %v", rec.rawQuery, err)
	}
	if got := query.Get("graph"); got != "urn:msr:proposal/property-solubility" {
		t.Errorf("graph query param = %q, want %q", got, "urn:msr:proposal/property-solubility")
	}
	if rec.contentType != "text/turtle" {
		t.Errorf("Content-Type header = %q, want text/turtle", rec.contentType)
	}
	if !bytes.Equal(rec.body, turtle) {
		t.Errorf("request body = %q, want %q (verbatim, no injection surface)", rec.body, turtle)
	}
}

// TestPutProposalGraph_NonSuccessStatusIsError confirms a non-2xx
// response (e.g. malformed turtle, or a SHACL rejection) is surfaced as
// an error, using detectValidationError the same way PutGraph does.
func TestPutProposalGraph_NonSuccessStatusIsError(t *testing.T) {
	srv, _ := newRecordingServer(t, http.StatusBadRequest, "malformed turtle")
	c := graph.New(srv.URL, "msr", srv.Client())

	if err := c.PutProposalGraph(context.Background(), "property-solubility", []byte("not turtle {{{")); err == nil {
		t.Fatal("expected an error for a non-2xx PutProposalGraph response")
	}
}

// TestProposalGraph_BuildsDeterministicIRI pins the ProposalGraph IRI
// builder: it must deterministically map an id to
// urn:msr:proposal/{id}, with no network call involved.
func TestProposalGraph_BuildsDeterministicIRI(t *testing.T) {
	tests := []struct {
		id   string
		want graph.GraphIRI
	}{
		{"property-solubility", "urn:msr:proposal/property-solubility"},
		{"class-graphite", "urn:msr:proposal/class-graphite"},
		{"individual-flibe-density", "urn:msr:proposal/individual-flibe-density"},
	}

	for _, tc := range tests {
		t.Run(tc.id, func(t *testing.T) {
			if got := graph.ProposalGraph(tc.id); got != tc.want {
				t.Errorf("ProposalGraph(%q) = %q, want %q", tc.id, got, tc.want)
			}
		})
	}
}
