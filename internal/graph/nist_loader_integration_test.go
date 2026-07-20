package graph_test

// Integration tests 8.7 and 8.8 for `loader nist`, guarded by the D6
// requireGraphDB helper (testhelper_test.go). These run the loader CLI
// end-to-end -- `go run ./cmd/loader seed` then `go run ./cmd/loader nist`
// -- against a live GraphDB and a fresh temp SQLite database, then assert
// against both stores per
// openspec/changes/load-nist-structured-data/specs/nist-structured-loading/spec.md:
//
//   - FLiBe density coefficients land in SQLite (8.7, scenario "FLiBe
//     density coefficients land in SQLite")
//   - the FLiBe density measurement is queryable via the core client
//     (8.7, scenario "FLiBe density measurement is queryable via the core
//     client")
//   - chlorides are excluded from both stores (fluoride-subset filter)
//   - a second `loader nist` run changes neither store (8.8, scenario
//     "Second run changes nothing") and the anchor salts (FLiBe, FLiNaK)
//     remain present (8.8, scenario "Anchor salts are present")
//
// ground-demo-in-real-docs removed the hand-curated A-Box seed
// (ontology/example-flibe.ttl) along with the msr:hasRole/msr:usedIn/
// msrd:MSRE TBox layer it alone populated, so the former "seed
// hand-curated edges survive the nist load" subtest (and its
// wantRole/wantReactor constants) no longer applies and has been removed.
// The FLiBe measurement/coefficients below come purely from `loader nist`
// (that was already the case -- only the seed-survival expectation is
// gone).
//
// runLoaderSeed, repoRoot, graphDBBaseURL, requireGraphDB, and
// countGraphTriples are reused from seed_integration_test.go /
// testhelper_test.go rather than redefined here.

import (
	"context"
	"database/sql"
	"fmt"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"testing"

	"github.com/blogem/msr-graph/internal/graph"
	"github.com/blogem/msr-graph/internal/store"
)

const (
	// flibeSaltCURIE is the MSRE coolant salt IRI minted by the nist loader
	// for the canonical BeF2-LiF | 34.0-66.0 salt (deterministic IRI keyed
	// by composition, per D6 -- there is no hand-curated seed A-Box
	// anymore, so this is the loader's own minted IRI, not a seed/loader
	// coincidence).
	flibeSaltCURIE = "msrd:salt-BeF2-LiF-34.0-66.0"
	// flibeMeasurementIRI is the full IRI form of the FLiBe density
	// measurement, minted by the nist loader.
	flibeMeasurementIRI = "https://w3id.org/msr-kg/data#m-nist-srd27-density-BeF2-LiF-34.0-66.0"
	// flibeLocator is the contract locator form (tasks.md / spec.md) for
	// the FLiBe density row: nist-srd27/{property}#{canonical-salt}.
	flibeLocator = "nist-srd27/density#BeF2-LiF|34.0-66.0"
	// flinakSaltCURIE is the FLiNaK anchor salt IRI, minted from the
	// KF-LiF-NaF,42.0-46.5-11.5 density row in data/nist/density-csv.txt.
	flinakSaltCURIE = "msrd:salt-KF-LiF-NaF-42.0-46.5-11.5"

	wantFlibeC0 = 2.413
	wantFlibeC1 = -4.88e-4
	floatTol    = 1e-9
)

// runLoader runs `go run ./cmd/loader <subcommand>` from the repo root
// with the given extra environment variables layered onto the current
// process environment, following seed_integration_test.go's runLoaderSeed
// pattern (generalized to any subcommand and env var set, since `nist`
// additionally needs MSR_DB_PATH pointed at a temp SQLite file).
func runLoader(t *testing.T, subcommand string, extraEnv ...string) {
	t.Helper()
	cmd := exec.Command("go", "run", "./cmd/loader", subcommand)
	cmd.Dir = repoRoot(t)
	cmd.Env = append(os.Environ(), extraEnv...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("`go run ./cmd/loader %s` failed: %v\noutput:\n%s", subcommand, err, out)
	}
}

// countMeasurementRows returns the total row count of measurement_value.
func countMeasurementRows(t *testing.T, ctx context.Context, db *sql.DB) int {
	t.Helper()
	var n int
	if err := db.QueryRowContext(ctx, `SELECT COUNT(*) FROM measurement_value`).Scan(&n); err != nil {
		t.Fatalf("counting measurement_value rows: %v", err)
	}
	return n
}

func floatsClose(a, b, tol float64) bool {
	return math.Abs(a-b) <= tol
}

// TestNistLoadIngestsFlibeAndExcludesChlorides pins nist-structured-loading
// spec.md's coefficient-storage and core-client scenarios (task 8.7): after
// `seed` then `nist`, the FLiBe density coefficients live in SQLite, the
// FLiBe density measurement is queryable through the core client, and no
// chloride salt/row is present in either store. (The former "seed
// hand-curated edges survive the load" expectation is gone -- see the file
// header comment -- ground-demo-in-real-docs removed the seed A-Box and
// its hasRole/usedIn/MSRE TBox layer entirely.)
func TestNistLoadIngestsFlibeAndExcludesChlorides(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()
	baseURL := graphDBBaseURL()

	dbPath := filepath.Join(t.TempDir(), "measurements.db")
	env := []string{"GRAPHDB_URL=" + baseURL, "MSR_DB_PATH=" + dbPath}

	runLoader(t, "seed", env...)
	runLoader(t, "nist", env...)

	db, err := store.Open(dbPath)
	if err != nil {
		t.Fatalf("store.Open(%s): %v", dbPath, err)
	}
	defer db.Close()

	t.Run("FLiBe density coefficients land in SQLite", func(t *testing.T) {
		var count int
		if err := db.QueryRowContext(ctx,
			`SELECT COUNT(*) FROM measurement_value WHERE locator = ?`, flibeLocator,
		).Scan(&count); err != nil {
			t.Fatalf("counting measurement_value rows for locator %q: %v", flibeLocator, err)
		}
		if count != 1 {
			t.Fatalf("expected exactly one measurement_value row for locator %q, got %d", flibeLocator, count)
		}

		var sourceCol string
		var c0, c1 sql.NullFloat64
		row := db.QueryRowContext(ctx,
			`SELECT source, c0, c1 FROM measurement_value WHERE locator = ?`, flibeLocator)
		if err := row.Scan(&sourceCol, &c0, &c1); err != nil {
			t.Fatalf("scanning measurement_value row for locator %q: %v", flibeLocator, err)
		}
		if sourceCol != "nist" {
			t.Errorf("source = %q, want %q", sourceCol, "nist")
		}
		if !c0.Valid || !floatsClose(c0.Float64, wantFlibeC0, floatTol) {
			t.Errorf("c0 = %v, want ~%v", c0, wantFlibeC0)
		}
		if !c1.Valid || !floatsClose(c1.Float64, wantFlibeC1, floatTol) {
			t.Errorf("c1 = %v, want ~%v", c1, wantFlibeC1)
		}
	})

	t.Run("FLiBe density measurement queryable via core client", func(t *testing.T) {
		query := fmt.Sprintf(`
			PREFIX msr: <https://w3id.org/msr-kg/ontology#>
			SELECT ?unit ?form ?tmin ?tmax ?locator WHERE {
				<%s> a msr:PropertyMeasurement ;
					msr:forProperty msr:density ;
					msr:hasUnit ?unit ;
					msr:equationForm ?form ;
					msr:validTempMin ?tmin ;
					msr:validTempMax ?tmax ;
					msr:dataLocator ?locator .
			}
		`, flibeMeasurementIRI)

		results, err := client.Select(ctx, query)
		if err != nil {
			t.Fatalf("Select: %v", err)
		}
		if len(results.Results.Bindings) != 1 {
			t.Fatalf("expected exactly one PropertyMeasurement binding for the FLiBe density measurement, got %d", len(results.Results.Bindings))
		}
		if got := results.Results.Bindings[0]["locator"].Value; got != flibeLocator {
			t.Errorf("dataLocator = %q, want %q (must equal the SQLite row's locator for the federation join to resolve)", got, flibeLocator)
		}
	})

	t.Run("no chloride rows in SQLite", func(t *testing.T) {
		var count int
		if err := db.QueryRowContext(ctx,
			`SELECT COUNT(*) FROM measurement_value WHERE salt LIKE '%Cl%'`,
		).Scan(&count); err != nil {
			t.Fatalf("counting chloride measurement_value rows: %v", err)
		}
		if count != 0 {
			t.Errorf("expected zero chloride rows in measurement_value (fluoride-subset filter), got %d", count)
		}
	})

	t.Run("no chloride salts in the core graph", func(t *testing.T) {
		query := `
			PREFIX msr: <https://w3id.org/msr-kg/ontology#>
			PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
			SELECT ?salt WHERE {
				?salt a msr:MoltenSalt ; rdfs:label ?label .
				FILTER(CONTAINS(?label, "Cl"))
			}
		`
		results, err := client.Select(ctx, query)
		if err != nil {
			t.Fatalf("Select: %v", err)
		}
		if len(results.Results.Bindings) != 0 {
			t.Errorf("expected zero msr:MoltenSalt individuals with a chloride-containing label, got %d", len(results.Results.Bindings))
		}
	})
}

// TestNistLoadIdempotentAcrossBothStores pins nist-structured-loading
// spec.md's "Second run changes nothing" and "Anchor salts are present"
// scenarios (task 8.8): running `loader nist` a second time against the
// same GraphDB repo and SQLite file leaves the urn:msr:data triple count
// and the measurement_value row count unchanged, and the FLiBe and FLiNaK
// anchor salts remain present in urn:msr:data.
func TestNistLoadIdempotentAcrossBothStores(t *testing.T) {
	client := requireGraphDB(t)
	ctx := context.Background()
	baseURL := graphDBBaseURL()

	dbPath := filepath.Join(t.TempDir(), "measurements.db")
	env := []string{"GRAPHDB_URL=" + baseURL, "MSR_DB_PATH=" + dbPath}

	runLoader(t, "seed", env...)
	runLoader(t, "nist", env...)

	db, err := store.Open(dbPath)
	if err != nil {
		t.Fatalf("store.Open(%s): %v", dbPath, err)
	}
	defer db.Close()

	tripleCountAfterFirstRun := countGraphTriples(t, client, graph.Data)
	rowCountAfterFirstRun := countMeasurementRows(t, ctx, db)

	runLoader(t, "nist", env...)

	if got := countGraphTriples(t, client, graph.Data); got != tripleCountAfterFirstRun {
		t.Errorf("urn:msr:data triple count changed across a repeat nist load: %d -> %d", tripleCountAfterFirstRun, got)
	}
	if got := countMeasurementRows(t, ctx, db); got != rowCountAfterFirstRun {
		t.Errorf("measurement_value row count changed across a repeat nist load: %d -> %d", rowCountAfterFirstRun, got)
	}

	// provenance-run-lineage task 5.8: the stable msrd:activity-loader-nist
	// typing added to urn:msr:data by buildInsertData (design D1) is
	// deterministic and timestamp-free, so it must not perturb the
	// "urn:msr:data triple count is unchanged across a repeat run" guarantee
	// this test already exercises above. Re-assert that explicitly: exactly
	// one typed msrd:activity-loader-nist individual exists in urn:msr:data
	// (never a second copy from the second run), and it carries no
	// timestamp facet -- if the stable-activity typing were accidentally
	// timestamped, it would itself break the triple-count invariant just
	// checked.
	t.Run("stable activity typing does not perturb urn:msr:data idempotency", func(t *testing.T) {
		query := `
			PREFIX msrd: <https://w3id.org/msr-kg/data#>
			PREFIX prov: <http://www.w3.org/ns/prov#>
			SELECT ?p ?o WHERE {
				msrd:activity-loader-nist a prov:Activity ; ?p ?o .
			}
		`
		results, err := client.Select(ctx, query)
		if err != nil {
			t.Fatalf("Select for msrd:activity-loader-nist: %v", err)
		}
		if len(results.Results.Bindings) == 0 {
			t.Fatal("expected msrd:activity-loader-nist to carry at least one attribute triple in urn:msr:data, got none")
		}
		for _, b := range results.Results.Bindings {
			p := b["p"].Value
			if p == "http://www.w3.org/ns/prov#startedAtTime" || p == "http://www.w3.org/ns/prov#endedAtTime" {
				t.Errorf("msrd:activity-loader-nist unexpectedly carries timestamp predicate %s -- this would break urn:msr:data idempotency across repeat runs", p)
			}
		}

		// COUNT(?activity) with a bound variable, not COUNT(*) over a fully
		// ground (zero-variable) BGP: this GraphDB deployment's SPARQL
		// engine returns 0 for COUNT(*) when the WHERE clause has no
		// variables at all, even when the ground triple pattern matches
		// (confirmed independently via ASK, which correctly returns true) --
		// so COUNT(*) here would be a false negative, not a real assertion.
		countQuery := `
			PREFIX msrd: <https://w3id.org/msr-kg/data#>
			PREFIX prov: <http://www.w3.org/ns/prov#>
			SELECT (COUNT(?activity) AS ?count) WHERE {
				?activity a prov:Activity .
				FILTER(?activity = msrd:activity-loader-nist)
			}
		`
		results, err = client.Select(ctx, countQuery)
		if err != nil {
			t.Fatalf("Select counting msrd:activity-loader-nist typing: %v", err)
		}
		if len(results.Results.Bindings) != 1 {
			t.Fatalf("expected exactly one COUNT(?activity) binding, got %d", len(results.Results.Bindings))
		}
		if got := results.Results.Bindings[0]["count"].Value; got != "1" {
			t.Errorf("expected exactly one `a prov:Activity` typing triple for msrd:activity-loader-nist in urn:msr:data after a repeat run, got count=%s", got)
		}
	})

	for _, anchor := range []struct {
		name  string
		curie string
	}{
		{"FLiBe (MSRE coolant salt)", flibeSaltCURIE},
		{"FLiNaK", flinakSaltCURIE},
	} {
		query := fmt.Sprintf(`
			PREFIX msr: <https://w3id.org/msr-kg/ontology#>
			PREFIX msrd: <https://w3id.org/msr-kg/data#>
			SELECT ?salt WHERE {
				BIND(%s AS ?salt)
				%s a msr:MoltenSalt .
			}
		`, anchor.curie, anchor.curie)

		results, err := client.Select(ctx, query)
		if err != nil {
			t.Fatalf("Select for anchor salt %s (%s): %v", anchor.name, anchor.curie, err)
		}
		if len(results.Results.Bindings) != 1 {
			t.Errorf("expected anchor salt %s (%s) to be present as a msr:MoltenSalt in urn:msr:data, got %d bindings", anchor.name, anchor.curie, len(results.Results.Bindings))
		}
	}
}
