package store_test

// Unit tests for the idempotent measurement_value upsert path (task 8.6).
// Grounded in openspec/changes/load-nist-structured-data/specs/measurement-store/spec.md
// "Idempotent upsert by locator": insert, re-upsert no-op on count/values,
// update-in-place on a changed coefficient, and a multi-row batch. Real
// temp-file SQLite via store.Open/store.Init, no external service -- these
// run unconditionally.
//
// Written against the agreed API (not yet present in this worktree):
//
//	type MeasurementRow struct {
//	    Locator                          string
//	    Salt, Property                   sql.NullString
//	    C0, C1, C2, C3, C4, TMin, TMax   sql.NullFloat64
//	    EquationForm, Uncertainty        sql.NullString
//	    Source                           string
//	    DocID                            sql.NullString
//	}
//	func Upsert(ctx context.Context, db *sql.DB, rows []MeasurementRow) error

import (
	"context"
	"database/sql"
	"path/filepath"
	"testing"

	"github.com/blogem/msr-graph/internal/store"
)

// flibeDensityRow is the corrected real FLiBe density row from
// data/nist/density-csv.txt (BeF2-LiF, 34.0-66.0 mol%, form P1 -> Linear),
// used as a realistic fixture across the scenarios below.
func flibeDensityRow() store.MeasurementRow {
	return store.MeasurementRow{
		Locator:      "nist-srd27/density#BeF2-LiF|34.0-66.0",
		Salt:         sql.NullString{String: "BeF2-LiF|34.0-66.0", Valid: true},
		Property:     sql.NullString{String: "density", Valid: true},
		C0:           sql.NullFloat64{Float64: 2.413, Valid: true},
		C1:           sql.NullFloat64{Float64: -4.88e-4, Valid: true},
		TMin:         sql.NullFloat64{Float64: 800.0, Valid: true},
		TMax:         sql.NullFloat64{Float64: 1080.0, Valid: true},
		EquationForm: sql.NullString{String: "Linear", Valid: true},
		Source:       "nist",
	}
}

func openTestStore(t *testing.T) *sql.DB {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "measurements.db")

	db, err := store.Open(path)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	t.Cleanup(func() { db.Close() })

	if err := store.Init(context.Background(), db); err != nil {
		t.Fatalf("Init: %v", err)
	}
	return db
}

func countRows(t *testing.T, ctx context.Context, db *sql.DB) int {
	t.Helper()
	var count int
	if err := db.QueryRowContext(ctx, `SELECT COUNT(*) FROM measurement_value`).Scan(&count); err != nil {
		t.Fatalf("counting rows: %v", err)
	}
	return count
}

func readRow(t *testing.T, ctx context.Context, db *sql.DB, locator string) store.MeasurementRow {
	t.Helper()
	var row store.MeasurementRow
	row.Locator = locator
	err := db.QueryRowContext(ctx,
		`SELECT salt, property, c0, c1, c2, c3, c4, t_min, t_max, equation_form, uncertainty, source, doc_id
		 FROM measurement_value WHERE locator = ?`, locator,
	).Scan(
		&row.Salt, &row.Property,
		&row.C0, &row.C1, &row.C2, &row.C3, &row.C4,
		&row.TMin, &row.TMax,
		&row.EquationForm, &row.Uncertainty, &row.Source, &row.DocID,
	)
	if err != nil {
		t.Fatalf("reading row %q: %v", locator, err)
	}
	return row
}

// TestUpsert_InsertsNewLocator pins the "First write inserts the row"
// scenario: a new locator yields exactly one row with the written values.
func TestUpsert_InsertsNewLocator(t *testing.T) {
	db := openTestStore(t)
	ctx := context.Background()
	row := flibeDensityRow()

	if err := store.Upsert(ctx, db, []store.MeasurementRow{row}); err != nil {
		t.Fatalf("Upsert: %v", err)
	}

	if got := countRows(t, ctx, db); got != 1 {
		t.Fatalf("row count = %d, want 1", got)
	}

	got := readRow(t, ctx, db, row.Locator)
	if got.Salt != row.Salt {
		t.Errorf("Salt = %+v, want %+v", got.Salt, row.Salt)
	}
	if got.Property != row.Property {
		t.Errorf("Property = %+v, want %+v", got.Property, row.Property)
	}
	if got.C0 != row.C0 {
		t.Errorf("C0 = %+v, want %+v", got.C0, row.C0)
	}
	if got.C1 != row.C1 {
		t.Errorf("C1 = %+v, want %+v", got.C1, row.C1)
	}
	if got.Source != row.Source {
		t.Errorf("Source = %q, want %q", got.Source, row.Source)
	}
}

// TestUpsert_ReUpsertIdenticalValuesIsNoOp pins the "Re-upserting the same
// locator is a no-op on count" scenario.
func TestUpsert_ReUpsertIdenticalValuesIsNoOp(t *testing.T) {
	db := openTestStore(t)
	ctx := context.Background()
	row := flibeDensityRow()

	if err := store.Upsert(ctx, db, []store.MeasurementRow{row}); err != nil {
		t.Fatalf("first Upsert: %v", err)
	}
	if err := store.Upsert(ctx, db, []store.MeasurementRow{row}); err != nil {
		t.Fatalf("second (identical) Upsert: %v", err)
	}

	if got := countRows(t, ctx, db); got != 1 {
		t.Fatalf("row count after re-upserting identical values = %d, want 1", got)
	}

	got := readRow(t, ctx, db, row.Locator)
	if got.C0 != row.C0 || got.C1 != row.C1 {
		t.Errorf("values changed after a no-op re-upsert: got C0=%+v C1=%+v, want C0=%+v C1=%+v",
			got.C0, got.C1, row.C0, row.C1)
	}
}

// TestUpsert_ReUpsertChangedValueUpdatesInPlace pins the "Re-upserting
// updates changed columns" scenario: a changed C0 updates the existing row
// without creating a duplicate.
func TestUpsert_ReUpsertChangedValueUpdatesInPlace(t *testing.T) {
	db := openTestStore(t)
	ctx := context.Background()
	row := flibeDensityRow()

	if err := store.Upsert(ctx, db, []store.MeasurementRow{row}); err != nil {
		t.Fatalf("first Upsert: %v", err)
	}

	updated := row
	updated.C0 = sql.NullFloat64{Float64: 2.999, Valid: true}
	if err := store.Upsert(ctx, db, []store.MeasurementRow{updated}); err != nil {
		t.Fatalf("second (changed) Upsert: %v", err)
	}

	if got := countRows(t, ctx, db); got != 1 {
		t.Fatalf("row count after updating a changed value = %d, want 1 (no duplicate)", got)
	}

	got := readRow(t, ctx, db, row.Locator)
	if got.C0 != updated.C0 {
		t.Errorf("C0 = %+v, want the updated value %+v", got.C0, updated.C0)
	}
}

// TestUpsert_BatchOfDistinctLocators pins a multi-row batch write: 3
// distinct locators upserted together yield 3 rows.
func TestUpsert_BatchOfDistinctLocators(t *testing.T) {
	db := openTestStore(t)
	ctx := context.Background()

	base := flibeDensityRow()
	second := base
	second.Locator = "nist-srd27/viscosity#BeF2-LiF|34.0-66.0"
	second.Property = sql.NullString{String: "viscosity", Valid: true}
	third := base
	third.Locator = "nist-srd27/density#KF-LiF-NaF|42.0-46.5-11.5"
	third.Salt = sql.NullString{String: "KF-LiF-NaF|42.0-46.5-11.5", Valid: true}

	rows := []store.MeasurementRow{base, second, third}
	if err := store.Upsert(ctx, db, rows); err != nil {
		t.Fatalf("Upsert batch: %v", err)
	}

	if got := countRows(t, ctx, db); got != 3 {
		t.Fatalf("row count after a 3-row batch = %d, want 3", got)
	}
	for _, r := range rows {
		_ = readRow(t, ctx, db, r.Locator) // fails the test via t.Fatalf if the locator is missing
	}
}
