package graph_test

// Task 7.3: opt-in GraphDB integration test for the unit allowlist
// data-quality shape (spec.md "Unit allowlist data-quality shape" --
// msr:hasUnit constrained via sh:in to ontology/qudt-units.json's
// allowedUnits array, design D3). Reuses completeMeasurementFields
// (shacl_measurement_integration_test.go) so only msr:hasUnit varies
// between the reject and accept fixtures -- every other required
// property is present, so a failure here can only be attributed to the
// unit-allowlist shape, not the completeness shape (task 7.1).

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// qudtAllowedUnits reads ontology/qudt-units.json's allowedUnits array --
// the single source of truth design D3 requires the shape to be
// generated from -- so this test's "allowed" fixture always agrees with
// whatever that file currently lists.
func qudtAllowedUnits(t *testing.T) []string {
	t.Helper()
	path := filepath.Join(repoRoot(t), "ontology", "qudt-units.json")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("reading %s: %v", path, err)
	}
	var doc struct {
		AllowedUnits []string `json:"allowedUnits"`
	}
	if err := json.Unmarshal(data, &doc); err != nil {
		t.Fatalf("parsing %s: %v", path, err)
	}
	if len(doc.AllowedUnits) == 0 {
		t.Fatalf("%s: allowedUnits is empty -- fixture assumption broken", path)
	}
	return doc.AllowedUnits
}

// unitCURIE converts a full QUDT unit IRI (http://qudt.org/vocab/unit/X)
// to its unit: CURIE form for use in a SPARQL fixture, matching the
// unit: prefix declared in shaclPrefixes.
func unitCURIE(t *testing.T, iri string) string {
	t.Helper()
	const ns = "http://qudt.org/vocab/unit/"
	if len(iri) <= len(ns) || iri[:len(ns)] != ns {
		t.Fatalf("unit IRI %q is not under the expected QUDT unit namespace %q", iri, ns)
	}
	return "unit:" + iri[len(ns):]
}

// TestUnitAllowlistShape_NonAllowlistUnitIsRejected pins "Non-allowlist
// unit is rejected": unit:PA is a real qudt:Unit (msr:meltingPoint's
// canonical unit, ontology/msr.ttl) but is deliberately absent from
// qudt-units.json's allowedUnits (only density/viscosity/surfaceTension/
// electricalConductivity's canonical units are allowlisted there), so it
// is a realistic non-allowlisted-but-real-unit fixture rather than a
// nonsense IRI.
func TestUnitAllowlistShape_NonAllowlistUnitIsRejected(t *testing.T) {
	client := requireGraphDB(t)

	allowed := qudtAllowedUnits(t)
	const disallowedUnit = "http://qudt.org/vocab/unit/PA"
	for _, u := range allowed {
		if u == disallowedUnit {
			t.Fatalf("test fixture assumption broken: %s is now in qudt-units.json's allowedUnits -- pick a different non-allowlisted unit for this fixture", disallowedUnit)
		}
	}

	id := uniqueLocal("unit-disallowed")
	fields := completeMeasurementFields(id)
	fields.hasUnit = unitCURIE(t, disallowedUnit)

	err := insertData(t, client, fields.triples(id))
	assertRejected(t, err, "measurement with non-allowlisted unit:PA")
}

// TestUnitAllowlistShape_AllowlistedUnitIsAccepted pins "Allowlisted unit
// is accepted", using the first entry of qudt-units.json's allowedUnits.
func TestUnitAllowlistShape_AllowlistedUnitIsAccepted(t *testing.T) {
	client := requireGraphDB(t)

	allowed := qudtAllowedUnits(t)
	id := uniqueLocal("unit-allowed")
	fields := completeMeasurementFields(id)
	fields.hasUnit = unitCURIE(t, allowed[0])
	triples := fields.triples(id)

	err := insertData(t, client, triples)
	assertAccepted(t, err, "measurement with allowlisted unit")
	t.Cleanup(func() { deleteData(t, client, triples) })
}
