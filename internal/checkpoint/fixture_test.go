package checkpoint_test

// Shared fixtures and query helpers for the internal/checkpoint integration
// tests (task 4.4). seedSolubilityFixtureForRoundTrip mirrors
// internal/proposal's solubility fixture (see
// internal/proposal/fixture_test.go for the identical shape and rationale)
// rather than importing it, since it is an unexported test-only helper in
// another package.

import (
	"context"
	"database/sql"
	"fmt"
	"path/filepath"
	"strconv"
	"testing"
	"time"

	"github.com/blogem/msr-graph/internal/graph"
	"github.com/blogem/msr-graph/internal/store"
)

// ontologyHeaderIRI is the owl:Ontology header subject inside
// urn:msr:ontology (ontology/msr.ttl line 16).
const ontologyHeaderIRI = "https://w3id.org/msr-kg/ontology"

// uniqueSuffix returns a per-run-unique numeric suffix so repeated test
// runs against the shared "msr" integration repo, and repeated runs writing
// under the same checkpoints root, never collide.
func uniqueSuffix() string {
	return strconv.FormatInt(time.Now().UnixNano(), 10)
}

// newTestSQLiteDB creates a minimal, valid measurement_value SQLite
// database at a temp path -- the dbPath checkpoint.NewEngine snapshots via
// VACUUM INTO (design D4) -- seeded with one row, and returns the path plus
// the row's locator so a caller can read/mutate/re-read it across a
// checkpoint/restore cycle.
func newTestSQLiteDB(t *testing.T) (dbPath, locator string) {
	t.Helper()
	dir := t.TempDir()
	dbPath = filepath.Join(dir, "msr.db")
	locator = "test-locator-" + uniqueSuffix()

	db, err := store.Open(dbPath)
	if err != nil {
		t.Fatalf("store.Open(%s): %v", dbPath, err)
	}
	defer db.Close()

	if err := store.Init(context.Background(), db); err != nil {
		t.Fatalf("store.Init: %v", err)
	}

	row := store.MeasurementRow{
		Locator: locator,
		Salt:    sql.NullString{String: "test-salt", Valid: true},
		C0:      sql.NullFloat64{Float64: 1.5, Valid: true},
		Source:  "document",
	}
	if err := store.Upsert(context.Background(), db, []store.MeasurementRow{row}); err != nil {
		t.Fatalf("seeding a measurement_value row: %v", err)
	}

	return dbPath, locator
}

// mutateMeasurementC0 upserts locator's c0 to a new value, in place, on the
// live SQLite file at dbPath -- used to prove Restore reverts the live
// measurement store's content to the checkpointed snapshot.
func mutateMeasurementC0(t *testing.T, dbPath, locator string, c0 float64) {
	t.Helper()
	db, err := store.Open(dbPath)
	if err != nil {
		t.Fatalf("store.Open(%s): %v", dbPath, err)
	}
	defer db.Close()

	row := store.MeasurementRow{
		Locator: locator,
		Salt:    sql.NullString{String: "test-salt", Valid: true},
		C0:      sql.NullFloat64{Float64: c0, Valid: true},
		Source:  "document",
	}
	if err := store.Upsert(context.Background(), db, []store.MeasurementRow{row}); err != nil {
		t.Fatalf("mutating measurement_value row %s in %s: %v", locator, dbPath, err)
	}
}

// readMeasurementC0 reads locator's current c0 from the SQLite file at
// dbPath.
func readMeasurementC0(t *testing.T, dbPath, locator string) float64 {
	t.Helper()
	db, err := store.Open(dbPath)
	if err != nil {
		t.Fatalf("store.Open(%s): %v", dbPath, err)
	}
	defer db.Close()

	var c0 sql.NullFloat64
	err = db.QueryRowContext(context.Background(),
		`SELECT c0 FROM measurement_value WHERE locator = ?`, locator,
	).Scan(&c0)
	if err != nil {
		t.Fatalf("reading c0 for locator %s from %s: %v", locator, dbPath, err)
	}
	if !c0.Valid {
		t.Fatalf("c0 for locator %s in %s is NULL, want a value", locator, dbPath)
	}
	return c0.Float64
}

// seedSolubilityFixtureForRoundTrip seeds a pending "property"
// msr:ChangeProposal (change-proposal-schema/spec.md's two-graph staging
// model) bundling a msr:PhysicalProperty individual and a skos:Concept in
// its urn:msr:proposal/{id} graph -- the same shape as
// approval-typed-routing spec.md's headline "solubility" scenario.
func seedSolubilityFixtureForRoundTrip(t *testing.T, client *graph.Client) (id, propertyIRI, conceptIRI string) {
	t.Helper()
	ctx := context.Background()
	suffix := uniqueSuffix()
	id = "property-solubility-cp-" + suffix
	propertyIRI = "https://w3id.org/msr-kg/ontology#solubility-" + suffix
	conceptIRI = "https://w3id.org/msr-kg/vocab#solubility-" + suffix
	proposalGraph := string(graph.ProposalGraph(id))
	resource := "https://w3id.org/msr-kg/data#proposal-" + id

	seed := fmt.Sprintf(`
		PREFIX msr: <https://w3id.org/msr-kg/ontology#>
		PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
		INSERT DATA {
			GRAPH <urn:msr:staging> {
				<%s> a msr:ChangeProposal ;
					msr:kind "property" ;
					msr:reviewStatus "pending" ;
					msr:term "solubility" ;
					msr:docFrequency 3 ;
					msr:hasProposalGraph "%s"^^xsd:anyURI .
			}
		}`, resource, proposalGraph)
	if err := client.Update(ctx, seed); err != nil {
		t.Fatalf("seeding msr:ChangeProposal %s: %v", resource, err)
	}

	bundle := fmt.Sprintf(`
		PREFIX msr: <https://w3id.org/msr-kg/ontology#>
		PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
		PREFIX qk: <http://qudt.org/vocab/quantitykind/>
		PREFIX unit: <http://qudt.org/vocab/unit/>
		INSERT DATA {
			GRAPH <%s> {
				<%s> a msr:PhysicalProperty ; msr:quantityKind qk:MassConcentration ; msr:canonicalUnit unit:GM-PER-L .
				<%s> a skos:Concept ; skos:prefLabel "solubility"@en .
			}
		}`, proposalGraph, propertyIRI, conceptIRI)
	if err := client.Update(ctx, bundle); err != nil {
		t.Fatalf("seeding proposal graph %s: %v", proposalGraph, err)
	}

	return id, propertyIRI, conceptIRI
}

// countGraphTriples returns g's total triple count via SelectRaw.
func countGraphTriples(t *testing.T, client *graph.Client, g graph.GraphIRI) int {
	t.Helper()
	query := fmt.Sprintf(`SELECT (COUNT(*) AS ?n) WHERE { GRAPH <%s> { ?s ?p ?o } }`, g)
	results, err := client.SelectRaw(context.Background(), query)
	if err != nil {
		t.Fatalf("counting triples in %s: %v", g, err)
	}
	if len(results.Results.Bindings) != 1 {
		t.Fatalf("expected exactly one COUNT(*) binding for %s, got %d", g, len(results.Results.Bindings))
	}
	n, err := strconv.Atoi(results.Results.Bindings[0]["n"].Value)
	if err != nil {
		t.Fatalf("parsing triple count for %s: %v", g, err)
	}
	return n
}

// hasSubject reports whether subjectIRI has at least one triple inside
// graph g, via SelectRaw.
func hasSubject(t *testing.T, client *graph.Client, g graph.GraphIRI, subjectIRI string) bool {
	t.Helper()
	query := fmt.Sprintf(`SELECT ?p WHERE { GRAPH <%s> { <%s> ?p ?o } }`, g, subjectIRI)
	results, err := client.SelectRaw(context.Background(), query)
	if err != nil {
		t.Fatalf("SelectRaw over %s for %s: %v", g, subjectIRI, err)
	}
	return len(results.Results.Bindings) > 0
}

// reviewStatus reads id's current msr:reviewStatus from urn:msr:staging.
func reviewStatus(t *testing.T, client *graph.Client, id string) string {
	t.Helper()
	resource := "https://w3id.org/msr-kg/data#proposal-" + id
	query := fmt.Sprintf(`
		PREFIX msr: <https://w3id.org/msr-kg/ontology#>
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

// ontologyVersion reads urn:msr:ontology's current owl:versionInfo.
func ontologyVersion(t *testing.T, client *graph.Client) string {
	t.Helper()
	query := fmt.Sprintf(`
		PREFIX owl: <http://www.w3.org/2002/07/owl#>
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
