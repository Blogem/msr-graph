package graph_test

// Task 7.4: opt-in GraphDB integration tests for the
// valid-temperature-range data-quality shape (spec.md
// "Valid-temperature-range data-quality shape", design D4's sh:sparql
// filter on validTempMin > validTempMax). Reuses
// completeMeasurementFields so the fixture is valid against every other
// shape (7.1 completeness, 7.3 unit allowlist) and only the
// temperature-range predicates vary.

import "testing"

// TestTempRangeShape_InvertedRangeIsRejected pins "Inverted range is
// rejected": validTempMin > validTempMax.
func TestTempRangeShape_InvertedRangeIsRejected(t *testing.T) {
	client := requireGraphDB(t)

	id := uniqueLocal("temp-inverted")
	fields := completeMeasurementFields(id)
	fields.validTempMin = `"600.0"^^xsd:decimal`
	fields.validTempMax = `"500.0"^^xsd:decimal`

	err := insertData(t, client, fields.triples(id))
	assertRejected(t, err, "inverted validTempMin/validTempMax")
}

// TestTempRangeShape_WellOrderedRangeIsAccepted pins "Well-ordered range
// is accepted": validTempMin <= validTempMax.
func TestTempRangeShape_WellOrderedRangeIsAccepted(t *testing.T) {
	client := requireGraphDB(t)

	id := uniqueLocal("temp-ordered")
	fields := completeMeasurementFields(id)
	fields.validTempMin = `"500.0"^^xsd:decimal`
	fields.validTempMax = `"600.0"^^xsd:decimal`
	triples := fields.triples(id)

	err := insertData(t, client, triples)
	assertAccepted(t, err, "well-ordered validTempMin/validTempMax")
	t.Cleanup(func() { deleteData(t, client, triples) })
}

// TestTempRangeShape_HalfPopulatedRangeIsRejected is an EXTRA scenario
// beyond spec.md's two named scenarios, pinning design.md's requirement
// prose directly: "both bounds are present and validTempMin <=
// validTempMax" -- a half-populated range (only validTempMin asserted)
// must also be rejected, not silently accepted as "no range asserted".
func TestTempRangeShape_HalfPopulatedRangeIsRejected(t *testing.T) {
	client := requireGraphDB(t)

	id := uniqueLocal("temp-half")
	fields := completeMeasurementFields(id)
	fields.validTempMin = `"500.0"^^xsd:decimal`
	// validTempMax deliberately left unset.

	err := insertData(t, client, fields.triples(id))
	assertRejected(t, err, "half-populated valid-temperature range (validTempMin without validTempMax)")
}
