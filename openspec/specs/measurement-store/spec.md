# measurement-store Specification

## Purpose

Define the SQLite measurement store: idempotent database initialization with the contract `measurement_value` schema, and a shared connection-opening helper that pins runtime connection settings.

## Requirements

### Requirement: Idempotent SQLite initialization
The system SHALL initialize the SQLite database via `cmd/loader init-db` (invoked by `make load-seed` or standalone), applying the `measurement_value` DDL embedded in `internal/store` with `CREATE TABLE IF NOT EXISTS` semantics. The DDL MUST match the contract schema exactly:

```sql
CREATE TABLE measurement_value (
  locator TEXT PRIMARY KEY, salt TEXT, property TEXT,
  c0 REAL, c1 REAL, c2 REAL, c3 REAL, c4 REAL,
  t_min REAL, t_max REAL, equation_form TEXT, uncertainty TEXT,
  source TEXT NOT NULL CHECK (source IN ('nist','document')), doc_id TEXT
);
```

Later chunks adding tables extend this init script rather than creating their own.

#### Scenario: Fresh init creates the table
- **WHEN** `cmd/loader init-db` runs against a path with no database file
- **THEN** the database exists with the `measurement_value` table matching the contract schema

#### Scenario: Re-running init is a no-op
- **WHEN** `cmd/loader init-db` runs against an already-initialized database containing rows
- **THEN** the command succeeds and existing rows and schema are unchanged

### Requirement: Pinned connection settings via a shared opening helper
`internal/store` SHALL expose the connection-opening helper that pins `journal_mode=DELETE` and sets `busy_timeout` on every connection. All later writers (chunks 2, 7) MUST open connections through this helper so the runtime contract is enforced in code, not convention.

#### Scenario: Journal mode pinned
- **WHEN** a connection is opened through the store helper
- **THEN** `PRAGMA journal_mode` reports `delete` and `PRAGMA busy_timeout` reports the configured non-zero timeout

#### Scenario: No WAL sidecar files
- **WHEN** the database is initialized and written through the store helper
- **THEN** no `-wal` or `-shm` files exist next to the database file (read-only directory mounts in sandboxes remain viable)
