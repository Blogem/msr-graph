package graph_test

// Task 7.2: opt-in GraphDB integration tests for the msr:Mention
// provenance shape (spec.md "Mention provenance shape" --
// msr:inDocument, msr:startOffset, msr:endOffset, msr:surfaceForm,
// prov:wasDerivedFrom, prov:wasGeneratedBy, minCount 1 each).
//
// mentionFields/completeMentionFields are also reused by
// shacl_linksto_integration_test.go (7.5) so its fixtures stay valid
// against this completeness shape too.

import (
	"fmt"
	"testing"
)

// mentionFields holds one value per required property of the
// Mention-provenance shape. An empty field is omitted from the generated
// Turtle, producing a fixture missing that property.
type mentionFields struct {
	inDocument  string
	startOffset string
	endOffset   string
	surfaceForm string
	derivedFrom string
	generatedBy string
}

// completeMentionFields returns a fixture with every required property
// populated: inDocument points at a freshly-minted synthetic Document
// IRI, offsets are plain xsd:integer literals, surfaceForm is a quoted
// string literal, and the PROV edges point at freshly-minted synthetic
// dataset/activity IRIs -- self-contained, no dependency on any other
// test's data.
func completeMentionFields(id string) mentionFields {
	return mentionFields{
		inDocument:  fmt.Sprintf("msrd:%s-doc", id),
		startOffset: "10",
		endOffset:   "15",
		surfaceForm: `"FLiBe"`,
		derivedFrom: fmt.Sprintf("msrd:%s-dataset", id),
		generatedBy: fmt.Sprintf("msrd:%s-activity", id),
	}
}

// triples renders the fixture as the body of an INSERT/DELETE DATA block
// for subject msrd:<id>, joining only the non-empty fields.
func (f mentionFields) triples(id string) string {
	type pv struct{ pred, val string }
	pairs := []pv{{"a", "msr:Mention"}}
	add := func(pred, val string) {
		if val != "" {
			pairs = append(pairs, pv{pred, val})
		}
	}
	add("msr:inDocument", f.inDocument)
	add("msr:startOffset", f.startOffset)
	add("msr:endOffset", f.endOffset)
	add("msr:surfaceForm", f.surfaceForm)
	add("prov:wasDerivedFrom", f.derivedFrom)
	add("prov:wasGeneratedBy", f.generatedBy)

	joined := ""
	for i, p := range pairs {
		if i > 0 {
			joined += " ;\n  "
		}
		joined += fmt.Sprintf("%s %s", p.pred, p.val)
	}
	return fmt.Sprintf("msrd:%s %s .\n", id, joined)
}

// TestMentionShape_MissingRequiredPropertyIsRejected pins spec.md's
// "Mention without source document is rejected" scenario, table-driven
// over all six required properties (the scenario names msr:inDocument
// explicitly and "or without prov:wasDerivedFrom / prov:wasGeneratedBy").
func TestMentionShape_MissingRequiredPropertyIsRejected(t *testing.T) {
	client := requireGraphDB(t)

	tests := []struct {
		name string
		zero func(*mentionFields)
	}{
		{"missing msr:inDocument", func(f *mentionFields) { f.inDocument = "" }},
		{"missing msr:startOffset", func(f *mentionFields) { f.startOffset = "" }},
		{"missing msr:endOffset", func(f *mentionFields) { f.endOffset = "" }},
		{"missing msr:surfaceForm", func(f *mentionFields) { f.surfaceForm = "" }},
		{"missing prov:wasDerivedFrom", func(f *mentionFields) { f.derivedFrom = "" }},
		{"missing prov:wasGeneratedBy", func(f *mentionFields) { f.generatedBy = "" }},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			id := uniqueLocal("mention-incomplete")
			fields := completeMentionFields(id)
			tc.zero(&fields)

			err := insertData(t, client, fields.triples(id))
			assertRejected(t, err, tc.name)
		})
	}
}

// TestMentionShape_CompleteMentionIsAccepted pins spec.md's "Complete
// mention is accepted" scenario.
func TestMentionShape_CompleteMentionIsAccepted(t *testing.T) {
	client := requireGraphDB(t)

	id := uniqueLocal("mention-complete")
	fields := completeMentionFields(id)
	triples := fields.triples(id)

	err := insertData(t, client, triples)
	assertAccepted(t, err, "complete mention")
	t.Cleanup(func() { deleteData(t, client, triples) })
}
