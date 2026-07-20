package main

import (
	"database/sql"
	"path/filepath"
	"testing"

	_ "modernc.org/sqlite"
)

// TestReadOnlyMeasurementStoreDSNAllowsReadsBlocksWrites pins the
// defense-in-depth compensating control on the measurement store
// connection: even though the SELECT-only guard in internal/agent's
// sql_query tool is meant to reject every non-SELECT statement before it
// reaches this connection, the connection itself must independently allow
// reads and reject writes -- both to the named database file and (via
// query_only) to any database an ATTACH statement might open.
func TestReadOnlyMeasurementStoreDSNAllowsReadsBlocksWrites(t *testing.T) {
	dbPath := filepath.Join(t.TempDir(), "msr.db")

	// Seed the database using a normal read-write connection, as
	// production tooling (migrations, the loader) would.
	rw, err := sql.Open("sqlite", dbPath)
	if err != nil {
		t.Fatalf("open read-write seed connection: %v", err)
	}
	if _, err := rw.Exec("CREATE TABLE measurement_value (c0 INTEGER)"); err != nil {
		t.Fatalf("seed CREATE TABLE: %v", err)
	}
	if _, err := rw.Exec("INSERT INTO measurement_value (c0) VALUES (42)"); err != nil {
		t.Fatalf("seed INSERT: %v", err)
	}
	if err := rw.Close(); err != nil {
		t.Fatalf("close seed connection: %v", err)
	}

	db, err := sql.Open("sqlite", readOnlyMeasurementStoreDSN(dbPath))
	if err != nil {
		t.Fatalf("open production read-only DSN: %v", err)
	}
	defer db.Close()

	var got int
	if err := db.QueryRow("SELECT c0 FROM measurement_value").Scan(&got); err != nil {
		t.Fatalf("SELECT over the read-only DSN should succeed, got error: %v", err)
	}
	if got != 42 {
		t.Fatalf("SELECT c0 = %d, want 42", got)
	}

	if _, err := db.Exec("CREATE TABLE t2 (a INTEGER)"); err == nil {
		t.Fatal("CREATE TABLE over the read-only DSN should be rejected, got nil error")
	}

	if _, err := db.Exec("INSERT INTO measurement_value (c0) VALUES (7)"); err == nil {
		t.Fatal("INSERT over the read-only DSN should be rejected, got nil error")
	}

	// query_only additionally rejects writes to an ATTACH-created database,
	// which mode=ro alone does not stop (SQLite's read-only open only
	// protects the file named in the DSN, not databases attached later).
	attachedPath := filepath.Join(filepath.Dir(dbPath), "attached.db")
	if _, err := db.Exec("ATTACH DATABASE '" + attachedPath + "' AS e"); err != nil {
		t.Fatalf("ATTACH itself is not expected to fail (only writes to it should): %v", err)
	}
	if _, err := db.Exec("CREATE TABLE e.pwned (x INTEGER)"); err == nil {
		t.Fatal("CREATE TABLE in an ATTACH-ed database over the query_only DSN should be rejected, got nil error")
	}
}
