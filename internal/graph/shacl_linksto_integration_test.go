package graph_test

// Task 7.5: opt-in GraphDB integration tests for the msr:linksTo
// target-kind data-quality shape (spec.md "linksTo target-kind
// data-quality shape", design D4). The mention fixture is otherwise
// complete (satisfies the task 7.2 completeness shape) so only the
// linksTo target varies between the reject and accept cases.
//
// Coverage note: the "dangling reference" half of spec.md's "Dangling or
// wrong-kind link is rejected" scenario is exercised precisely (a linksTo
// target IRI with zero triples anywhere in the store). The "wrong-kind"
// half is NOT independently exercised here: design D4 defines the
// expected kinds only as "concept / class / individual" without pinning
// which existing-but-differently-typed resource would count as
// definitely wrong-kind under the (not yet authored) shape -- constructing
// an unambiguous wrong-kind-but-existing fixture without seeing the
// shape's actual sh:sparql/sh:class expression would risk testing the
// wrong thing. Flagged as a partial-coverage gap in the handoff report.

import (
	"fmt"
	"testing"
)

// linksToTriples builds a msr:Mention fixture that is complete against
// the task 7.2 shape (every required property present) plus msr:linksTo
// pointing at target, so a rejection can only be attributed to the
// linksTo target-kind shape.
func linksToTriples(id, target string) string {
	f := completeMentionFields(id)
	return fmt.Sprintf(
		"msrd:%s a msr:Mention ;\n"+
			"  msr:inDocument %s ;\n"+
			"  msr:startOffset %s ;\n"+
			"  msr:endOffset %s ;\n"+
			"  msr:surfaceForm %s ;\n"+
			"  prov:wasDerivedFrom %s ;\n"+
			"  prov:wasGeneratedBy %s ;\n"+
			"  msr:linksTo %s .\n",
		id, f.inDocument, f.startOffset, f.endOffset, f.surfaceForm, f.derivedFrom, f.generatedBy, target,
	)
}

// TestLinksToShape_DanglingTargetIsRejected pins the "dangling ... link is
// rejected" half of spec.md's scenario: msr:linksTo pointing at an IRI
// that has no triples anywhere in the store (neither as subject nor
// object) cannot be an "existing target of the expected kind".
func TestLinksToShape_DanglingTargetIsRejected(t *testing.T) {
	client := requireGraphDB(t)

	id := uniqueLocal("linksto-dangling")
	danglingTarget := fmt.Sprintf("msrd:%s-nonexistent-target", id)

	err := insertData(t, client, linksToTriples(id, danglingTarget))
	assertRejected(t, err, "linksTo pointing at a dangling (non-existent) target")
}

// TestLinksToShape_WellFormedLinkIsAccepted pins "Well-formed link is
// accepted": msr:linksTo pointing at an existing, explicitly-typed target
// of one of the shape's expected kinds is accepted.
//
// The target is a freshly-minted skos:Concept individual inserted in the
// SAME transaction as the Mention fixture, rather than a dependency on the
// msr:MoltenSalt ontology seed being loaded: this keeps the test
// self-contained and hermetic (no hidden dependency on external repo
// state). A skos:Concept is deliberately chosen over a fresh
// msr:MoltenSalt individual, which would ALSO be caught by the
// catalog-provenance shape (2.5, msr:CatalogIndividualProvenanceShape
// targets msr:MoltenSalt/Constituent/ChemicalCompound and requires
// prov:wasGeneratedBy/wasDerivedFrom) -- a bare skos:Concept individual is
// not subject to any provenance shape, so its acceptance can only be
// attributed to msr:LinksToTargetKindShape.
func TestLinksToShape_WellFormedLinkIsAccepted(t *testing.T) {
	client := requireGraphDB(t)

	id := uniqueLocal("linksto-wellformed")
	targetID := uniqueLocal("linksto-wellformed-target")
	target := fmt.Sprintf("msrd:%s", targetID)
	targetTriples := fmt.Sprintf("%s a skos:Concept .\n", target)
	triples := targetTriples + linksToTriples(id, target)

	err := insertData(t, client, triples)
	assertAccepted(t, err, "linksTo pointing at a freshly-minted, self-contained skos:Concept target")
	t.Cleanup(func() { deleteData(t, client, triples) })
}
