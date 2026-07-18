// Package store provides the SQLite-backed measurement value store,
// including idempotent schema initialization and a connection-opening
// helper that pins the runtime contract (journal_mode=DELETE,
// busy_timeout).
package store

import (
	"context"
	"database/sql"
	_ "embed"
	"fmt"

	_ "modernc.org/sqlite"
)

// schemaDDL is the embedded measurement_value DDL. It is applied with
// CREATE TABLE IF NOT EXISTS semantics so Init is idempotent. Later
// chunks that add tables extend this single script rather than creating
// their own.
//
//go:embed schema.sql
var schemaDDL string

// busyTimeoutMillis is the non-zero SQLite busy_timeout pinned on every
// connection opened via Open.
const busyTimeoutMillis = 5000

// driverName is the database/sql driver name registered by
// modernc.org/sqlite.
const driverName = "sqlite"

// Open opens (creating if absent) the SQLite database at path, pinning
// journal_mode=DELETE (never WAL, which breaks read-only sandbox mounts)
// and a non-zero busy_timeout on every connection via DSN query
// parameters that modernc.org/sqlite applies to each pooled connection.
// The caller is responsible for closing the returned *sql.DB.
func Open(path string) (*sql.DB, error) {
	dsn := fmt.Sprintf(
		"file:%s?_pragma=journal_mode(DELETE)&_pragma=busy_timeout(%d)",
		path, busyTimeoutMillis,
	)

	db, err := sql.Open(driverName, dsn)
	if err != nil {
		return nil, fmt.Errorf("store: open %s: %w", path, err)
	}
	return db, nil
}

// Init applies the measurement_value DDL idempotently
// (CREATE TABLE IF NOT EXISTS). It is safe to call repeatedly against the
// same database.
func Init(ctx context.Context, db *sql.DB) error {
	if _, err := db.ExecContext(ctx, schemaDDL); err != nil {
		return fmt.Errorf("store: init schema: %w", err)
	}
	return nil
}
