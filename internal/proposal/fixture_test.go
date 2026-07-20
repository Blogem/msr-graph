package proposal_test

// Shared fixtures and query helpers for the internal/proposal integration
// tests (task 2.5 / 3.6). Each fixture builds a deterministic-shape,
// unique-per-run proposal: a msr:ChangeProposal resource in urn:msr:staging
// plus its proposed triples in urn:msr:proposal/{id}, mirroring the
// two-graph staging model from change-proposal-schema/spec.md.
//
// Subject IRIs are suffixed with a per-run nanosecond timestamp (per the
// task brief's hermeticity requirement: "generate unique fixture ids per
// run ... so repeated runs against the shared msr repo don't collide").
// Routing is by RDF type, not by name (design D1's "by type, not by
// proposal kind"), so a suffixed "solubility-<ts>" property individual
// exercises exactly the same classifier path as a literal "solubility"
// would, without colliding with any other run's fixture or a real mined
// candidate that might land in the same repo.

import (
	"context"
	"fmt"
	"strconv"
	"testing"
	"time"

	"github.com/blogem/msr-graph/internal/graph"
	"github.com/blogem/msr-graph/internal/proposal"
)

// ontologyHeaderIRI is the owl:Ontology header subject inside
// urn:msr:ontology (ontology/msr.ttl line 16).
const ontologyHeaderIRI = "https://w3id.org/msr-kg/ontology"

// commonPrefixes bundles every PREFIX declaration the fixtures below need;
// harmless to over-include in a query that only uses a subset.
const commonPrefixes = `
	PREFIX msr: <https://w3id.org/msr-kg/ontology#>
	PREFIX msrd: <https://w3id.org/msr-kg/data#>
	PREFIX voc: <https://w3id.org/msr-kg/vocab#>
	PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
	PREFIX owl: <http://www.w3.org/2002/07/owl#>
	PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
	PREFIX prov: <http://www.w3.org/ns/prov#>
	PREFIX qk: <http://qudt.org/vocab/quantitykind/>
	PREFIX unit: <http://qudt.org/vocab/unit/>
	PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
`

// uniqueSuffix returns a per-run-unique numeric suffix so repeated test
// runs against the shared "msr" integration repo never collide on subject
// IRIs.
func uniqueSuffix() string {
	return strconv.FormatInt(time.Now().UnixNano(), 10)
}

// changeProposalIRI is the deterministic msrd:proposal-{id} resource IRI
// (change-proposal-schema/spec.md).
func changeProposalIRI(id string) string {
	return "https://w3id.org/msr-kg/data#proposal-" + id
}

// testApproveRequest returns a fixed, valid ApproveRequest for tests that
// don't need to assert on the reviewer/timestamp values themselves.
func testApproveRequest() proposal.ApproveRequest {
	return proposal.ApproveRequest{
		Reviewer:  "tester@example.com",
		Timestamp: "2026-07-20T12:00:00Z",
	}
}

// seedChangeProposal writes the staging-side msr:ChangeProposal resource
// (kind/status/term/docFrequency/hasProposalGraph/hasEvidence) for id, per
// change-proposal-schema/spec.md's two-graph staging model.
func seedChangeProposal(t *testing.T, client *graph.Client, id, kind, term, status string) {
	t.Helper()
	resource := changeProposalIRI(id)
	proposalGraph := string(graph.ProposalGraph(id))

	update := fmt.Sprintf(commonPrefixes+`
		INSERT DATA {
			GRAPH <urn:msr:staging> {
				<%s> a msr:ChangeProposal ;
					msr:kind "%s" ;
					msr:reviewStatus "%s" ;
					msr:term "%s" ;
					msr:docFrequency 3 ;
					msr:hasProposalGraph "%s"^^xsd:anyURI ;
					msr:hasEvidence [
						a msr:Evidence ;
						msr:evidenceText "a fixture evidence sentence mentioning %s" ;
						msr:citedIn msrd:test-doc-%s ;
						msr:startOffset 0 ;
						msr:endOffset 10
					] .
			}
		}`, resource, kind, status, term, proposalGraph, term, id)

	if err := client.Update(context.Background(), update); err != nil {
		t.Fatalf("seeding msr:ChangeProposal %s: %v", resource, err)
	}
}

// solubilityFixture holds the IRIs a solubility-shaped fixture proposal
// generates (approval-typed-routing spec.md's "A property proposal routes
// to ontology and vocab" scenario).
type solubilityFixture struct {
	ID          string // proposal {id} path segment
	PropertyIRI string // the msr:PhysicalProperty individual
	ConceptIRI  string // the skos:Concept
}

// seedSolubilityProposal seeds a pending "property" proposal bundling one
// msr:PhysicalProperty individual (with quantityKind/canonicalUnit, so it
// classifies to urn:msr:ontology per design D1) and one skos:Concept (so it
// classifies to urn:msr:vocab).
func seedSolubilityProposal(t *testing.T, client *graph.Client) solubilityFixture {
	t.Helper()
	suffix := uniqueSuffix()
	id := "property-solubility-" + suffix
	propertyLocal := "solubility-" + suffix
	conceptLocal := "solubility-" + suffix

	seedChangeProposal(t, client, id, "property", "solubility", "pending")

	proposalGraph := string(graph.ProposalGraph(id))
	update := fmt.Sprintf(commonPrefixes+`
		INSERT DATA {
			GRAPH <%s> {
				msr:%s a msr:PhysicalProperty ;
					msr:quantityKind qk:MassConcentration ;
					msr:canonicalUnit unit:GM-PER-L .
				voc:%s a skos:Concept ;
					skos:prefLabel "solubility"@en .
			}
		}`, proposalGraph, propertyLocal, conceptLocal)
	if err := client.Update(context.Background(), update); err != nil {
		t.Fatalf("seeding solubility proposal graph %s: %v", proposalGraph, err)
	}

	return solubilityFixture{
		ID:          id,
		PropertyIRI: "https://w3id.org/msr-kg/ontology#" + propertyLocal,
		ConceptIRI:  "https://w3id.org/msr-kg/vocab#" + conceptLocal,
	}
}

// graphiteFixture holds the IRIs a graphite-shaped mixed bundle generates
// (approval-typed-routing spec.md's "A mixed class bundle routes each
// triple by type" scenario / change-proposal-schema/spec.md's "A class
// proposal bundles a relation and an individual" scenario).
type graphiteFixture struct {
	ID            string
	ClassIRI      string // msr:Moderator-shaped owl:Class
	PropertyIRI   string // msr:moderatedBy-shaped owl:ObjectProperty
	IndividualIRI string // msrd:graphite-shaped individual typed by ClassIRI
}

// seedGraphiteProposal seeds a pending "class" proposal bundling an
// owl:Class, an owl:ObjectProperty ranging over that class, and an
// individual typed by the class -- a mixed TBox+instance bundle under one
// ChangeProposal, exactly as design.md's Context section describes.
func seedGraphiteProposal(t *testing.T, client *graph.Client) graphiteFixture {
	t.Helper()
	suffix := uniqueSuffix()
	id := "class-graphite-" + suffix
	classLocal := "Moderator-" + suffix
	propLocal := "moderatedBy-" + suffix
	indivLocal := "graphite-" + suffix

	seedChangeProposal(t, client, id, "class", "graphite", "pending")

	proposalGraph := string(graph.ProposalGraph(id))
	update := fmt.Sprintf(commonPrefixes+`
		INSERT DATA {
			GRAPH <%s> {
				msr:%s a owl:Class .
				msr:%s a owl:ObjectProperty ; rdfs:range msr:%s .
				msrd:%s a msr:%s .
			}
		}`, proposalGraph, classLocal, propLocal, classLocal, indivLocal, classLocal)
	if err := client.Update(context.Background(), update); err != nil {
		t.Fatalf("seeding graphite proposal graph %s: %v", proposalGraph, err)
	}

	return graphiteFixture{
		ID:            id,
		ClassIRI:      "https://w3id.org/msr-kg/ontology#" + classLocal,
		PropertyIRI:   "https://w3id.org/msr-kg/ontology#" + propLocal,
		IndividualIRI: "https://w3id.org/msr-kg/data#" + indivLocal,
	}
}

// seedBadMeasurementProposal seeds a pending "instance" proposal whose
// bundle is a bare `a msr:PropertyMeasurement` typing with NONE of the
// seven properties deploy/graphdb/msr-shapes.ttl's
// msr:PropertyMeasurementShape requires (minCount 1 each):
// prov:wasDerivedFrom, prov:wasGeneratedBy, msr:dataLocator,
// msr:forProperty, msr:ofSalt, msr:hasUnit, msr:equationForm. Being an
// individual (not a TBox axiom or SKOS concept), the routing classifier
// sends it to urn:msr:data per design D1, so approving it should trip the
// SHACL sail.
func seedBadMeasurementProposal(t *testing.T, client *graph.Client) (id, measurementIRI string) {
	t.Helper()
	suffix := uniqueSuffix()
	id = "instance-badmeasurement-" + suffix
	local := "badmeasurement-" + suffix

	seedChangeProposal(t, client, id, "instance", "badmeasurement", "pending")

	proposalGraph := string(graph.ProposalGraph(id))
	update := fmt.Sprintf(commonPrefixes+`
		INSERT DATA {
			GRAPH <%s> {
				msrd:%s a msr:PropertyMeasurement .
			}
		}`, proposalGraph, local)
	if err := client.Update(context.Background(), update); err != nil {
		t.Fatalf("seeding SHACL-violating proposal graph %s: %v", proposalGraph, err)
	}
	return id, "https://w3id.org/msr-kg/data#" + local
}

// coreGraphHasSubject reports whether subjectIRI has at least one triple
// inside graph g, read through the core-dataset Select -- proving the
// promoted triple is visible via the same client the analysis agent uses.
// g must be one of graph.CoreGraphs for this to exercise the core-dataset
// restriction meaningfully.
func coreGraphHasSubject(t *testing.T, client *graph.Client, g graph.GraphIRI, subjectIRI string) bool {
	t.Helper()
	query := fmt.Sprintf(`SELECT ?p ?o WHERE { GRAPH <%s> { <%s> ?p ?o } }`, g, subjectIRI)
	results, err := client.Select(context.Background(), query)
	if err != nil {
		t.Fatalf("Select over %s for %s: %v", g, subjectIRI, err)
	}
	return len(results.Results.Bindings) > 0
}

// rawGraphHasSubject is coreGraphHasSubject's SelectRaw counterpart, usable
// against any named graph (including staging/proposal graphs the core
// client cannot see).
func rawGraphHasSubject(t *testing.T, client *graph.Client, g graph.GraphIRI, subjectIRI string) bool {
	t.Helper()
	query := fmt.Sprintf(`SELECT ?p ?o WHERE { GRAPH <%s> { <%s> ?p ?o } }`, g, subjectIRI)
	results, err := client.SelectRaw(context.Background(), query)
	if err != nil {
		t.Fatalf("SelectRaw over %s for %s: %v", g, subjectIRI, err)
	}
	return len(results.Results.Bindings) > 0
}

// countSubjectTriples counts subjectIRI's triples inside graph g via
// SelectRaw (unrestricted), for idempotency / audit-record-retention
// assertions.
func countSubjectTriples(t *testing.T, client *graph.Client, g graph.GraphIRI, subjectIRI string) int {
	t.Helper()
	query := fmt.Sprintf(`SELECT (COUNT(*) AS ?n) WHERE { GRAPH <%s> { <%s> ?p ?o } }`, g, subjectIRI)
	results, err := client.SelectRaw(context.Background(), query)
	if err != nil {
		t.Fatalf("counting %s triples in %s: %v", subjectIRI, g, err)
	}
	if len(results.Results.Bindings) != 1 {
		t.Fatalf("expected exactly one COUNT(*) binding for %s in %s, got %d", subjectIRI, g, len(results.Results.Bindings))
	}
	n, err := strconv.Atoi(results.Results.Bindings[0]["n"].Value)
	if err != nil {
		t.Fatalf("parsing triple count for %s in %s: %v", subjectIRI, g, err)
	}
	return n
}

// reviewStatus reads id's current msr:reviewStatus from urn:msr:staging.
func reviewStatus(t *testing.T, client *graph.Client, id string) string {
	t.Helper()
	resource := changeProposalIRI(id)
	query := fmt.Sprintf(commonPrefixes+`
		SELECT ?status WHERE { GRAPH <urn:msr:staging> { <%s> msr:reviewStatus ?status } }`, resource)
	results, err := client.SelectRaw(context.Background(), query)
	if err != nil {
		t.Fatalf("querying msr:reviewStatus for %s: %v", resource, err)
	}
	if len(results.Results.Bindings) != 1 {
		t.Fatalf("expected exactly one msr:reviewStatus binding for %s, got %d", resource, len(results.Results.Bindings))
	}
	return results.Results.Bindings[0]["status"].Value
}

// setOntologyVersion force-sets urn:msr:ontology's owl:versionInfo to
// version via a scoped DELETE/INSERT, first ensuring the owl:Ontology
// header individual itself exists (INSERT DATA is set-semantics, so this
// is a no-op if `make load-seed` already ran). Per the task brief, tests
// must not depend on load-seed having already set a particular baseline --
// this is the self-contained setup mechanism instead.
func setOntologyVersion(t *testing.T, client *graph.Client, version string) {
	t.Helper()
	ctx := context.Background()

	ensure := fmt.Sprintf(commonPrefixes+`
		INSERT DATA { GRAPH <urn:msr:ontology> { <%s> a owl:Ontology . } }`, ontologyHeaderIRI)
	if err := client.Update(ctx, ensure); err != nil {
		t.Fatalf("ensuring the owl:Ontology header exists: %v", err)
	}

	bump := fmt.Sprintf(commonPrefixes+`
		DELETE { GRAPH <urn:msr:ontology> { <%[1]s> owl:versionInfo ?old } }
		INSERT { GRAPH <urn:msr:ontology> { <%[1]s> owl:versionInfo "%[2]s" } }
		WHERE { OPTIONAL { GRAPH <urn:msr:ontology> { <%[1]s> owl:versionInfo ?old } } }`,
		ontologyHeaderIRI, version)
	if err := client.Update(ctx, bump); err != nil {
		t.Fatalf("setting owl:versionInfo to %q: %v", version, err)
	}
}

// ontologyVersion reads urn:msr:ontology's current owl:versionInfo.
func ontologyVersion(t *testing.T, client *graph.Client) string {
	t.Helper()
	query := fmt.Sprintf(commonPrefixes+`
		SELECT ?v WHERE { GRAPH <urn:msr:ontology> { <%s> owl:versionInfo ?v } }`, ontologyHeaderIRI)
	results, err := client.SelectRaw(context.Background(), query)
	if err != nil {
		t.Fatalf("querying owl:versionInfo: %v", err)
	}
	if len(results.Results.Bindings) != 1 {
		t.Fatalf("expected exactly one owl:versionInfo literal, got %d", len(results.Results.Bindings))
	}
	return results.Results.Bindings[0]["v"].Value
}

// countVersionLiterals counts owl:versionInfo literals on the ontology
// header, for the "exactly one version literal" assertion.
func countVersionLiterals(t *testing.T, client *graph.Client) int {
	t.Helper()
	query := fmt.Sprintf(commonPrefixes+`
		SELECT (COUNT(*) AS ?n) WHERE { GRAPH <urn:msr:ontology> { <%s> owl:versionInfo ?v } }`, ontologyHeaderIRI)
	results, err := client.SelectRaw(context.Background(), query)
	if err != nil {
		t.Fatalf("counting owl:versionInfo literals: %v", err)
	}
	if len(results.Results.Bindings) != 1 {
		t.Fatalf("expected exactly one COUNT(*) binding, got %d", len(results.Results.Bindings))
	}
	n, err := strconv.Atoi(results.Results.Bindings[0]["n"].Value)
	if err != nil {
		t.Fatalf("parsing version-literal count: %v", err)
	}
	return n
}
