package nist_test

// Unit tests for the fluoride-subset filter (task 8.4). Grounded in
// openspec/changes/load-nist-structured-data/design.md D6: a row is kept
// iff every component parses as a fluoride compound (cation in
// {Li, Be, Na, K, Zr, U, Th}, formula ends in F/F2/F3/F4, no other anion).
// Chlorides and mixed-anion salts must be rejected.

import (
	"testing"

	"github.com/blogem/msr-graph/internal/nist"
)

func TestIsFluoride_AcceptsFluorideSalts(t *testing.T) {
	tests := []string{
		"LiF",
		"BeF2-LiF",
		"KF-LiF-NaF",
		"NaF-ZrF4",
		"BeF2-LiF-UF4-ZrF4",
	}
	for _, saltToken := range tests {
		t.Run(saltToken, func(t *testing.T) {
			if !nist.IsFluoride(saltToken) {
				t.Errorf("IsFluoride(%q) = false, want true", saltToken)
			}
		})
	}
}

func TestIsFluoride_RejectsChlorideAndMixedAnionSalts(t *testing.T) {
	tests := []string{
		"AgBr-AgCl",
		"KCl-KF",
		"NaCl",
	}
	for _, saltToken := range tests {
		t.Run(saltToken, func(t *testing.T) {
			if nist.IsFluoride(saltToken) {
				t.Errorf("IsFluoride(%q) = true, want false", saltToken)
			}
		})
	}
}
