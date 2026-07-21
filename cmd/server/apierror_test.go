package main

// Regression test for a security-review finding: mapEngineError's
// default (500) branch must never echo an unclassified error's raw
// text to the client. An unclassified error reaching that branch is
// typically an unwrapped transport/parse failure straight from
// graph.Client, which can carry raw upstream GraphDB response content
// (parse errors, offending query text, endpoint/repo detail) -- handing
// that back to an unauthenticated caller both leaks internal detail and
// hands back an injection oracle. See apierror.go's mapEngineError
// doc-comment.

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestMapEngineError_GenericErrorDoesNotLeakUpstreamDetail(t *testing.T) {
	const upstreamSecret = "SECRET-UPSTREAM-DETAIL: GraphDB rejected malformed SPARQL near token '???'"

	prop := &fakeProposalService{rejectFn: func(string) error {
		return errFakeUpstream{upstreamSecret}
	}}
	mux, _ := newTestMux(&fakeProposalReader{}, prop, &fakeCheckpointService{})

	req := httptest.NewRequest(http.MethodPost, "/api/proposals/property-solubility/reject", nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusInternalServerError)
	}

	body := rec.Body.String()
	if strings.Contains(body, upstreamSecret) {
		t.Fatalf("500 response body leaked upstream error detail: %s", body)
	}
	if strings.Contains(body, "SECRET-UPSTREAM-DETAIL") {
		t.Fatalf("500 response body leaked upstream sentinel substring: %s", body)
	}

	var got apiError
	if err := json.Unmarshal(rec.Body.Bytes(), &got); err != nil {
		t.Fatalf("decode response body: %v (body: %s)", err, body)
	}
	if got.Error != "internal" {
		t.Errorf("error = %q, want %q", got.Error, "internal")
	}
	if got.Message != internalErrorMessage {
		t.Errorf("message = %q, want %q", got.Message, internalErrorMessage)
	}
}

// errFakeUpstream is a plain (non-sentinel, non-*graph.ValidationError)
// error, standing in for the kind of unwrapped failure graph.Client
// returns on a transport/parse error -- the case mapEngineError's
// default branch exists to handle.
type errFakeUpstream struct{ msg string }

func (e errFakeUpstream) Error() string { return e.msg }
