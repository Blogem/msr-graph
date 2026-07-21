package main

// Unit tests for reportError's SHACL-violation reporting (code-review fix:
// each violation must be printed exactly once). See internal/graph/errors.go
// for the *graph.ValidationError type these tests construct directly.

import (
	"bytes"
	"errors"
	"strings"
	"testing"

	"github.com/blogem/msr-graph/internal/graph"
)

func TestReportError_ValidationErrorWithViolations_PrintsEachOnce(t *testing.T) {
	ve := &graph.ValidationError{
		Violations: []graph.Violation{
			{
				FocusNode:                 "urn:msr:data#salt-1",
				SourceConstraintComponent: "sh:MinCountConstraintComponent",
				SourceShape:               "urn:msr:shapes#SaltShape",
				ResultPath:                "urn:msr:hasComposition",
				Message:                   "missing composition",
			},
			{
				FocusNode:                 "urn:msr:data#salt-2",
				SourceConstraintComponent: "sh:DatatypeConstraintComponent",
				SourceShape:               "urn:msr:shapes#MeasurementShape",
				ResultPath:                "urn:msr:hasValue",
				Message:                   "wrong datatype",
			},
		},
		Report: "raw report body that should not leak when violations parsed",
	}

	var buf bytes.Buffer
	reportError(&buf, ve)
	out := buf.String()

	for _, distinctive := range []string{
		"urn:msr:data#salt-1",
		"urn:msr:data#salt-2",
	} {
		if got := strings.Count(out, distinctive); got != 1 {
			t.Errorf("output contains %q %d times, want exactly 1\noutput:\n%s", distinctive, got, out)
		}
	}

	// The header must make clear this is a SHACL rejection, not a
	// transport/5xx failure.
	if !strings.Contains(out, "SHACL validation rejected the write") {
		t.Errorf("output missing SHACL rejection header:\n%s", out)
	}

	// The raw report body must not also be printed when violations parsed
	// (that would duplicate the same information a second time).
	if strings.Contains(out, ve.Report) {
		t.Errorf("output unexpectedly contains raw report body when violations were parsed:\n%s", out)
	}
}

func TestReportError_ValidationErrorNoViolations_PrintsRawReport(t *testing.T) {
	ve := &graph.ValidationError{
		Violations: nil,
		Report:     "raw report body with no parseable sh:ValidationResult",
	}

	var buf bytes.Buffer
	reportError(&buf, ve)
	out := buf.String()

	if !strings.Contains(out, ve.Report) {
		t.Errorf("output missing raw report body when no violations parsed:\noutput:\n%s\nwant substring:\n%s", out, ve.Report)
	}
	if !strings.Contains(out, "SHACL validation rejected the write") {
		t.Errorf("output missing SHACL rejection header:\n%s", out)
	}
}

func TestReportError_GenericError_PrintedOnceUnformatted(t *testing.T) {
	err := errors.New("connection refused")

	var buf bytes.Buffer
	reportError(&buf, err)
	out := buf.String()

	if got := strings.Count(out, "connection refused"); got != 1 {
		t.Errorf("output contains %q %d times, want exactly 1\noutput:\n%s", "connection refused", got, out)
	}
	if strings.Contains(out, "SHACL") {
		t.Errorf("generic error misformatted as a SHACL validation error:\n%s", out)
	}
	want := "loader: connection refused\n"
	if out != want {
		t.Errorf("output = %q, want %q", out, want)
	}
}
