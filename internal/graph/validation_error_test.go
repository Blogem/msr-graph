package graph_test

// Task 7.9: pure unit test for the write-path validation-error typing
// (design D5, task 5.1). This is NOT gated behind requireGraphDB -- it
// must pass without a live GraphDB, using an httptest.Server double that
// stands in for RDF4J/GraphDB's response to a SHACL-rejected commit.
//
// Pinned contract (from the parallel implementer): an exported type
// graph.ValidationError in package graph, implementing error, detectable
// via errors.As(err, &ve) with `var ve *graph.ValidationError`, carrying
// the failing constraint(s) + focus node(s) + a raw Report. Since the
// exact parse-out field names are not finalized, this test asserts only
// on the behavior the contract explicitly promises: err IS a
// *graph.ValidationError (errors.As succeeds), and the focus-node /
// constraint strings appear in the error's detail (ve.Error()) -- not on
// any specific struct field layout.
//
// This file references graph.ValidationError, which does not exist until
// the coder's parallel branch lands task 5.1 -- so, until merge, this
// file (and therefore this whole package's test binary, per Go's
// per-package compilation) does not compile. This is expected pass-1
// state: see this change's tester handoff report. All other
// shacl_*_integration_test.go files in this package deliberately avoid
// referencing graph.ValidationError so that shape-behavior coverage is
// not entangled with this type's landing.

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/blogem/msr-graph/internal/graph"
)

// simulatedValidationReportTTL is a minimal, realistic RDF4J
// sh:ValidationReport for a MinCount violation on
// msrd:test-measurement-shacl-7-9's prov:wasDerivedFrom -- the shape of
// report RDF4J/GraphDB emits when a SHACL-enabled repository rejects a
// commit (design D5's "RDF4J emits an HTTP error carrying a
// sh:ValidationReport").
const simulatedValidationReportTTL = `
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix msrd: <https://w3id.org/msr-kg/data#> .
@prefix prov: <http://www.w3.org/ns/prov#> .

[] a sh:ValidationReport ;
    sh:conforms false ;
    sh:result [
        a sh:ValidationResult ;
        sh:focusNode msrd:test-measurement-shacl-7-9 ;
        sh:resultSeverity sh:Violation ;
        sh:sourceConstraintComponent sh:MinCountConstraintComponent ;
        sh:resultPath prov:wasDerivedFrom ;
        sh:resultMessage "Less than 1 values on msrd:test-measurement-shacl-7-9->prov:wasDerivedFrom" ;
    ] .
`

// newValidationReportServer returns an httptest.Server that responds to
// every request with simulatedValidationReportTTL as a text/turtle body
// under a plain 500 status. Per spec.md's "Rejection carries actionable
// detail" scenario ("classifiable as a validation failure (not a generic
// 5xx)"), the double deliberately uses a non-specific 5xx status to prove
// the classification looks at the response body, not merely the status
// code.
func newValidationReportServer(t *testing.T) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/turtle")
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte(simulatedValidationReportTTL))
	}))
}

// TestUpdate_ClassifiesSHACLRejectionAsValidationError drives a SPARQL
// Update through the client's write path against the double and asserts
// the returned error is classifiable via errors.As as *graph.ValidationError
// and its detail names the focus node and failing constraint.
func TestUpdate_ClassifiesSHACLRejectionAsValidationError(t *testing.T) {
	srv := newValidationReportServer(t)
	defer srv.Close()

	c := graph.New(srv.URL, "msr", srv.Client())

	err := c.Update(context.Background(), `INSERT DATA { GRAPH <urn:msr:data> { <urn:s> <urn:p> <urn:o> } }`)
	if err == nil {
		t.Fatal("expected an error for a simulated SHACL-rejected Update")
	}

	var ve *graph.ValidationError
	if !errors.As(err, &ve) {
		t.Fatalf("expected errors.As to find a *graph.ValidationError in the Update error chain, got: %v", err)
	}
	if !strings.Contains(ve.Error(), "test-measurement-shacl-7-9") {
		t.Errorf("ValidationError.Error() = %q, want it to mention the focus node test-measurement-shacl-7-9", ve.Error())
	}
	if !strings.Contains(ve.Error(), "MinCountConstraintComponent") {
		t.Errorf("ValidationError.Error() = %q, want it to mention the failing constraint MinCountConstraintComponent", ve.Error())
	}
}

// TestPutGraph_ClassifiesSHACLRejectionAsValidationError is the same
// classification check for the Graph Store Protocol PUT write path
// (design D5 names both Client.Update and Client.PutGraph).
func TestPutGraph_ClassifiesSHACLRejectionAsValidationError(t *testing.T) {
	srv := newValidationReportServer(t)
	defer srv.Close()

	c := graph.New(srv.URL, "msr", srv.Client())

	err := c.PutGraph(context.Background(), graph.Data, []byte("<urn:s> <urn:p> <urn:o> ."))
	if err == nil {
		t.Fatal("expected an error for a simulated SHACL-rejected PutGraph")
	}

	var ve *graph.ValidationError
	if !errors.As(err, &ve) {
		t.Fatalf("expected errors.As to find a *graph.ValidationError in the PutGraph error chain, got: %v", err)
	}
	if !strings.Contains(ve.Error(), "test-measurement-shacl-7-9") {
		t.Errorf("ValidationError.Error() = %q, want it to mention the focus node test-measurement-shacl-7-9", ve.Error())
	}
}

// TestValidationError_NotConfusedWithGenericTransportError is a contrast
// check: a plain non-2xx response with NO validation-report body must
// NOT be classified as a *graph.ValidationError, else every ordinary
// write failure would look like a SHACL rejection.
func TestValidationError_NotConfusedWithGenericTransportError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "malformed SPARQL update", http.StatusBadRequest)
	}))
	defer srv.Close()

	c := graph.New(srv.URL, "msr", srv.Client())

	err := c.Update(context.Background(), `not even sparql`)
	if err == nil {
		t.Fatal("expected an error for a rejected Update")
	}
	var ve *graph.ValidationError
	if errors.As(err, &ve) {
		t.Fatalf("expected a generic (non-validation) error for a non-SHACL 400, got *graph.ValidationError: %v", ve)
	}
}
