package store_test

// Unit tests for internal/store (task 6.3). Real temp-file SQLite, no
// external service -- these run unconditionally. Schema grounded in
// openspec/changes/bootstrap-graph-infra/specs/measurement-store/spec.md:
//
//	CREATE TABLE measurement_value (
//	  locator TEXT PRIMARY KEY, salt TEXT, property TEXT,
//	  c0 REAL, c1 REAL, c2 REAL, c3 REAL, c4 REAL,
//	  t_min REAL, t_max REAL, equation_form TEXT, uncertainty TEXT,
//	  source TEXT NOT NULL CHECK (source IN ('nist','document')), doc_id TEXT
//	);

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/blogem/msr-graph/internal/store"
)

// TestInit_Idempotent pins measurement-store spec.md's "Re-running init is a
// no-op" scenario: running Init twice against the same file preserves rows
// inserted between the two calls.
func TestInit_Idempotent(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "measurements.db")

	db, err := store.Open(path)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer db.Close()

	ctx := context.Background()
	if err := store.Init(ctx, db); err != nil {
		t.Fatalf("first Init: %v", err)
	}

	const locator = "nist-srd27/density#BeF2-LiF|66.0-34.0"
	const insertSQL = `INSERT INTO measurement_value
		(locator, salt, property, c0, c1, t_min, t_max, equation_form, source)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`
	if _, err := db.ExecContext(ctx, insertSQL,
		locator, "BeF2-LiF|66.0-34.0", "density",
		2.413, -4.88e-4, 800.0, 1080.0, "Linear", "nist",
	); err != nil {
		t.Fatalf("seeding a row before the second Init: %v", err)
	}

	if err := store.Init(ctx, db); err != nil {
		t.Fatalf("second Init (idempotency): %v", err)
	}

	var count int
	if err := db.QueryRowContext(ctx,
		`SELECT COUNT(*) FROM measurement_value WHERE locator = ?`, locator,
	).Scan(&count); err != nil {
		t.Fatalf("counting preserved rows: %v", err)
	}
	if count != 1 {
		t.Fatalf("expected the pre-inserted row to survive a second Init, got count=%d", count)
	}
}

// TestInit_CreatesContractSchema pins measurement-store spec.md's "The DDL
// MUST match the contract schema exactly" requirement by checking column
// name, declared type, NOT NULL, and PRIMARY KEY for every column via
// PRAGMA table_info.
func TestInit_CreatesContractSchema(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "schema.db")

	db, err := store.Open(path)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer db.Close()

	ctx := context.Background()
	if err := store.Init(ctx, db); err != nil {
		t.Fatalf("Init: %v", err)
	}

	rows, err := db.QueryContext(ctx, `PRAGMA table_info(measurement_value)`)
	if err != nil {
		t.Fatalf("PRAGMA table_info: %v", err)
	}
	defer rows.Close()

	type column struct {
		name    string
		colType string
		notNull bool
		pk      bool
	}
	var got []column
	for rows.Next() {
		var (
			cid       int
			name      string
			colType   string
			notNull   int
			dfltValue any
			pk        int
		)
		if err := rows.Scan(&cid, &name, &colType, &notNull, &dfltValue, &pk); err != nil {
			t.Fatalf("scanning table_info row: %v", err)
		}
		got = append(got, column{name: name, colType: strings.ToUpper(colType), notNull: notNull != 0, pk: pk != 0})
	}
	if err := rows.Err(); err != nil {
		t.Fatalf("iterating table_info rows: %v", err)
	}

	want := []column{
		{"locator", "TEXT", false, true},
		{"salt", "TEXT", false, false},
		{"property", "TEXT", false, false},
		{"c0", "REAL", false, false},
		{"c1", "REAL", false, false},
		{"c2", "REAL", false, false},
		{"c3", "REAL", false, false},
		{"c4", "REAL", false, false},
		{"t_min", "REAL", false, false},
		{"t_max", "REAL", false, false},
		{"equation_form", "TEXT", false, false},
		{"uncertainty", "TEXT", false, false},
		{"source", "TEXT", true, false},
		{"doc_id", "TEXT", false, false},
	}

	if len(got) != len(want) {
		t.Fatalf("measurement_value has %d columns, want %d\ngot:  %+v\nwant: %+v", len(got), len(want), got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("column %d: got %+v, want %+v", i, got[i], want[i])
		}
	}
}

// TestMeasurementValue_SourceCheckConstraint pins the CHECK (source IN
// ('nist','document')) clause of the contract schema: table_info cannot see
// CHECK constraints, so this exercises the constraint behaviorally.
func TestMeasurementValue_SourceCheckConstraint(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "check.db")

	db, err := store.Open(path)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer db.Close()

	ctx := context.Background()
	if err := store.Init(ctx, db); err != nil {
		t.Fatalf("Init: %v", err)
	}

	tests := []struct {
		name    string
		source  string
		wantErr bool
	}{
		{"nist is allowed", "nist", false},
		{"document is allowed", "document", false},
		{"anything else is rejected", "spreadsheet", true},
	}

	for i, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			locator := fmt.Sprintf("test/check#%d", i)
			_, err := db.ExecContext(ctx,
				`INSERT INTO measurement_value (locator, source) VALUES (?, ?)`,
				locator, tc.source)
			if tc.wantErr && err == nil {
				t.Fatalf("expected an error inserting source=%q, got nil", tc.source)
			}
			if !tc.wantErr && err != nil {
				t.Fatalf("unexpected error inserting source=%q: %v", tc.source, err)
			}
		})
	}
}

// TestOpen_PinsJournalModeAndBusyTimeout pins measurement-store spec.md's
// "Journal mode pinned" scenario: every connection opened through the store
// helper reports journal_mode=delete and a non-zero busy_timeout.
func TestOpen_PinsJournalModeAndBusyTimeout(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "pragma.db")

	db, err := store.Open(path)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer db.Close()

	// Disable idle-connection reuse so each PRAGMA check below is likely to
	// exercise a distinct driver-level connection, approximating the
	// "on every connection" part of the contract rather than just the
	// first one ever opened.
	db.SetMaxIdleConns(0)

	for i := 0; i < 3; i++ {
		t.Run(fmt.Sprintf("connection %d", i), func(t *testing.T) {
			var journalMode string
			if err := db.QueryRow("PRAGMA journal_mode").Scan(&journalMode); err != nil {
				t.Fatalf("PRAGMA journal_mode: %v", err)
			}
			if strings.ToLower(journalMode) != "delete" {
				t.Errorf("journal_mode = %q, want %q", journalMode, "delete")
			}

			var busyTimeout int
			if err := db.QueryRow("PRAGMA busy_timeout").Scan(&busyTimeout); err != nil {
				t.Fatalf("PRAGMA busy_timeout: %v", err)
			}
			if busyTimeout <= 0 {
				t.Errorf("busy_timeout = %d, want a non-zero value", busyTimeout)
			}
		})
	}
}

// TestOpen_NoWALSidecarFilesAfterWrite pins measurement-store spec.md's "No
// WAL sidecar files" scenario: after init + a write through the store
// helper, no -wal/-shm sidecar files exist next to the database file.
func TestOpen_NoWALSidecarFilesAfterWrite(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "nowal.db")

	db, err := store.Open(path)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	defer db.Close()

	ctx := context.Background()
	if err := store.Init(ctx, db); err != nil {
		t.Fatalf("Init: %v", err)
	}

	if _, err := db.ExecContext(ctx,
		`INSERT INTO measurement_value (locator, salt, property, source) VALUES (?, ?, ?, ?)`,
		"nist-srd27/viscosity#BeF2-LiF|66.0-34.0", "BeF2-LiF|66.0-34.0", "viscosity", "nist",
	); err != nil {
		t.Fatalf("writing a row: %v", err)
	}

	for _, suffix := range []string{"-wal", "-shm"} {
		t.Run(suffix, func(t *testing.T) {
			sidecar := path + suffix
			if _, statErr := os.Stat(sidecar); statErr == nil {
				t.Errorf("found unexpected sidecar file %s after a write with journal_mode=DELETE", sidecar)
			} else if !os.IsNotExist(statErr) {
				t.Errorf("stat %s: %v", sidecar, statErr)
			}
		})
	}
}
