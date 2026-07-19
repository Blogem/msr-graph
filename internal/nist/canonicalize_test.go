package nist_test

// Unit tests for the salt canonicalization core (tasks 8.1 and 8.2).
// Grounded in openspec/changes/load-nist-structured-data/specs/salt-canonicalization/spec.md
// and design.md D3-D5a. Pure Go, no GraphDB, no network.
//
// These tests are written against the agreed API (Canonicalize) and the
// agreed testdata/salt-canonicalization.json fixture schema BEFORE the
// coder's internal/nist implementation and the fixture file exist in this
// worktree. They are expected to fail to compile here; they must compile
// and pass once the coder's package + fixture merge alongside these tests.

import (
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"testing"

	"github.com/blogem/msr-graph/internal/nist"
)

const molePercentEpsilon = 1e-9

// fixtureFile mirrors the agreed schema of testdata/salt-canonicalization.json.
type fixtureFile struct {
	Cases []fixtureCase `json:"cases"`
}

type fixtureCase struct {
	Name           string    `json:"name"`
	RawSalt        string    `json:"raw_salt"`
	RawComposition string    `json:"raw_composition"`
	FormCode       string    `json:"form_code"`
	Canonical      string    `json:"canonical"`
	Components     []string  `json:"components"`
	MolePercent    []float64 `json:"mole_percent"`
	SaltIRI        string    `json:"salt_iri"`
	IsRange        bool      `json:"is_range"`
	VaryComponent  string    `json:"vary_component"`
	VaryMin        *float64  `json:"vary_min"`
	VaryMax        *float64  `json:"vary_max"`
}

// TestCanonicalize_Fixture drives task 8.1: every raw input in
// testdata/salt-canonicalization.json MUST produce the fixture's expected
// canonical string, ordered component list, salt IRI, range flag, and
// per-component mole fractions (Go is the drift guard the shared fixture
// exists to enforce, per design.md D3).
func TestCanonicalize_Fixture(t *testing.T) {
	fixturePath := filepath.Join("..", "..", "testdata", "salt-canonicalization.json")
	raw, err := os.ReadFile(fixturePath)
	if err != nil {
		if os.IsNotExist(err) {
			t.Skipf("fixture not present yet at %s (authored by the coder's task 2.5/8.1): %v", fixturePath, err)
		}
		t.Fatalf("reading fixture %s: %v", fixturePath, err)
	}

	var ff fixtureFile
	if err := json.Unmarshal(raw, &ff); err != nil {
		t.Fatalf("parsing fixture %s: %v", fixturePath, err)
	}
	if len(ff.Cases) == 0 {
		t.Fatalf("fixture %s has no cases", fixturePath)
	}

	for _, tc := range ff.Cases {
		tc := tc
		t.Run(tc.Name, func(t *testing.T) {
			got, err := nist.Canonicalize(tc.RawSalt, tc.RawComposition, tc.FormCode)
			if err != nil {
				t.Fatalf("Canonicalize(%q, %q, %q): unexpected error: %v", tc.RawSalt, tc.RawComposition, tc.FormCode, err)
			}

			if got.Canonical != tc.Canonical {
				t.Errorf("Canonical = %q, want %q", got.Canonical, tc.Canonical)
			}
			if !stringSlicesEqual(got.Components, tc.Components) {
				t.Errorf("Components = %v, want %v", got.Components, tc.Components)
			}
			if got.IRI != tc.SaltIRI {
				t.Errorf("IRI = %q, want %q", got.IRI, tc.SaltIRI)
			}
			if got.IsRange != tc.IsRange {
				t.Errorf("IsRange = %v, want %v", got.IsRange, tc.IsRange)
			}

			if !tc.IsRange {
				if len(tc.MolePercent) != len(got.Constituents) {
					t.Fatalf("fixture has %d mole_percent entries, got %d constituents", len(tc.MolePercent), len(got.Constituents))
				}
				for i, c := range got.Constituents {
					if c.MoleFraction == nil {
						t.Fatalf("constituent %d (%s): MoleFraction is nil for a point case", i, c.Compound)
					}
					want := tc.MolePercent[i] / 100.0
					if math.Abs(*c.MoleFraction-want) > molePercentEpsilon {
						t.Errorf("constituent %d (%s): MoleFraction = %v, want %v", i, c.Compound, *c.MoleFraction, want)
					}
				}
			} else {
				if tc.VaryComponent == "" {
					t.Fatalf("fixture case %q: is_range=true but vary_component is empty", tc.Name)
				}
				var found *nist.Constituent
				for i := range got.Constituents {
					if got.Constituents[i].Compound == tc.VaryComponent {
						found = &got.Constituents[i]
						break
					}
				}
				if found == nil {
					t.Fatalf("fixture case %q: no constituent named %q among %v", tc.Name, tc.VaryComponent, got.Constituents)
				}
				if found.MoleFractionMin == nil || found.MoleFractionMax == nil {
					t.Fatalf("fixture case %q: varying constituent %q missing MoleFractionMin/Max", tc.Name, tc.VaryComponent)
				}
				// vary_min/vary_max in the fixture are mole percentages (like
				// mole_percent), while MoleFractionMin/Max are fractions.
				if tc.VaryMin != nil {
					wantMin := *tc.VaryMin / 100.0
					if math.Abs(*found.MoleFractionMin-wantMin) > molePercentEpsilon {
						t.Errorf("constituent %s: MoleFractionMin = %v, want %v", tc.VaryComponent, *found.MoleFractionMin, wantMin)
					}
				}
				if tc.VaryMax != nil {
					wantMax := *tc.VaryMax / 100.0
					if math.Abs(*found.MoleFractionMax-wantMax) > molePercentEpsilon {
						t.Errorf("constituent %s: MoleFractionMax = %v, want %v", tc.VaryComponent, *found.MoleFractionMax, wantMax)
					}
				}
			}
		})
	}
}

// TestCanonicalize_PureCases pins the salt-canonicalization spec.md scenarios
// directly (task 8.1), independent of the fixture file: the real FLiBe row
// (already byte-canonical, no reorder needed), the lockstep reorder, a
// ternary reorder, and a pure single-component salt.
func TestCanonicalize_PureCases(t *testing.T) {
	tests := []struct {
		name           string
		rawSalt        string
		rawComposition string
		formCode       string
		wantCanonical  string
		wantComponents []string
		wantMoleFrac   map[string]float64
	}{
		{
			name:           "FLiBe real row is already byte-canonical",
			rawSalt:        "BeF2-LiF",
			rawComposition: "34.0-66.0",
			formCode:       "P1",
			wantCanonical:  "BeF2-LiF | 34.0-66.0",
			wantComponents: []string{"BeF2", "LiF"},
			wantMoleFrac:   map[string]float64{"BeF2": 0.34, "LiF": 0.66},
		},
		{
			name:           "lockstep reorder",
			rawSalt:        "LiF-BeF2",
			rawComposition: "34.0-66.0",
			formCode:       "P1",
			wantCanonical:  "BeF2-LiF | 66.0-34.0",
			wantComponents: []string{"BeF2", "LiF"},
			wantMoleFrac:   map[string]float64{"BeF2": 0.66, "LiF": 0.34},
		},
		{
			name:           "ternary reorder",
			rawSalt:        "LiF-NaF-KF",
			rawComposition: "46.5-11.5-42.0",
			formCode:       "P1",
			wantCanonical:  "KF-LiF-NaF | 42.0-46.5-11.5",
			wantComponents: []string{"KF", "LiF", "NaF"},
			wantMoleFrac:   map[string]float64{"KF": 0.42, "LiF": 0.465, "NaF": 0.115},
		},
		{
			name:           "pure salt",
			rawSalt:        "LiF",
			rawComposition: "100",
			formCode:       "P1",
			wantCanonical:  "LiF | 100.0",
			wantComponents: []string{"LiF"},
			wantMoleFrac:   map[string]float64{"LiF": 1.0},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got, err := nist.Canonicalize(tc.rawSalt, tc.rawComposition, tc.formCode)
			if err != nil {
				t.Fatalf("Canonicalize(%q, %q, %q): unexpected error: %v", tc.rawSalt, tc.rawComposition, tc.formCode, err)
			}
			if got.Canonical != tc.wantCanonical {
				t.Errorf("Canonical = %q, want %q", got.Canonical, tc.wantCanonical)
			}
			if !stringSlicesEqual(got.Components, tc.wantComponents) {
				t.Errorf("Components = %v, want %v", got.Components, tc.wantComponents)
			}
			if got.IsRange {
				t.Errorf("IsRange = true, want false for a positional case")
			}
			if len(got.Constituents) != len(tc.wantComponents) {
				t.Fatalf("got %d constituents, want %d", len(got.Constituents), len(tc.wantComponents))
			}
			for _, c := range got.Constituents {
				want, ok := tc.wantMoleFrac[c.Compound]
				if !ok {
					t.Fatalf("unexpected constituent %q in result", c.Compound)
				}
				if c.MoleFraction == nil {
					t.Fatalf("constituent %s: MoleFraction is nil", c.Compound)
				}
				if math.Abs(*c.MoleFraction-want) > molePercentEpsilon {
					t.Errorf("constituent %s: MoleFraction = %v, want %v", c.Compound, *c.MoleFraction, want)
				}
			}
		})
	}
}

// TestCanonicalize_Disambiguation pins task 8.2 and design.md D4: the
// equation-form code, not the value shape, drives positional-vs-range
// interpretation.
func TestCanonicalize_Disambiguation(t *testing.T) {
	t.Run("two-component positional summing to exactly 100 becomes MoleFraction", func(t *testing.T) {
		got, err := nist.Canonicalize("LiF-NaF", "60.0-40.0", "P1")
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if got.IsRange {
			t.Fatalf("IsRange = true, want false for a positional row summing to 100")
		}
		for _, c := range got.Constituents {
			if c.MoleFraction == nil {
				t.Errorf("constituent %s: expected MoleFraction to be set", c.Compound)
			}
			if c.MoleFractionMin != nil || c.MoleFractionMax != nil {
				t.Errorf("constituent %s: expected MoleFractionMin/Max to be nil for a positional case", c.Compound)
			}
		}
	})

	t.Run("positional row summing to 99.0 stays within the +/-2.0 tolerance", func(t *testing.T) {
		got, err := nist.Canonicalize("LiF-NaF", "26.04-72.96", "P1")
		if err != nil {
			t.Fatalf("unexpected error for a row within the +/-2.0 mol%% tolerance: %v", err)
		}
		if got.IsRange {
			t.Fatalf("IsRange = true, want false for a positional row")
		}
		// Canonicalize formats each mole-% to one decimal place (spec:
		// salt-canonicalization "Canonical salt form"): 26.04 -> 26.0,
		// 72.96 -> 73.0, so the resulting fractions are 0.26 / 0.73.
		want := map[string]float64{"LiF": 0.26, "NaF": 0.73}
		for _, c := range got.Constituents {
			if c.MoleFraction == nil {
				t.Fatalf("constituent %s: MoleFraction is nil", c.Compound)
			}
			if math.Abs(*c.MoleFraction-want[c.Compound]) > molePercentEpsilon {
				t.Errorf("constituent %s: MoleFraction = %v, want %v", c.Compound, *c.MoleFraction, want[c.Compound])
			}
		}
	})

	t.Run("isotherm I3 row produces a composition range", func(t *testing.T) {
		got, err := nist.Canonicalize("KF-ZrF4", "0.0-33.3 ZrF4", "I3")
		if err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
		if !got.IsRange {
			t.Fatalf("IsRange = false, want true for an isotherm row")
		}
		var zrf4, kf *nist.Constituent
		for i := range got.Constituents {
			switch got.Constituents[i].Compound {
			case "ZrF4":
				zrf4 = &got.Constituents[i]
			case "KF":
				kf = &got.Constituents[i]
			}
		}
		if zrf4 == nil || kf == nil {
			t.Fatalf("expected constituents ZrF4 and KF, got %v", got.Constituents)
		}
		if zrf4.MoleFractionMin == nil || zrf4.MoleFractionMax == nil {
			t.Fatalf("ZrF4 constituent missing MoleFractionMin/Max")
		}
		if math.Abs(*zrf4.MoleFractionMin-0.0) > molePercentEpsilon || math.Abs(*zrf4.MoleFractionMax-0.333) > molePercentEpsilon {
			t.Errorf("ZrF4 range = [%v, %v], want [0.0, 0.333]", *zrf4.MoleFractionMin, *zrf4.MoleFractionMax)
		}
		if kf.MoleFractionMin == nil || kf.MoleFractionMax == nil {
			t.Fatalf("KF constituent missing MoleFractionMin/Max")
		}
		if math.Abs(*kf.MoleFractionMin-0.667) > molePercentEpsilon || math.Abs(*kf.MoleFractionMax-1.0) > molePercentEpsilon {
			t.Errorf("KF range = [%v, %v], want [0.667, 1.0]", *kf.MoleFractionMin, *kf.MoleFractionMax)
		}
	})

	t.Run("positional row far from 100 is a manual-review error", func(t *testing.T) {
		_, err := nist.Canonicalize("LiF-NaF", "50-30", "P1")
		if err == nil {
			t.Fatalf("expected an error for a positional row summing to 80 (outside +/-2.0 tolerance), got nil")
		}
	})
}

func stringSlicesEqual(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
