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
// accepted": msr:linksTo pointing at msr:MoltenSalt, an owl:Class
// individual that always exists in urn:msr:ontology (static seed data,
// no dependency on any other test/loader having run), which is
// unambiguously an existing target of the "class" kind.
func TestLinksToShape_WellFormedLinkIsAccepted(t *testing.T) {
	client := requireGraphDB(t)

	id := uniqueLocal("linksto-wellformed")
	triples := linksToTriples(id, "msr:MoltenSalt")

	err := insertData(t, client, triples)
	assertAccepted(t, err, "linksTo pointing at the existing msr:MoltenSalt class")
	t.Cleanup(func() { deleteData(t, client, triples) })
}
