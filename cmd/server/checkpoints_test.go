package main

// Unit tests for the checkpoint HTTP API (openspec/changes/
// apply-ontology-changes, chunk 9/task 5.5), pinned against a fake
// checkpointService -- no filesystem, no live GraphDB. See
// proposals_test.go for the shared chatStub/newTestMux helpers and the
// fake-dispatch conventions this file reuses.

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/blogem/msr-graph/internal/checkpoint"
)

// Compile-time contract pin: fails to compile until the coder's
// handler.go declares checkpointService with exactly this method set
// (task 5.2-5.3) -- the expected pass-1 state.
var _ checkpointService = (*fakeCheckpointService)(nil)

// fakeCheckpointService is a functional double for checkpointService
// ({Create, Restore, List}): each test configures createFn/restoreFn/
// listFn to return the canned Manifest/error the scenario needs, and every
// call is counted so a 405 test can assert no mutation occurred.
type fakeCheckpointService struct {
	createFn  func(label string) (checkpoint.Manifest, error)
	restoreFn func(label string) error
	listFn    func() ([]checkpoint.Manifest, error)

	createCalls  int
	restoreCalls int
	listCalls    int
}

func (f *fakeCheckpointService) Create(_ context.Context, label string) (checkpoint.Manifest, error) {
	f.createCalls++
	if f.createFn != nil {
		return f.createFn(label)
	}
	return checkpoint.Manifest{Label: label}, nil
}

func (f *fakeCheckpointService) Restore(_ context.Context, label string) error {
	f.restoreCalls++
	if f.restoreFn != nil {
		return f.restoreFn(label)
	}
	return nil
}

func (f *fakeCheckpointService) List() ([]checkpoint.Manifest, error) {
	f.listCalls++
	if f.listFn != nil {
		return f.listFn()
	}
	return nil, nil
}

// --- GET /api/checkpoints ---

func TestCheckpointsList_ReturnsShape(t *testing.T) {
	ckpt := &fakeCheckpointService{listFn: func() ([]checkpoint.Manifest, error) {
		return []checkpoint.Manifest{
			{Label: "demo", OntologyVersion: "0.4.0"},
			{Label: "pre-approve", OntologyVersion: "0.4.0"},
		}, nil
	}}
	mux, _ := newTestMux(&fakeProposalReader{}, &fakeProposalService{}, ckpt)

	req := httptest.NewRequest(http.MethodGet, "/api/checkpoints", nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 (body: %s)", rec.Code, rec.Body.String())
	}

	body := decodeJSONObject(t, rec.Body.Bytes())
	checkpoints := asSlice(t, body["checkpoints"], "checkpoints")
	if len(checkpoints) != 2 {
		t.Fatalf("got %d checkpoints, want 2 (body: %s)", len(checkpoints), rec.Body.String())
	}

	raw := rec.Body.String()
	for _, want := range []string{"demo", "pre-approve", "0.4.0"} {
		if !strings.Contains(raw, want) {
			t.Errorf("response missing expected content %q (body: %s)", want, raw)
		}
	}
	if ckpt.listCalls != 1 {
		t.Errorf("List called %d times, want 1", ckpt.listCalls)
	}
}

// --- POST /api/checkpoints ---

func TestCheckpointCreate_Success201(t *testing.T) {
	ckpt := &fakeCheckpointService{createFn: func(label string) (checkpoint.Manifest, error) {
		return checkpoint.Manifest{Label: label, OntologyVersion: "0.4.0"}, nil
	}}
	mux, _ := newTestMux(&fakeProposalReader{}, &fakeProposalService{}, ckpt)

	req := httptest.NewRequest(http.MethodPost, "/api/checkpoints", strings.NewReader(`{"label":"demo"}`))
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusCreated {
		t.Fatalf("status = %d, want 201 (body: %s)", rec.Code, rec.Body.String())
	}
	raw := rec.Body.String()
	if !strings.Contains(raw, "demo") || !strings.Contains(raw, "0.4.0") {
		t.Errorf("response missing manifest content (body: %s)", raw)
	}
	if ckpt.createCalls != 1 {
		t.Errorf("Create called %d times, want 1", ckpt.createCalls)
	}
}

func TestCheckpointCreate_InvalidLabelReturns400(t *testing.T) {
	ckpt := &fakeCheckpointService{createFn: func(string) (checkpoint.Manifest, error) {
		return checkpoint.Manifest{}, checkpoint.ErrInvalidLabel
	}}
	mux, _ := newTestMux(&fakeProposalReader{}, &fakeProposalService{}, ckpt)

	req := httptest.NewRequest(http.MethodPost, "/api/checkpoints", strings.NewReader(`{"label":"../etc"}`))
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400 (body: %s)", rec.Code, rec.Body.String())
	}
}

func TestCheckpointCreate_MalformedBodyReturns400(t *testing.T) {
	ckpt := &fakeCheckpointService{}
	mux, _ := newTestMux(&fakeProposalReader{}, &fakeProposalService{}, ckpt)

	req := httptest.NewRequest(http.MethodPost, "/api/checkpoints", strings.NewReader(`not json`))
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400 (body: %s)", rec.Code, rec.Body.String())
	}
	if ckpt.createCalls != 0 {
		t.Errorf("Create called %d times, want 0 on malformed body", ckpt.createCalls)
	}
}

// --- POST /api/checkpoints/{label}/restore ---

func TestCheckpointRestore_Success200(t *testing.T) {
	ckpt := &fakeCheckpointService{}
	mux, _ := newTestMux(&fakeProposalReader{}, &fakeProposalService{}, ckpt)

	req := httptest.NewRequest(http.MethodPost, "/api/checkpoints/demo/restore", nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 (body: %s)", rec.Code, rec.Body.String())
	}
	if ckpt.restoreCalls != 1 {
		t.Errorf("Restore called %d times, want 1", ckpt.restoreCalls)
	}
}

func TestCheckpointRestore_NotFoundReturns404(t *testing.T) {
	ckpt := &fakeCheckpointService{restoreFn: func(string) error {
		return checkpoint.ErrNotFound
	}}
	mux, _ := newTestMux(&fakeProposalReader{}, &fakeProposalService{}, ckpt)

	req := httptest.NewRequest(http.MethodPost, "/api/checkpoints/no-such-label/restore", nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404 (body: %s)", rec.Code, rec.Body.String())
	}
}

// --- 405 on a wrong method for a checkpoint route ---

func TestCheckpointRestoreRoute_WrongMethodIs405AndDoesNotMutate(t *testing.T) {
	ckpt := &fakeCheckpointService{}
	mux, _ := newTestMux(&fakeProposalReader{}, &fakeProposalService{}, ckpt)

	req := httptest.NewRequest(http.MethodGet, "/api/checkpoints/demo/restore", nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusMethodNotAllowed {
		t.Fatalf("status = %d, want 405 (body: %s)", rec.Code, rec.Body.String())
	}
	if got := rec.Header().Get("Allow"); got == "" {
		t.Errorf("Allow header missing on 405 response")
	}
	if ckpt.createCalls != 0 || ckpt.restoreCalls != 0 || ckpt.listCalls != 0 {
		t.Errorf("service calls = create:%d restore:%d list:%d, want all 0 (no mutation on 405)",
			ckpt.createCalls, ckpt.restoreCalls, ckpt.listCalls)
	}
}

func TestCheckpointsRoute_WrongMethodIs405(t *testing.T) {
	ckpt := &fakeCheckpointService{}
	mux, _ := newTestMux(&fakeProposalReader{}, &fakeProposalService{}, ckpt)

	req := httptest.NewRequest(http.MethodDelete, "/api/checkpoints", nil)
	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusMethodNotAllowed {
		t.Fatalf("status = %d, want 405 (body: %s)", rec.Code, rec.Body.String())
	}
	if got := rec.Header().Get("Allow"); got == "" {
		t.Errorf("Allow header missing on 405 response")
	}
	if ckpt.createCalls != 0 || ckpt.listCalls != 0 {
		t.Errorf("service calls = create:%d list:%d, want both 0 (no mutation on 405)", ckpt.createCalls, ckpt.listCalls)
	}
}
