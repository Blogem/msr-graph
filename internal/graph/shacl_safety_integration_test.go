package graph_test

// Task 8.8 (ingest-iaea-safety, chunk 11): opt-in GraphDB integration
// tests for the safety-genre shapes added to the catalogue by task 5.2
// (deploy/graphdb/msr-shapes.ttl §2.6 -- msr:SafetyIndividualProvenanceShape,
// msr:ServedByPropertyTargetShape, msr:AddressesFunctionTargetShape).
// Design D6: "SafetyFunction and Requirement each require
// prov:wasDerivedFrom + prov:wasGeneratedBy; a servedByProperty edge's
// target must be an existing core PhysicalProperty; an addressesFunction
// edge's target must be a SafetyFunction." No threshold/satisfaction
// shape exists (D5 -- thresholds are a soft, agent-computed criterion,
// never a SHACL gate), so no test targets one here.
//
// Like every other shacl_*_integration_test.go file in this package, these
// tests are gated by requireGraphDB(t) (via the shared
// shacl_helpers_integration_test.go helpers): unreachable + GRAPHDB_REQUIRED
// unset -> t.Skip; unreachable + GRAPHDB_REQUIRED set -> t.Fatal. This file
// has no compile-time dependency on a live GraphDB and compiles/vets
// standalone.

import (
	"fmt"
	"strings"
	"testing"
)

// safetyIndividualTriples renders a fixture msr:SafetyFunction or
// msr:Requirement individual for subject msrd:<id>, with
// generatedBy/derivedFrom omitted from the Turtle when passed as ""
// (mirrors catalogIndividualTriples in shacl_catalog_provenance_integration_test.go).
func safetyIndividualTriples(id, class, generatedBy, derivedFrom string) string {
	type pv struct{ pred, val string }
	pairs := []pv{{"a", class}}
	add := func(pred, val string) {
		if val != "" {
			pairs = append(pairs, pv{pred, val})
		}
	}
	add("prov:wasGeneratedBy", generatedBy)
	add("prov:wasDerivedFrom", derivedFrom)

	var joined strings.Builder
	for i, p := range pairs {
		if i > 0 {
			joined.WriteString(" ;\n  ")
		}
		fmt.Fprintf(&joined, "%s %s", p.pred, p.val)
	}
	return fmt.Sprintf("msrd:%s %s .\n", id, joined.String())
}

// safetyClasses are the two classes msr:SafetyIndividualProvenanceShape
// (deploy/graphdb/msr-shapes.ttl §2.6.1) targets.
var safetyClasses = []string{"msr:SafetyFunction", "msr:Requirement"}

// TestSafetyProvenanceShape_MissingProvenanceIsRejected pins design D6 /
// task 8.8's "a msr:SafetyFunction individual missing
// prov:wasDerivedFrom is REJECTED by msr:SafetyIndividualProvenanceShape",
// table-driven over both safety-genre classes and each of the two
// required PROV edges (mirroring TestCatalogProvenanceShape_MissingProvenanceIsRejected).
func TestSafetyProvenanceShape_MissingProvenanceIsRejected(t *testing.T) {
	client := requireGraphDB(t)

	for _, class := range safetyClasses {
		t.Run(class+"/missing prov:wasDerivedFrom", func(t *testing.T) {
			id := uniqueLocal("safety-incomplete")
			generatedBy := fmt.Sprintf("msrd:%s-activity", id)
			err := insertData(t, client, safetyIndividualTriples(id, class, generatedBy, ""))
			assertRejected(t, err, class+" missing prov:wasDerivedFrom")
		})
		t.Run(class+"/missing prov:wasGeneratedBy", func(t *testing.T) {
			id := uniqueLocal("safety-incomplete")
			derivedFrom := fmt.Sprintf("msrd:%s-document", id)
			err := insertData(t, client, safetyIndividualTriples(id, class, "", derivedFrom))
			assertRejected(t, err, class+" missing prov:wasGeneratedBy")
		})
	}
}

// TestSafetyProvenanceShape_FullyProvenancedIndividualIsAccepted pins the
// accept half of msr:SafetyIndividualProvenanceShape: a fully-attributed
// safety individual (both PROV edges present) loads, table-driven over
// both safety-genre classes.
func TestSafetyProvenanceShape_FullyProvenancedIndividualIsAccepted(t *testing.T) {
	client := requireGraphDB(t)

	for _, class := range safetyClasses {
		t.Run(class, func(t *testing.T) {
			id := uniqueLocal("safety-complete")
			generatedBy := fmt.Sprintf("msrd:%s-activity", id)
			derivedFrom := fmt.Sprintf("msrd:%s-document", id)
			triples := safetyIndividualTriples(id, class, generatedBy, derivedFrom)

			err := insertData(t, client, triples)
			assertAccepted(t, err, class+" fully provenanced")
			t.Cleanup(func() { deleteData(t, client, triples) })
		})
	}
}

// TestSafetyServedByPropertyShape_ValidPhysicalPropertyTargetIsAccepted pins
// design D6 / task 8.8's "a valid servedByProperty -> PhysicalProperty
// edge LOADS" (msr:ServedByPropertyTargetShape, msr-shapes.ttl §2.6.2). A
// fully-provenanced msr:SafetyFunction individual asserts
// msr:servedByProperty against msr:specificHeat -- a seed
// msr:PhysicalProperty individual already declared in the core ontology
// (ontology/msr.ttl), so the target-kind check can only be attributed to
// this shape, not to any provenance shape on the target.
func TestSafetyServedByPropertyShape_ValidPhysicalPropertyTargetIsAccepted(t *testing.T) {
	client := requireGraphDB(t)

	id := uniqueLocal("safety-servedby")
	generatedBy := fmt.Sprintf("msrd:%s-activity", id)
	derivedFrom := fmt.Sprintf("msrd:%s-document", id)
	triples := fmt.Sprintf(
		"msrd:%s a msr:SafetyFunction ;\n"+
			"  prov:wasGeneratedBy %s ;\n"+
			"  prov:wasDerivedFrom %s ;\n"+
			"  msr:servedByProperty msr:specificHeat .\n",
		id, generatedBy, derivedFrom,
	)

	err := insertData(t, client, triples)
	assertAccepted(t, err, "servedByProperty targeting an existing core msr:PhysicalProperty (msr:specificHeat)")
	t.Cleanup(func() { deleteData(t, client, triples) })
}

// TestSafetyServedByPropertyShape_NonPhysicalPropertyTargetIsRejected pins the
// reject half of msr:ServedByPropertyTargetShape: a servedByProperty
// edge whose target is not a msr:PhysicalProperty (here, a bare
// skos:Concept individual freshly minted in the same transaction) is
// rejected, even though the subject itself is fully provenanced.
func TestSafetyServedByPropertyShape_NonPhysicalPropertyTargetIsRejected(t *testing.T) {
	client := requireGraphDB(t)

	id := uniqueLocal("safety-servedby-wrongkind")
	targetID := uniqueLocal("safety-servedby-wrongkind-target")
	target := fmt.Sprintf("msrd:%s", targetID)
	generatedBy := fmt.Sprintf("msrd:%s-activity", id)
	derivedFrom := fmt.Sprintf("msrd:%s-document", id)
	triples := fmt.Sprintf(
		"%s a skos:Concept .\n"+
			"msrd:%s a msr:SafetyFunction ;\n"+
			"  prov:wasGeneratedBy %s ;\n"+
			"  prov:wasDerivedFrom %s ;\n"+
			"  msr:servedByProperty %s .\n",
		target, id, generatedBy, derivedFrom, target,
	)

	err := insertData(t, client, triples)
	assertRejected(t, err, "servedByProperty targeting a non-PhysicalProperty individual")
}
