package main

import (
	"encoding/json"
	"errors"
	"net/http"

	"github.com/blogem/msr-graph/internal/checkpoint"
	"github.com/blogem/msr-graph/internal/graph"
	"github.com/blogem/msr-graph/internal/proposal"
)

// statusResponse is the wire shape every disposition endpoint (approve,
// reject, edit, restore) returns on success: a single "status" field
// naming the outcome, per the pinned JSON contract in
// openspec/changes/apply-ontology-changes/tasks.md 5.1/5.2.
type statusResponse struct {
	Status string `json:"status"`
}

// apiError is the JSON error body shape for the proposal/checkpoint API's
// typed error contract (task 5.4): every non-2xx response carries a
// stable machine-readable "error" code plus a human-readable "message".
// A SHACL rejection additionally populates "violations" so a caller never
// has to parse a stack trace to find out what failed.
type apiError struct {
	Error      string          `json:"error"`
	Message    string          `json:"message"`
	Violations []violationJSON `json:"violations,omitempty"`
}

// violationJSON is the wire shape of one graph.Violation.
type violationJSON struct {
	FocusNode  string `json:"focusNode,omitempty"`
	Constraint string `json:"constraint,omitempty"`
	Shape      string `json:"shape,omitempty"`
	Path       string `json:"path,omitempty"`
	Message    string `json:"message,omitempty"`
}

// writeJSON encodes v as the response body with the given status code,
// always setting Content-Type: application/json first (spec "Stateless
// JSON API with a typed error contract").
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	// The response has already been committed by WriteHeader above; an
	// encode failure here (e.g. the client disconnecting mid-write) has
	// no remaining recovery action, so it is deliberately not handled a
	// second time.
	_ = json.NewEncoder(w).Encode(v)
}

// writeAPIError writes the {error, message} JSON shape used for every
// error response that carries no further structured detail.
func writeAPIError(w http.ResponseWriter, status int, code, message string) {
	writeJSON(w, status, apiError{Error: code, Message: message})
}

// writeBadRequest writes the 400 shape used for a malformed or
// undecodable request body (task 5.4).
func writeBadRequest(w http.ResponseWriter, message string) {
	writeAPIError(w, http.StatusBadRequest, "bad_request", message)
}

// mapEngineError is the single place that inspects an error returned by
// the proposal/checkpoint engines and maps it to the typed HTTP contract
// (task 5.4), so every handler maps errors identically:
//
//   - *graph.ValidationError (a SHACL rejection)   -> 422, structured violations
//   - proposal.ErrNotFound / checkpoint.ErrNotFound -> 404
//   - proposal.ErrInvalidTransition                 -> 409
//   - checkpoint.ErrInvalidLabel                    -> 400
//   - anything else                                 -> 500
//
// The ValidationError check runs first: GraphDB's SHACL rejection is
// itself surfaced by the engines as an unwrapped *graph.ValidationError
// (see internal/proposal/lifecycle.go), so it must be checked with
// errors.As before the sentinel errors.Is checks below it.
func mapEngineError(w http.ResponseWriter, err error) {
	var ve *graph.ValidationError
	switch {
	case errors.As(err, &ve):
		violations := make([]violationJSON, 0, len(ve.Violations))
		for _, v := range ve.Violations {
			violations = append(violations, violationJSON{
				FocusNode:  v.FocusNode,
				Constraint: v.SourceConstraintComponent,
				Shape:      v.SourceShape,
				Path:       v.ResultPath,
				Message:    v.Message,
			})
		}
		writeJSON(w, http.StatusUnprocessableEntity, apiError{
			Error:      "validation",
			Message:    ve.Error(),
			Violations: violations,
		})
	case errors.Is(err, proposal.ErrNotFound), errors.Is(err, checkpoint.ErrNotFound):
		writeAPIError(w, http.StatusNotFound, "not_found", err.Error())
	case errors.Is(err, proposal.ErrInvalidTransition):
		writeAPIError(w, http.StatusConflict, "invalid_transition", err.Error())
	case errors.Is(err, checkpoint.ErrInvalidLabel):
		writeAPIError(w, http.StatusBadRequest, "invalid_label", err.Error())
	default:
		writeAPIError(w, http.StatusInternalServerError, "internal", err.Error())
	}
}
