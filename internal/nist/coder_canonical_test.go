package nist

import "testing"

func TestCanonicalize_FLiBe(t *testing.T) {
	salt, err := Canonicalize("BeF2-LiF", "34.0-66.0", "P1")
	if err != nil {
		t.Fatalf("Canonicalize: %v", err)
	}
	if salt.Canonical != "BeF2-LiF | 34.0-66.0" {
		t.Errorf("Canonical = %q, want %q", salt.Canonical, "BeF2-LiF | 34.0-66.0")
	}
	if salt.IRI != "msrd:salt-BeF2-LiF-34.0-66.0" {
		t.Errorf("IRI = %q, want %q", salt.IRI, "msrd:salt-BeF2-LiF-34.0-66.0")
	}
	if salt.IsRange {
		t.Errorf("IsRange = true, want false")
	}
	if len(salt.Constituents) != 2 {
		t.Fatalf("len(Constituents) = %d, want 2", len(salt.Constituents))
	}
	want := map[string]float64{"BeF2": 0.34, "LiF": 0.66}
	for _, c := range salt.Constituents {
		if c.MoleFraction == nil {
			t.Fatalf("constituent %s: MoleFraction is nil", c.Compound)
		}
		if *c.MoleFraction != want[c.Compound] {
			t.Errorf("constituent %s: MoleFraction = %v, want %v", c.Compound, *c.MoleFraction, want[c.Compound])
		}
	}
}

func TestCanonicalize_IsothermRange(t *testing.T) {
	salt, err := Canonicalize("KF-ZrF4", "0.0-33.3 ZrF4", "I3")
	if err != nil {
		t.Fatalf("Canonicalize: %v", err)
	}
	if salt.Canonical != "KF-ZrF4 | ZrF4 0.0-33.3" {
		t.Errorf("Canonical = %q, want %q", salt.Canonical, "KF-ZrF4 | ZrF4 0.0-33.3")
	}
	if salt.IRI != "msrd:salt-KF-ZrF4-ZrF4-0.0-33.3" {
		t.Errorf("IRI = %q, want %q", salt.IRI, "msrd:salt-KF-ZrF4-ZrF4-0.0-33.3")
	}
	if !salt.IsRange {
		t.Errorf("IsRange = false, want true")
	}
	for _, c := range salt.Constituents {
		if c.MoleFractionMin == nil || c.MoleFractionMax == nil {
			t.Fatalf("constituent %s: expected min/max set", c.Compound)
		}
		switch c.Compound {
		case "ZrF4":
			if *c.MoleFractionMin != 0.0 {
				t.Errorf("ZrF4 min = %v, want 0.0", *c.MoleFractionMin)
			}
			if got, want := *c.MoleFractionMax, 0.333; got < want-1e-6 || got > want+1e-6 {
				t.Errorf("ZrF4 max = %v, want ~%v", got, want)
			}
		case "KF":
			if got, want := *c.MoleFractionMin, 0.667; got < want-1e-6 || got > want+1e-6 {
				t.Errorf("KF min = %v, want ~%v", got, want)
			}
			if *c.MoleFractionMax != 1.0 {
				t.Errorf("KF max = %v, want 1.0", *c.MoleFractionMax)
			}
		}
	}
}

func TestMapEquationForm(t *testing.T) {
	form, err := MapEquationForm("I3")
	if err != nil || form != "Isotherm3" {
		t.Errorf("MapEquationForm(I3) = %q, %v, want Isotherm3, nil", form, err)
	}
	if _, err := MapEquationForm("XY"); err == nil {
		t.Errorf("MapEquationForm(XY) = nil error, want error naming XY")
	}
}

func TestIsFluoride(t *testing.T) {
	cases := map[string]bool{
		"BeF2-LiF":  true,
		"AgBr-AgCl": false,
		"NaF-ZrF4":  true,
	}
	for salt, want := range cases {
		if got := IsFluoride(salt); got != want {
			t.Errorf("IsFluoride(%q) = %v, want %v", salt, got, want)
		}
	}
}
