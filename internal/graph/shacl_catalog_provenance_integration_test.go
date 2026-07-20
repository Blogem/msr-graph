package graph_test

// Task 7.10: opt-in GraphDB integration tests for the catalog-individual
// provenance shape (spec.md "Catalog-individual provenance shape" --
// msr:MoltenSalt, msr:Constituent, msr:ChemicalCompound each require
// prov:wasGeneratedBy + prov:wasDerivedFrom, minCount 1).

import (
	"fmt"
	"testing"
)

// catalogClasses are the three classes design.md/spec.md name for this
// shape.
var catalogClasses = []string{"msr:MoltenSalt", "msr:Constituent", "msr:ChemicalCompound"}

// catalogIndividualTriples renders a fixture individual of type class
// for subject msrd:<id>, with generatedBy/derivedFrom omitted from the
// Turtle when passed as "".
func catalogIndividualTriples(id, class, generatedBy, derivedFrom string) string {
	type pv struct{ pred, val string }
	pairs := []pv{{"a", class}}
	add := func(pred, val string) {
		if val != "" {
			pairs = append(pairs, pv{pred, val})
		}
	}
	add("prov:wasGeneratedBy", generatedBy)
	add("prov:wasDerivedFrom", derivedFrom)

	joined := ""
	for i, p := range pairs {
		if i > 0 {
			joined += " ;\n  "
		}
		joined += fmt.Sprintf("%s %s", p.pred, p.val)
	}
	return fmt.Sprintf("msrd:%s %s .\n", id, joined)
}

// TestCatalogProvenanceShape_MissingProvenanceIsRejected pins "Salt,
// constituent, or compound missing provenance is rejected", table-driven
// over the three classes and each of the two required PROV edges.
func TestCatalogProvenanceShape_MissingProvenanceIsRejected(t *testing.T) {
	client := requireGraphDB(t)

	for _, class := range catalogClasses {
		class := class
		t.Run(class+"/missing prov:wasGeneratedBy", func(t *testing.T) {
			id := uniqueLocal("catalog-incomplete")
			derivedFrom := fmt.Sprintf("msrd:%s-dataset", id)
			err := insertData(t, client, catalogIndividualTriples(id, class, "", derivedFrom))
			assertRejected(t, err, class+" missing prov:wasGeneratedBy")
		})
		t.Run(class+"/missing prov:wasDerivedFrom", func(t *testing.T) {
			id := uniqueLocal("catalog-incomplete")
			generatedBy := fmt.Sprintf("msrd:%s-activity", id)
			err := insertData(t, client, catalogIndividualTriples(id, class, generatedBy, ""))
			assertRejected(t, err, class+" missing prov:wasDerivedFrom")
		})
	}
}

// TestCatalogProvenanceShape_FullyProvenancedIndividualIsAccepted pins
// "Fully-provenanced catalog individual is accepted", table-driven over
// the three classes.
func TestCatalogProvenanceShape_FullyProvenancedIndividualIsAccepted(t *testing.T) {
	client := requireGraphDB(t)

	for _, class := range catalogClasses {
		class := class
		t.Run(class, func(t *testing.T) {
			id := uniqueLocal("catalog-complete")
			generatedBy := fmt.Sprintf("msrd:%s-activity", id)
			derivedFrom := fmt.Sprintf("msrd:%s-dataset", id)
			triples := catalogIndividualTriples(id, class, generatedBy, derivedFrom)

			err := insertData(t, client, triples)
			assertAccepted(t, err, class+" fully provenanced")
			t.Cleanup(func() { deleteData(t, client, triples) })
		})
	}
}
