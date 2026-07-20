package graph_test

// Task 7.1: opt-in GraphDB integration tests for the measurement
// provenance/completeness shape (spec.md "Measurement provenance and
// completeness shape" -- prov:wasDerivedFrom, prov:wasGeneratedBy,
// msr:dataLocator, msr:forProperty, msr:ofSalt, msr:hasUnit,
// msr:equationForm, minCount 1 each; msr:citedIn deliberately NOT
// required per design.md/tasks.md 2.1). Uses the shared
// insertData/deleteData/uniqueLocal/assertRejected/assertAccepted helpers
// in shacl_helpers_integration_test.go.
//
// measurementFields/completeMeasurementFields are also reused by
// shacl_unit_allowlist_integration_test.go (7.3) and
// shacl_temp_range_integration_test.go (7.4) so their fixtures stay valid
// against this shape too (a single commit is checked against every
// installed shape at once).

import (
	"fmt"
	"testing"
)

// measurementFields holds one value per required property of the
// measurement-completeness shape, plus the two optional
// valid-temperature-range bounds task 7.4 exercises. An empty field is
// omitted from the generated Turtle, producing a fixture missing that
// property.
type measurementFields struct {
	derivedFrom  string
	generatedBy  string
	dataLocator  string
	forProperty  string
	ofSalt       string
	hasUnit      string
	equationForm string
	validTempMin string
	validTempMax string
}

// completeMeasurementFields returns a fixture with every required
// property populated with a plausible, self-contained value (no
// dependency on any other test's data): prov edges point at
// freshly-minted synthetic dataset/activity IRIs, forProperty/
// equationForm point at real ontology individuals that always exist
// (urn:msr:ontology is static seed data), hasUnit is a real
// QUDT-allowlisted unit, and ofSalt points at a freshly-minted salt IRI
// (the completeness shape only requires the property's presence, not
// that the target carries a particular rdf:type -- that existence/kind
// check is msr:linksTo's job, task 7.5). validTempMin/Max are left unset
// by default since they are optional for this shape.
func completeMeasurementFields(id string) measurementFields {
	return measurementFields{
		derivedFrom:  fmt.Sprintf("msrd:%s-dataset", id),
		generatedBy:  fmt.Sprintf("msrd:%s-activity", id),
		dataLocator:  fmt.Sprintf(`"test/shacl-fixture#%s"`, id),
		forProperty:  "msr:density",
		ofSalt:       fmt.Sprintf("msrd:%s-salt", id),
		hasUnit:      "unit:GM-PER-CentiM3",
		equationForm: "msr:Linear",
	}
}

// triples renders the fixture as the body of an INSERT/DELETE DATA block
// for subject msrd:<id>, joining only the non-empty fields.
func (f measurementFields) triples(id string) string {
	type pv struct{ pred, val string }
	pairs := []pv{{"a", "msr:PropertyMeasurement"}}
	add := func(pred, val string) {
		if val != "" {
			pairs = append(pairs, pv{pred, val})
		}
	}
	add("prov:wasDerivedFrom", f.derivedFrom)
	add("prov:wasGeneratedBy", f.generatedBy)
	add("msr:dataLocator", f.dataLocator)
	add("msr:forProperty", f.forProperty)
	add("msr:ofSalt", f.ofSalt)
	add("msr:hasUnit", f.hasUnit)
	add("msr:equationForm", f.equationForm)
	add("msr:validTempMin", f.validTempMin)
	add("msr:validTempMax", f.validTempMax)

	joined := ""
	for i, p := range pairs {
		if i > 0 {
			joined += " ;\n  "
		}
		joined += fmt.Sprintf("%s %s", p.pred, p.val)
	}
	return fmt.Sprintf("msrd:%s %s .\n", id, joined)
}

// TestMeasurementShape_MissingRequiredPropertyIsRejected pins spec.md's
// "Measurement missing provenance is rejected" scenario: a
// msr:PropertyMeasurement missing ANY one of the seven required
// properties must be rejected on commit. Table-driven over all seven.
func TestMeasurementShape_MissingRequiredPropertyIsRejected(t *testing.T) {
	client := requireGraphDB(t)

	tests := []struct {
		name string
		zero func(*measurementFields)
	}{
		{"missing prov:wasDerivedFrom", func(f *measurementFields) { f.derivedFrom = "" }},
		{"missing prov:wasGeneratedBy", func(f *measurementFields) { f.generatedBy = "" }},
		{"missing msr:dataLocator", func(f *measurementFields) { f.dataLocator = "" }},
		{"missing msr:forProperty", func(f *measurementFields) { f.forProperty = "" }},
		{"missing msr:ofSalt", func(f *measurementFields) { f.ofSalt = "" }},
		{"missing msr:hasUnit", func(f *measurementFields) { f.hasUnit = "" }},
		{"missing msr:equationForm", func(f *measurementFields) { f.equationForm = "" }},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			id := uniqueLocal("measurement-incomplete")
			fields := completeMeasurementFields(id)
			tc.zero(&fields)

			err := insertData(t, client, fields.triples(id))
			assertRejected(t, err, tc.name)
		})
	}
}

// TestMeasurementShape_CompleteMeasurementIsAccepted pins spec.md's
// "Complete measurement is accepted" scenario: all seven required
// properties present (including prov:wasDerivedFrom and
// prov:wasGeneratedBy), with no msr:citedIn asserted, commits
// successfully.
func TestMeasurementShape_CompleteMeasurementIsAccepted(t *testing.T) {
	client := requireGraphDB(t)

	id := uniqueLocal("measurement-complete")
	fields := completeMeasurementFields(id)
	triples := fields.triples(id)

	err := insertData(t, client, triples)
	assertAccepted(t, err, "complete measurement")
	t.Cleanup(func() { deleteData(t, client, triples) })
}
