package nist_test

// Unit tests for equation-form code mapping (task 8.3). Grounded in
// openspec/changes/load-nist-structured-data/design.md D5 (the full
// documented 12-code NIST equation-form set) and
// specs/nist-structured-loading/spec.md's "Unknown data-type code aborts"
// and "Documented isotherm and extended-Arrhenius codes are ingested, not
// skipped" scenarios.

import (
	"strings"
	"testing"

	"github.com/blogem/msr-graph/internal/nist"
)

func TestMapEquationForm_KnownCodes(t *testing.T) {
	tests := []struct {
		code string
		want string
	}{
		{"P1", "Linear"},
		{"P2", "Polynomial2"},
		{"P3", "Polynomial3"},
		{"P4", "Polynomial4"},
		{"+E", "Arrhenius"},
		{"E1", "ExtendedArrhenius1"},
		{"E2", "ExtendedArrhenius2"},
		{"DP", "DiscretePoint"},
		{"I1", "Isotherm1"},
		{"I2", "Isotherm2"},
		{"I3", "Isotherm3"},
		{"I4", "Isotherm4"},
	}

	for _, tc := range tests {
		t.Run(tc.code, func(t *testing.T) {
			got, err := nist.MapEquationForm(tc.code)
			if err != nil {
				t.Fatalf("MapEquationForm(%q): unexpected error: %v", tc.code, err)
			}
			if got != tc.want {
				t.Errorf("MapEquationForm(%q) = %q, want %q", tc.code, got, tc.want)
			}
		})
	}
}

func TestMapEquationForm_UnknownCodeErrors(t *testing.T) {
	const badCode = "ZZ"
	_, err := nist.MapEquationForm(badCode)
	if err == nil {
		t.Fatalf("MapEquationForm(%q): expected an error for an undocumented code, got nil", badCode)
	}
	if !strings.Contains(err.Error(), badCode) {
		t.Errorf("MapEquationForm(%q) error = %q, want it to contain the offending code %q", badCode, err.Error(), badCode)
	}
}
