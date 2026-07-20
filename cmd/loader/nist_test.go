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
//
// --- openspec/changes/provenance-run-lineage additions (tasks 5.1-5.5) -----
//
// This change's agreed task contract (tasks.md 2.1-2.5) replaces the single
// buildInsertData(ms) string with buildInsertData(ms, version) (string,
// []string) -- the second return value is the deduped, ordered slice of
// every fact IRI the call emitted (MoltenSalt/Constituent/ChemicalCompound/
// PropertyMeasurement/Dataset), so the caller can thread it into the
// provenance builder without re-deriving it. buildRunGraphData(ts, version)
// is replaced by buildProvenanceData(ts, version, factIRIs) string, which
// renders the GRAPH <urn:msr:provenance> update: the per-run
// urn:msr:run:loader/<ts> Activity node plus one prov:wasGeneratedBy edge
// per factIRI. It no longer touches urn:msr:src:*.

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
		t.Errorf("output missing %q\n--- full output ---\n%s", want, out)
	}
}

func assertNotContains(t *testing.T, out, unwanted string) {
	t.Helper()
	if strings.Contains(out, unwanted) {
		t.Errorf("output unexpectedly contains %q\n--- full output ---\n%s", unwanted, out)
	}
}

// TestBuildInsertData_FLiBeDensity covers the "FLiBe density measurement is
// queryable via the core client" scenario: the emitted INSERT DATA must
// carry every triple a consumer needs to resolve the measurement, its salt,
// unit, equation form, validity range, locator, and provenance.
func TestBuildInsertData_FLiBeDensity(t *testing.T) {
	out, _ := buildInsertData([]nist.Measurement{flibeDensityMeasurement()}, ontologyVersion)

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
	out, _ := buildInsertData([]nist.Measurement{flibeDensityMeasurement()}, ontologyVersion)

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
	out, _ := buildInsertData([]nist.Measurement{kfZrf4IsothermMeasurement()}, ontologyVersion)

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
	out, _ := buildInsertData([]nist.Measurement{flibeDensityMeasurement(), kfZrf4IsothermMeasurement()}, ontologyVersion)

	for _, unwanted := range []string{"msr:hasRole", "msr:usedIn", "msr:citedIn", "skos:closeMatch"} {
		assertNotContains(t, out, unwanted)
	}
}

// TestBuildInsertData_Empty documents the trivial boundary: an empty
// measurement slice should not panic. buildInsertData ALWAYS emits the
// msrd:nist-srd27 Dataset node -- it is a derivation root, emitted
// regardless of measurement count (design D3, task 5.2) -- so even a nil
// measurement slice yields exactly one fact IRI: the Dataset node itself.
// This guards against buildInsertData dereferencing ms[0] unconditionally,
// while still pinning that the Dataset node is always a fact IRI carrying a
// generation edge.
func TestBuildInsertData_Empty(t *testing.T) {
	defer func() {
		if r := recover(); r != nil {
			t.Fatalf("buildInsertData(nil) panicked: %v", r)
		}
	}()
	_, factIRIs := buildInsertData(nil, ontologyVersion)
	if len(factIRIs) != 1 || factIRIs[0] != nistDatasetIRI {
		t.Errorf("buildInsertData(nil) returned fact IRIs %v, want exactly [%s]", factIRIs, nistDatasetIRI)
	}
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
	out, _ := buildInsertData([]nist.Measurement{flibeDensityMeasurement(), kfZrf4IsothermMeasurement()}, ontologyVersion)

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
	out, _ := buildInsertData([]nist.Measurement{flibeDensityMeasurement()}, ontologyVersion)

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
	out, _ := buildInsertData([]nist.Measurement{flibeDensityMeasurement(), kfZrf4IsothermMeasurement()}, ontologyVersion)

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

	first, firstIRIs := buildInsertData(ms, ontologyVersion)
	second, secondIRIs := buildInsertData(ms, ontologyVersion)

	if first != second {
		t.Errorf("buildInsertData is not deterministic across calls with identical input:\n--- first ---\n%s\n--- second ---\n%s", first, second)
	}
	if strings.Join(firstIRIs, ",") != strings.Join(secondIRIs, ",") {
		t.Errorf("buildInsertData fact-IRI slice is not deterministic across calls:\nfirst:  %v\nsecond: %v", firstIRIs, secondIRIs)
	}
}

// --- openspec/changes/provenance-run-lineage additions (tasks 5.1-5.5) -----
//
// buildRunGraphData(ts, version) is REPLACED by
// buildProvenanceData(ts time.Time, version string, factIRIs []string) string
// (task 2.2): it renders the additive INSERT DATA targeting
// GRAPH <urn:msr:provenance> only -- the per-run activity node
// <urn:msr:run:loader/<ts>> plus one <factIRI> prov:wasGeneratedBy <run> edge
// per element of factIRIs. It no longer touches urn:msr:src:*, and it no
// longer re-emits the stable msrd:activity-loader-nist typing -- that moved
// into buildInsertData (task 2.1), which now also returns the deduped,
// ordered fact-IRI slice these tests thread into buildProvenanceData.
//
// Spec: openspec/changes/provenance-run-lineage/specs/{nist-structured-loading,provenance-model}/spec.md
//   - "Loader-run activity recorded in a named graph" (MODIFIED)
//   - "Per-run generation lineage" (ADDED)
//   - "A single provenance graph holds run activities and lineage" (ADDED)
//   - "Generating activities record agent, timestamps, and ontology version" (MODIFIED)

// runFactIRIs is a small helper: build the two fixtures' INSERT DATA and
// return the fact-IRI slice buildInsertData reports for them, so the
// provenance tests below don't have to re-derive the entity list by hand.
func runFactIRIs(t *testing.T) []string {
	t.Helper()
	_, factIRIs := buildInsertData([]nist.Measurement{flibeDensityMeasurement(), kfZrf4IsothermMeasurement()}, ontologyVersion)
	return factIRIs
}

// TestBuildProvenanceData_RunActivity covers 5.1: the provenance update
// targets GRAPH <urn:msr:provenance> and contains the per-run activity
// <urn:msr:run:loader/<ts>> fully attributed (agent, start/end timestamps,
// ontology version).
func TestBuildProvenanceData_RunActivity(t *testing.T) {
	fixedTS := time.Date(2024, 1, 2, 3, 4, 5, 0, time.UTC)
	tsStr := fixedTS.UTC().Format(time.RFC3339)
	factIRIs := runFactIRIs(t)

	out := buildProvenanceData(fixedTS, ontologyVersion, factIRIs)

	assertContains(t, out, "GRAPH <urn:msr:provenance>")
	runIRI := "urn:msr:run:loader/" + tsStr
	assertContains(t, out, "<"+runIRI+">")
	assertContains(t, out, "a prov:Activity")
	assertContains(t, out, "prov:wasAssociatedWith <agent:loader@"+ontologyVersion+">")
	assertContains(t, out, "prov:startedAtTime")
	assertContains(t, out, "prov:endedAtTime")
	assertContains(t, out, `owl:versionInfo "`+ontologyVersion+`"`)
}

// TestBuildProvenanceData_GenerationEdgeCountParity covers 5.2: every fact
// IRI buildInsertData reports appears exactly once as the subject of a
// prov:wasGeneratedBy <run> edge in buildProvenanceData's output, the total
// edge count equals len(factIRIs), and the slice is not missing any
// subject-typed fact buildInsertData actually emitted (sanity check that
// the slice and the INSERT DATA output agree on "how many facts").
func TestBuildProvenanceData_GenerationEdgeCountParity(t *testing.T) {
	insertOut, factIRIs := buildInsertData([]nist.Measurement{flibeDensityMeasurement(), kfZrf4IsothermMeasurement()}, ontologyVersion)
	if len(factIRIs) == 0 {
		t.Fatal("buildInsertData returned zero fact IRIs -- fixtures produced nothing to check")
	}

	// Sanity: the number of distinct typed individuals buildInsertData
	// actually wrote (Dataset + every MoltenSalt/Constituent/
	// ChemicalCompound/PropertyMeasurement block) must equal len(factIRIs) --
	// the slice must be neither missing facts nor padded with extras.
	entityCount := countOccurrences(insertOut, "a msr:Dataset") +
		countOccurrences(insertOut, "a msr:MoltenSalt") +
		countOccurrences(insertOut, "a msr:Constituent") +
		countOccurrences(insertOut, "a msr:ChemicalCompound") +
		countOccurrences(insertOut, "a msr:PropertyMeasurement")
	if entityCount != len(factIRIs) {
		t.Errorf("buildInsertData emitted %d typed individuals but returned %d fact IRIs, want equal\nfactIRIs: %v", entityCount, len(factIRIs), factIRIs)
	}

	// No duplicate IRIs in the returned slice.
	seen := make(map[string]bool, len(factIRIs))
	for _, iri := range factIRIs {
		if seen[iri] {
			t.Errorf("buildInsertData fact-IRI slice contains duplicate %q: %v", iri, factIRIs)
		}
		seen[iri] = true
	}

	fixedTS := time.Date(2024, 1, 2, 3, 4, 5, 0, time.UTC)
	tsStr := fixedTS.UTC().Format(time.RFC3339)
	runIRI := "urn:msr:run:loader/" + tsStr
	provOut := buildProvenanceData(fixedTS, ontologyVersion, factIRIs)

	totalEdges := countOccurrences(provOut, "prov:wasGeneratedBy <"+runIRI+">")
	if totalEdges != len(factIRIs) {
		t.Errorf("buildProvenanceData emitted %d generation edges to <%s>, want exactly %d (one per fact IRI)", totalEdges, runIRI, len(factIRIs))
	}

	for _, iri := range factIRIs {
		want := iri + " prov:wasGeneratedBy <" + runIRI + ">"
		got := countOccurrences(provOut, want)
		if got != 1 {
			t.Errorf("fact IRI %q has %d generation edges to <%s>, want exactly 1", iri, got, runIRI)
		}
	}
}

// TestBuildInsertData_StableActivityNoTimestamps covers 5.3: buildInsertData
// types the stable msrd:activity-loader-nist as a prov:Activity with no
// timestamp literals at all -- neither an xsd:dateTime literal nor a
// startedAtTime/endedAtTime predicate -- so urn:msr:data stays a
// set-semantics no-op across re-runs.
func TestBuildInsertData_StableActivityNoTimestamps(t *testing.T) {
	out, _ := buildInsertData([]nist.Measurement{flibeDensityMeasurement()}, ontologyVersion)

	assertContains(t, out, loaderActivityIRI+" a prov:Activity")
	assertContains(t, out, "prov:wasAssociatedWith <agent:loader@"+ontologyVersion+">")
	assertContains(t, out, `owl:versionInfo "`+ontologyVersion+`"`)

	assertNotContains(t, out, "xsd:dateTime")
	assertNotContains(t, out, "startedAtTime")
	assertNotContains(t, out, "endedAtTime")
}

// TestNoSourceGraphAnywhere covers 5.4: neither buildInsertData nor
// buildProvenanceData ever names a urn:msr:src:* graph -- the per-source
// audit graph is removed entirely (design D2), the Dataset node stays
// self-contained in urn:msr:data, and the run identifier survives only as
// the per-run activity node IRI inside urn:msr:provenance.
func TestNoSourceGraphAnywhere(t *testing.T) {
	insertOut, factIRIs := buildInsertData([]nist.Measurement{flibeDensityMeasurement(), kfZrf4IsothermMeasurement()}, ontologyVersion)
	assertNotContains(t, insertOut, "urn:msr:src:")

	fixedTS := time.Date(2024, 1, 2, 3, 4, 5, 0, time.UTC)
	provOut := buildProvenanceData(fixedTS, ontologyVersion, factIRIs)
	assertNotContains(t, provOut, "urn:msr:src:")
}

// TestBuildProvenanceData_AppendOnlyAcrossRuns covers 5.5: two distinct ts
// values produce two distinct per-run activity IRIs and two disjoint sets of
// generation edges -- a generation edge minted for run A's per-run activity
// never appears in run B's output and vice versa, matching the append-only
// lineage semantics (design D2/D4): rollback or inspection of one run's
// output never leaks into another run's.
func TestBuildProvenanceData_AppendOnlyAcrossRuns(t *testing.T) {
	factIRIs := runFactIRIs(t)

	tsA := time.Date(2024, 1, 2, 3, 4, 5, 0, time.UTC)
	tsB := time.Date(2024, 6, 7, 8, 9, 10, 0, time.UTC)
	runA := "urn:msr:run:loader/" + tsA.UTC().Format(time.RFC3339)
	runB := "urn:msr:run:loader/" + tsB.UTC().Format(time.RFC3339)

	outA := buildProvenanceData(tsA, ontologyVersion, factIRIs)
	outB := buildProvenanceData(tsB, ontologyVersion, factIRIs)

	assertContains(t, outA, "<"+runA+">")
	assertNotContains(t, outA, "<"+runB+">")
	assertContains(t, outB, "<"+runB+">")
	assertNotContains(t, outB, "<"+runA+">")

	for _, iri := range factIRIs {
		edgeA := iri + " prov:wasGeneratedBy <" + runA + ">"
		edgeB := iri + " prov:wasGeneratedBy <" + runB + ">"

		if !strings.Contains(outA, edgeA) {
			t.Errorf("run A output missing its own generation edge for %q", iri)
		}
		if strings.Contains(outA, edgeB) {
			t.Errorf("run A output unexpectedly contains run B's generation edge for %q", iri)
		}
		if !strings.Contains(outB, edgeB) {
			t.Errorf("run B output missing its own generation edge for %q", iri)
		}
		if strings.Contains(outB, edgeA) {
			t.Errorf("run B output unexpectedly contains run A's generation edge for %q", iri)
		}
	}
}
