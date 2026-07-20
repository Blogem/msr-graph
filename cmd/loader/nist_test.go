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
	"time"

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

// --- openspec/changes/provenance-model additions (tasks 6.1/6.2) -----------
//
// The provenance-model change retrofits the loader so every emitted
// catalog/measurement individual carries prov:wasGeneratedBy the
// deterministic msrd:activity-loader-nist Activity IRI (alongside the
// existing prov:wasDerivedFrom msrd:nist-srd27), and so the loader itself
// emits the self-contained msrd:nist-srd27 msr:Dataset node + DOI (the
// hand-curated seed that used to define it is already gone -- design D3/D9).
// These tests are written against that task contract's agreed string
// literals (msrd:nist-srd27, msrd:activity-loader-nist,
// "doi:10.18434/mds2-2298") and are expected to fail on this isolated
// pass-1 branch until the coder's changes to nist.go land (buildInsertData
// does not yet emit any of this).
//
// Spec: openspec/changes/provenance-model/specs/nist-structured-loading/spec.md
//   - "Catalog triples emitted additively to the core data graph" (MODIFIED)
//   - "Loader is the sole source of the NIST dataset node and DOI" (ADDED)
//   - "Loader-run activity recorded in a named graph" (ADDED)
//   - "Idempotent re-runs across both stores" (MODIFIED)

// loaderActivityIRI, nistDatasetIRI, and nistDatasetDOI are already declared
// in nist.go (same package); reuse those production constants directly
// rather than redeclaring them here.

// countOccurrences reports how many non-overlapping times substr appears in
// s, used below to check a provenance predicate appears once per emitted
// individual rather than merely "somewhere" in the output.
func countOccurrences(s, substr string) int {
	return strings.Count(s, substr)
}

// TestBuildInsertData_MeasurementCarriesGenerationProvenance covers 6.1:
// every emitted PropertyMeasurement carries both prov:wasDerivedFrom
// msrd:nist-srd27 (already emitted pre-change) and the new
// prov:wasGeneratedBy msrd:activity-loader-nist, and no msr:citedIn is ever
// emitted (NIST SRD-27 has no per-row citation -- design D3; the blanket
// "no hand-curated edges" check above already covers citedIn for both
// fixtures, this test re-asserts it alongside the new generation edge for
// clarity).
func TestBuildInsertData_MeasurementCarriesGenerationProvenance(t *testing.T) {
	out := buildInsertData([]nist.Measurement{flibeDensityMeasurement(), kfZrf4IsothermMeasurement()})

	assertContains(t, out, "prov:wasDerivedFrom "+nistDatasetIRI)
	assertContains(t, out, "prov:wasGeneratedBy "+loaderActivityIRI)
	assertNotContains(t, out, "msr:citedIn")

	wantMeasurements := countOccurrences(out, "a msr:PropertyMeasurement")
	if wantMeasurements == 0 {
		t.Fatal("fixture produced zero msr:PropertyMeasurement blocks -- test fixture is broken")
	}
	gotGenerated := countOccurrences(out, "prov:wasGeneratedBy "+loaderActivityIRI)
	if gotGenerated < wantMeasurements {
		t.Errorf("\"prov:wasGeneratedBy %s\" appears %d times, want at least once per PropertyMeasurement (%d)",
			loaderActivityIRI, gotGenerated, wantMeasurements)
	}
}

// TestBuildInsertData_DatasetNodeWithDOI covers 6.1's "self-contained
// Dataset+DOI is present when loading into an empty data graph (no seed)":
// the loader is now the sole source of the msrd:nist-srd27 msr:Dataset node,
// carrying its DOI as dcterms:identifier, so every measurement's
// prov:wasDerivedFrom resolves to a real, DOI-bearing dataset even with the
// hand-curated seed gone (design D3/D9).
func TestBuildInsertData_DatasetNodeWithDOI(t *testing.T) {
	out := buildInsertData([]nist.Measurement{flibeDensityMeasurement()})

	assertContains(t, out, nistDatasetIRI+" a msr:Dataset")
	assertContains(t, out, "dcterms:identifier "+quoteLiteral(nistDatasetDOI))
}

// TestBuildInsertData_CatalogIndividualsCarryProvenance covers 6.1's
// "Catalog individuals carry provenance" scenario: every emitted
// MoltenSalt/Constituent/ChemicalCompound (not just PropertyMeasurement)
// carries prov:wasGeneratedBy msrd:activity-loader-nist and
// prov:wasDerivedFrom msrd:nist-srd27 -- design D1 scopes provenance to all
// instance data the loader asserts, not only measurements.
func TestBuildInsertData_CatalogIndividualsCarryProvenance(t *testing.T) {
	out := buildInsertData([]nist.Measurement{flibeDensityMeasurement(), kfZrf4IsothermMeasurement()})

	entityCount := countOccurrences(out, "a msr:MoltenSalt") +
		countOccurrences(out, "a msr:Constituent") +
		countOccurrences(out, "a msr:ChemicalCompound") +
		countOccurrences(out, "a msr:PropertyMeasurement")
	if entityCount == 0 {
		t.Fatal("fixtures produced zero catalog/measurement individuals -- test fixture is broken")
	}

	generatedCount := countOccurrences(out, "prov:wasGeneratedBy "+loaderActivityIRI)
	derivedCount := countOccurrences(out, "prov:wasDerivedFrom "+nistDatasetIRI)

	if generatedCount < entityCount {
		t.Errorf("\"prov:wasGeneratedBy %s\" appears %d times, want at least once per catalog/measurement individual (%d individuals)",
			loaderActivityIRI, generatedCount, entityCount)
	}
	if derivedCount < entityCount {
		t.Errorf("\"prov:wasDerivedFrom %s\" appears %d times, want at least once per catalog/measurement individual (%d individuals)",
			nistDatasetIRI, derivedCount, entityCount)
	}
}

// TestBuildInsertData_DeterministicAcrossCalls covers 6.2's loader
// idempotency requirement at the pure-function level: buildInsertData over
// the same measurements is byte-identical across calls, because every IRI
// it mints -- salt/constituent/compound/measurement, the msrd:nist-srd27
// Dataset node, and the msrd:activity-loader-nist reference each
// measurement/catalog individual carries -- is deterministic. Re-running
// the loader against unchanged input is therefore a set-semantics no-op in
// urn:msr:data (design D8; the urn:msr:data triple count and
// measurement_value row count are unaffected by a second run).
func TestBuildInsertData_DeterministicAcrossCalls(t *testing.T) {
	ms := []nist.Measurement{flibeDensityMeasurement(), kfZrf4IsothermMeasurement()}

	first := buildInsertData(ms)
	second := buildInsertData(ms)

	if first != second {
		t.Errorf("buildInsertData is not deterministic across calls with identical input:\n--- first ---\n%s\n--- second ---\n%s", first, second)
	}
}

// TestBuildRunGraphData_DeterministicWithFixedTimestamp covers 6.2's
// "audit-graph" carve-out from design D8: the wall-clock loader-run
// Activity *record* (urn:msr:run:loader/<ts>) is intentionally per-run, but
// with a FIXED injected timestamp the builder must still be a pure,
// deterministic function of its inputs, and the msrd:activity-loader-nist
// IRI it writes must be the exact IRI every measurement's
// prov:wasGeneratedBy references (so "everything from this run" is
// reachable by joining on that IRI).
//
// ASSUMPTION (pass-1, flagged in the tester handoff report for
// reconciliation at merge): this pins the task contract's suggested symbol
// buildRunGraphData(ts time.Time, version string) string in package main.
// It is not required to compile until the coder's loader change (which
// must expose *some* pure, timestamp-injectable builder for the run graph
// per task 2.4) lands; if the coder chooses a different name/signature,
// this test needs updating at merge, not the acceptance intent it encodes.
func TestBuildRunGraphData_DeterministicWithFixedTimestamp(t *testing.T) {
	fixedTS := time.Date(2024, 1, 2, 3, 4, 5, 0, time.UTC)

	first := buildRunGraphData(fixedTS, "0.3.0")
	second := buildRunGraphData(fixedTS, "0.3.0")

	if first != second {
		t.Errorf("buildRunGraphData is not deterministic for a fixed timestamp:\n--- first ---\n%s\n--- second ---\n%s", first, second)
	}

	assertContains(t, first, "GRAPH <urn:msr:run:loader/")
	assertContains(t, first, "a prov:Activity")
	assertContains(t, first, loaderActivityIRI)
	assertContains(t, first, "prov:wasAssociatedWith <agent:loader@0.3.0>")
	assertContains(t, first, "prov:startedAtTime")
	assertContains(t, first, "prov:endedAtTime")
	assertContains(t, first, `owl:versionInfo "0.3.0"`)
}
