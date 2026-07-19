package main

// Pass-1 unit tests for the `loader nist` subcommand's pure, non-networked
// pieces: the SPARQL INSERT DATA builder (buildInsertData), the
// Measurement->row / Measurement->triple split (coefficients stay in
// SQLite, metadata goes to the graph), and dispatch recognition of the
// "nist" subcommand.
//
// These tests are written against the task contract's agreed API
// (buildInsertData(ms []nist.Measurement) string in package main) and the
// exported internal/nist types (Measurement, Salt, Constituent). The nist
// ingest implementation (cmd/loader/nist.go) lands in a parallel worktree
// and is expected to be ABSENT here; these tests are written to COMPILE and
// encode the acceptance scenarios precisely, not to pass, until the
// implementation and internal/nist package are merged in.
//
// Spec: openspec/changes/load-nist-structured-data/specs/nist-structured-loading/spec.md
//   - "Catalog triples emitted additively to the core data graph"
//   - "FLiBe density measurement is queryable via the core client"
//   - "Coefficients are not emitted as triples"
//   - "Composition-isotherm measurements" / KF-ZrF4 isotherm scenario
//   - "Seed hand-curated edges survive the load"

import (
	"strings"
	"testing"

	"github.com/blogem/msr-graph/internal/nist"
)

func f64(v float64) *float64 { return &v }

// flibeDensityMeasurement builds the canonical FLiBe (BeF2-LiF, 34.0-66.0
// mol%) density measurement fixture per the design's worked example:
// coefficients 2.413 / -4.88e-4 (Linear), unit GM-PER-CentiM3, validity
// 800-1080 K, locator nist-srd27/density#BeF2-LiF|34.0-66.0.
func flibeDensityMeasurement() nist.Measurement {
	saltIRI := "msrd:salt-BeF2-LiF-34.0-66.0"
	salt := nist.Salt{
		Canonical:  "BeF2-LiF | 34.0-66.0",
		IRI:        saltIRI,
		Label:      "BeF2-LiF (34.0-66.0 mol%)",
		Components: []string{"BeF2", "LiF"},
		Constituents: []nist.Constituent{
			{Compound: "BeF2", IRI: saltIRI + "-c-BeF2", MoleFraction: f64(0.34)},
			{Compound: "LiF", IRI: saltIRI + "-c-LiF", MoleFraction: f64(0.66)},
		},
		IsRange: false,
	}
	return nist.Measurement{
		Salt:                 salt,
		Property:             "density",
		EquationForm:         "Linear",
		UnitIRI:              "http://qudt.org/vocab/unit/GM-PER-CentiM3",
		UnitCurie:            "unit:GM-PER-CentiM3",
		Coeffs:               [5]*float64{f64(2.413), f64(-4.88e-4), nil, nil, nil},
		TMin:                 f64(800),
		TMax:                 f64(1080),
		Locator:              "nist-srd27/density#BeF2-LiF|34.0-66.0",
		IRI:                  "msrd:m-nist-srd27-density-BeF2-LiF-34.0-66.0",
		CompositionComponent: "",
	}
}

// kfZrf4IsothermMeasurement builds the KF-ZrF4 composition-isotherm
// viscosity fixture per design D5a: range-composition salt
// "KF-ZrF4 | ZrF4 0.0-33.3", ZrF4 the varying component
// (moleFractionMin=0.0, moleFractionMax=0.333), KF the complement
// (moleFractionMin=0.667, moleFractionMax=1.0), equationForm Isotherm3,
// validTempMin == validTempMax (single sweep temperature).
func kfZrf4IsothermMeasurement() nist.Measurement {
	saltIRI := "msrd:salt-KF-ZrF4-ZrF4-0.0-33.3"
	salt := nist.Salt{
		Canonical:  "KF-ZrF4 | ZrF4 0.0-33.3",
		IRI:        saltIRI,
		Label:      "KF-ZrF4 (ZrF4 0.0-33.3 mol%)",
		Components: []string{"KF", "ZrF4"},
		Constituents: []nist.Constituent{
			{Compound: "KF", IRI: saltIRI + "-c-KF", MoleFractionMin: f64(0.667), MoleFractionMax: f64(1.0)},
			{Compound: "ZrF4", IRI: saltIRI + "-c-ZrF4", MoleFractionMin: f64(0.0), MoleFractionMax: f64(0.333)},
		},
		IsRange: true,
	}
	return nist.Measurement{
		Salt:                 salt,
		Property:             "viscosity",
		EquationForm:         "Isotherm3",
		UnitIRI:              "http://qudt.org/vocab/unit/MilliPA-SEC",
		UnitCurie:            "unit:MilliPA-SEC",
		Coeffs:               [5]*float64{f64(1.0), f64(2.0), f64(3.0), f64(4.0), nil},
		TMin:                 f64(773),
		TMax:                 f64(773),
		Locator:              "nist-srd27/viscosity#KF-ZrF4|ZrF4=0.0-33.3",
		IRI:                  "msrd:m-nist-srd27-viscosity-KF-ZrF4-ZrF4-0.0-33.3",
		CompositionComponent: "ZrF4",
	}
}

func assertContains(t *testing.T, out, want string) {
	t.Helper()
	if !strings.Contains(out, want) {
		t.Errorf("buildInsertData output missing %q\n--- full output ---\n%s", want, out)
	}
}

func assertNotContains(t *testing.T, out, unwanted string) {
	t.Helper()
	if strings.Contains(out, unwanted) {
		t.Errorf("buildInsertData output unexpectedly contains %q\n--- full output ---\n%s", unwanted, out)
	}
}

// TestBuildInsertData_FLiBeDensity covers the "FLiBe density measurement is
// queryable via the core client" scenario: the emitted INSERT DATA must
// carry every triple a consumer needs to resolve the measurement, its salt,
// unit, equation form, validity range, locator, and provenance.
func TestBuildInsertData_FLiBeDensity(t *testing.T) {
	out := buildInsertData([]nist.Measurement{flibeDensityMeasurement()})

	assertContains(t, out, "INSERT DATA")
	assertContains(t, out, "GRAPH <urn:msr:data>")

	// Salt node.
	assertContains(t, out, "msrd:salt-BeF2-LiF-34.0-66.0")
	assertContains(t, out, "a msr:MoltenSalt")
	assertContains(t, out, "BeF2-LiF (34.0-66.0 mol%)")

	// Measurement node.
	assertContains(t, out, "msr:ofSalt msrd:salt-BeF2-LiF-34.0-66.0")
	assertContains(t, out, "msr:forProperty msr:density")
	assertContains(t, out, "msr:equationForm msr:Linear")
	assertContains(t, out, `msr:dataLocator "nist-srd27/density#BeF2-LiF|34.0-66.0"`)
	assertContains(t, out, "msr:validTempMin 800")
	assertContains(t, out, "msr:validTempMax 1080")
	assertContains(t, out, "prov:wasDerivedFrom msrd:nist-srd27")

	// Unit, full QUDT IRI form.
	assertContains(t, out, "http://qudt.org/vocab/unit/GM-PER-CentiM3")

	// Point-composition mole fractions.
	assertContains(t, out, "msr:moleFraction 0.34")
	assertContains(t, out, "msr:moleFraction 0.66")
}

// TestBuildInsertData_CoefficientsNotEmitted covers "Coefficients are not
// emitted as triples": numeric coefficient values and any coefficient-named
// predicate must never appear in the graph payload; they live only in
// SQLite (measurement_value.c0..c4), keyed by locator.
func TestBuildInsertData_CoefficientsNotEmitted(t *testing.T) {
	out := buildInsertData([]nist.Measurement{flibeDensityMeasurement()})

	assertNotContains(t, out, "2.413")
	assertNotContains(t, out, "-4.88")
	assertNotContains(t, out, "msr:c0")
	if strings.Contains(strings.ToLower(out), "coeff") {
		t.Errorf("buildInsertData output unexpectedly mentions a coefficient predicate\n--- full output ---\n%s", out)
	}
}

// TestBuildInsertData_IsothermCompositionRange covers "Composition-isotherm
// measurements" / the KF-ZrF4 isotherm scenario: the varying constituent
// carries moleFractionMin/moleFractionMax (not a plain moleFraction), the
// measurement carries compositionComponent naming the varying compound, and
// equationForm resolves to the matching msr:IsothermN individual.
func TestBuildInsertData_IsothermCompositionRange(t *testing.T) {
	out := buildInsertData([]nist.Measurement{kfZrf4IsothermMeasurement()})

	assertContains(t, out, "msr:equationForm msr:Isotherm3")
	assertContains(t, out, "msr:compositionComponent msrd:ZrF4")
	assertContains(t, out, "msr:moleFractionMin")
	assertContains(t, out, "msr:moleFractionMax")

	// The varying/complement constituents must not also carry a plain
	// point moleFraction triple (that predicate is reserved for
	// non-range salts).
	assertNotContains(t, out, "msr:moleFraction 0.0")
	assertNotContains(t, out, "msr:moleFraction 0.333")
	assertNotContains(t, out, "msr:moleFraction 0.667")
	assertNotContains(t, out, "msr:moleFraction 1.0")
}

// TestBuildInsertData_NoHandCuratedEdges covers "Seed hand-curated edges
// survive the load" from the additive side: the loader cannot derive
// hasRole / usedIn / citedIn / skos:closeMatch from NIST data and must not
// fabricate them. These predicates are seed-owned; buildInsertData's
// output must never mention them, for either fixture.
func TestBuildInsertData_NoHandCuratedEdges(t *testing.T) {
	out := buildInsertData([]nist.Measurement{flibeDensityMeasurement(), kfZrf4IsothermMeasurement()})

	for _, unwanted := range []string{"msr:hasRole", "msr:usedIn", "msr:citedIn", "skos:closeMatch"} {
		assertNotContains(t, out, unwanted)
	}
}

// TestBuildInsertData_Empty documents the trivial boundary: an empty
// measurement slice should not panic and (if it produces output at all)
// should not fabricate a GRAPH block with no content worth asserting on
// beyond "no panic, no crash". This guards against buildInsertData
// dereferencing ms[0] unconditionally.
func TestBuildInsertData_Empty(t *testing.T) {
	defer func() {
		if r := recover(); r != nil {
			t.Fatalf("buildInsertData(nil) panicked: %v", r)
		}
	}()
	_ = buildInsertData(nil)
}
