package main

// Unit tests for `loader init-db` (task 5.2). These run against a temp-file
// SQLite database and need no external service.

import (
	"bytes"
	"database/sql"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// envWithDBPath returns an env lookup that reports dbPath for MSR_DB_PATH
// and empty (default) for everything else.
func envWithDBPath(dbPath string) func(string) string {
	return func(key string) string {
		if key == "MSR_DB_PATH" {
			return dbPath
		}
		return ""
	}
}

func TestRunInitDB_CreatesSchema(t *testing.T) {
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "nested", "msr.db")

	var stdout bytes.Buffer
	if err := runInitDB(envWithDBPath(dbPath), &stdout); err != nil {
		t.Fatalf("runInitDB: %v", err)
	}

	if _, err := os.Stat(dbPath); err != nil {
		t.Fatalf("expected database file at %s: %v", dbPath, err)
	}

	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		t.Fatalf("opening %s to verify schema: %v", dbPath, err)
	}
	defer db.Close()

	var count int
	if err := db.QueryRow(`SELECT COUNT(*) FROM measurement_value`).Scan(&count); err != nil {
		t.Fatalf("querying measurement_value after runInitDB: %v", err)
	}

	if stdout.Len() == 0 {
		t.Error("expected progress output on stdout, got none")
	}
}

func TestRunInitDB_IdempotentPreservesRows(t *testing.T) {
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "msr.db")
	env := envWithDBPath(dbPath)

	var stdout bytes.Buffer
	if err := runInitDB(env, &stdout); err != nil {
		t.Fatalf("first runInitDB: %v", err)
	}

	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		t.Fatalf("opening %s: %v", dbPath, err)
	}
	defer db.Close()

	const locator = "nist-srd27/density#BeF2-LiF|66.0-34.0"
	if _, err := db.Exec(
		`INSERT INTO measurement_value (locator, salt, property, source) VALUES (?, ?, ?, ?)`,
		locator, "BeF2-LiF|66.0-34.0", "density", "nist",
	); err != nil {
		t.Fatalf("seeding a row before the second runInitDB: %v", err)
	}

	if err := runInitDB(env, &stdout); err != nil {
		t.Fatalf("second runInitDB (idempotency): %v", err)
	}

	var count int
	if err := db.QueryRow(
		`SELECT COUNT(*) FROM measurement_value WHERE locator = ?`, locator,
	).Scan(&count); err != nil {
		t.Fatalf("counting preserved rows: %v", err)
	}
	if count != 1 {
		t.Fatalf("expected the pre-inserted row to survive a second runInitDB, got count=%d", count)
	}
}

func TestRunInitDB_CreatesParentDirs(t *testing.T) {
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "a", "b", "c", "msr.db")

	var stdout bytes.Buffer
	if err := runInitDB(envWithDBPath(dbPath), &stdout); err != nil {
		t.Fatalf("runInitDB with nested missing parent dirs: %v", err)
	}
	if _, err := os.Stat(dbPath); err != nil {
		t.Fatalf("expected database file at %s after MkdirAll: %v", dbPath, err)
	}
}

func TestRunInitDB_ReportsDBPathInOutput(t *testing.T) {
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "msr.db")

	var stdout bytes.Buffer
	if err := runInitDB(envWithDBPath(dbPath), &stdout); err != nil {
		t.Fatalf("runInitDB: %v", err)
	}
	if !strings.Contains(stdout.String(), dbPath) {
		t.Errorf("expected stdout to mention db path %q, got %q", dbPath, stdout.String())
	}
}
