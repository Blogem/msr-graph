package nist

// Regression tests for the H1 locator-collision fix (disambiguateLocators in
// process.go): the real vendored NIST data carries multiple measurements for
// some (property, salt) pairs -- most notably BeF2 electrical conductivity,
// which has three DiscretePoint rows (990K, 1030K, 1070K) plus one Arrhenius
// fit (1090K), all of which previously minted the identical locator
// "nist-srd27/electricalConductivity#BeF2|100.0" and measurement IRI. These
// tests run Process against the real vendored data (not a synthetic
// fixture) because the collision only reproduces there, and assert:
//
//  1. every measurement's Locator is unique across the whole run,
//  2. the 4 BeF2 conductivity measurements get 4 distinct locators,
//  3. the FLiBe and FLiNaK density anchor locators are unchanged (singletons
//     must not be disambiguated),
//  4. every measurement IRI is a valid msrd: CURIE local name (no stray
//     "@", "|", "#", or "/").
//
// GRAPHDB-free: Process only reads local files (the vendored CSVs + the
// QUDT allowlist), never GraphDB or SQLite.

import (
	"os"
	"strings"
	"testing"
)

const (
	nistDataDir       = "../../data/nist"
	qudtAllowlistPath = "../../ontology/qudt-units.json"
)

// skipIfDataAbsent skips the test if the vendored NIST data directory or the
// QUDT allowlist file is not present in this checkout (e.g. a partial or
// shallow checkout), so the rest of the suite still passes.
func skipIfDataAbsent(t *testing.T) {
	t.Helper()
	if _, err := os.Stat(nistDataDir); err != nil {
		t.Skipf("vendored NIST data dir %s not present: %v", nistDataDir, err)
	}
	if _, err := os.Stat(qudtAllowlistPath); err != nil {
		t.Skipf("QUDT allowlist %s not present: %v", qudtAllowlistPath, err)
	}
}

// processRealData runs the real Process pipeline over the vendored data,
// failing the test on any pipeline error (parse, canonicalize, unit
// validation, etc. failures are unexpected against the known-good vendored
// files).
func processRealData(t *testing.T) []Measurement {
	t.Helper()
	units, err := LoadUnitAllowlist(qudtAllowlistPath)
	if err != nil {
		t.Fatalf("LoadUnitAllowlist(%s): %v", qudtAllowlistPath, err)
	}
	measurements, _, err := Process(nistDataDir, units)
	if err != nil {
		t.Fatalf("Process(%s): %v", nistDataDir, err)
	}
	return measurements
}

func TestProcess_LocatorsAreUnique(t *testing.T) {
	skipIfDataAbsent(t)
	measurements := processRealData(t)

	seen := make(map[string]int, len(measurements))
	for _, m := range measurements {
		seen[m.Locator]++
	}
	if len(seen) != len(measurements) {
		t.Errorf("got %d measurements but only %d distinct locators", len(measurements), len(seen))
		for locator, count := range seen {
			if count > 1 {
				t.Errorf("  locator %q used by %d measurements", locator, count)
			}
		}
	}
}

func TestProcess_BeF2ConductivityDisambiguated(t *testing.T) {
	skipIfDataAbsent(t)
	measurements := processRealData(t)

	const basePrefix = "nist-srd27/electricalConductivity#BeF2|100.0"
	var group []Measurement
	for _, m := range measurements {
		if m.Property == PropElectricalConductivity && strings.HasPrefix(m.Locator, basePrefix) {
			group = append(group, m)
		}
	}

	if len(group) != 4 {
		t.Fatalf("expected 4 BeF2 electrical-conductivity measurements sharing base locator %q, got %d: %+v", basePrefix, len(group), group)
	}

	locators := make(map[string]bool, len(group))
	for _, m := range group {
		if locators[m.Locator] {
			t.Errorf("duplicate locator %q among BeF2 conductivity measurements", m.Locator)
		}
		locators[m.Locator] = true
		if m.Locator == basePrefix {
			t.Errorf("BeF2 conductivity measurement kept the undisambiguated base locator %q", m.Locator)
		}
	}
	if len(locators) != 4 {
		t.Errorf("expected 4 distinct BeF2 conductivity locators, got %d: %v", len(locators), locators)
	}
}

func TestProcess_AnchorLocatorsUnchanged(t *testing.T) {
	skipIfDataAbsent(t)
	measurements := processRealData(t)

	const (
		flibeLocator  = "nist-srd27/density#BeF2-LiF|34.0-66.0"
		flinakLocator = "nist-srd27/density#KF-LiF-NaF|42.0-46.5-11.5"
	)
	var sawFLiBe, sawFLiNaK bool
	for _, m := range measurements {
		switch m.Locator {
		case flibeLocator:
			sawFLiBe = true
		case flinakLocator:
			sawFLiNaK = true
		}
	}
	if !sawFLiBe {
		t.Errorf("expected FLiBe density anchor locator %q to be present unchanged", flibeLocator)
	}
	if !sawFLiNaK {
		t.Errorf("expected FLiNaK density anchor locator %q to be present unchanged", flinakLocator)
	}
}

func TestProcess_MeasurementIRIsAreValidCurieLocalNames(t *testing.T) {
	skipIfDataAbsent(t)
	measurements := processRealData(t)

	for _, m := range measurements {
		for _, bad := range []string{"@", "|", "#", "/"} {
			if strings.Contains(m.IRI, bad) {
				t.Errorf("measurement IRI %q contains disallowed character %q (locator %q)", m.IRI, bad, m.Locator)
			}
		}
	}
}
