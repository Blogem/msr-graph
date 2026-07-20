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
`internal/store` SHALL expose the connection-opening helper that pins `journal_mode=DELETE` and sets `busy_timeout` on every connection. All later **Go** writers MUST open connections through this helper so the runtime contract is enforced in code, not convention. The chunk-7 extraction writer is **Python** (the extraction container) and cannot link the Go helper across the language boundary; it SHALL instead enforce the identical runtime contract (`journal_mode=DELETE` + a non-zero `busy_timeout` on every connection, no `-wal`/`-shm` sidecars) via a small Python stdlib `sqlite3` connection helper. The contract — not the particular helper — is the guarantee, and it is enforced in code on both sides of the language boundary.

#### Scenario: Journal mode pinned
- **WHEN** a connection is opened through the store helper
- **THEN** `PRAGMA journal_mode` reports `delete` and `PRAGMA busy_timeout` reports the configured non-zero timeout

#### Scenario: No WAL sidecar files
- **WHEN** the database is initialized and written through the store helper
- **THEN** no `-wal` or `-shm` files exist next to the database file (read-only directory mounts in sandboxes remain viable)

#### Scenario: The Python extraction writer enforces the same contract
- **WHEN** the chunk-7 Python writer opens a connection to `measurement_value`
- **THEN** `PRAGMA journal_mode` reports `delete`, a non-zero `busy_timeout` is set, and no `-wal`/`-shm` file appears next to the database — the same runtime contract as the Go helper, enforced in Python

### Requirement: Idempotent upsert by locator
`internal/store` SHALL expose an idempotent write path that upserts `measurement_value` rows keyed on the `locator` primary key (`INSERT … ON CONFLICT(locator) DO UPDATE`, equivalently `INSERT OR REPLACE`), so re-running a batch loader with the same locators leaves the row count unchanged and updates any changed columns in place. The Go batch writer (the chunk-2 NIST loader) MUST write through this helper so the upsert-by-locator contract and the pinned connection settings are enforced in code, not convention. The chunk-7 Python extraction writer, which cannot use the Go helper across the language boundary, SHALL implement the same upsert-by-`locator` semantics (`INSERT … ON CONFLICT(locator) DO UPDATE`) through its Python connection helper, so its re-runs are equally idempotent on the row count.

#### Scenario: First write inserts the row
- **WHEN** a measurement row with a new locator is upserted
- **THEN** `measurement_value` contains exactly one row for that locator with the written column values

#### Scenario: Re-upserting the same locator is a no-op on count
- **WHEN** the same locator is upserted a second time with identical values
- **THEN** the total row count is unchanged and the row's values are unchanged

#### Scenario: Re-upserting updates changed columns
- **WHEN** a locator already present is upserted with a changed coefficient value
- **THEN** the existing row is updated in place, no duplicate row is created, and the row count is unchanged

#### Scenario: The Python extraction writer upserts by locator idempotently
- **WHEN** the chunk-7 Python writer upserts a `source='document'` row and the `extract` run is repeated with the same locator
- **THEN** the row count is unchanged after the second run and any changed columns are updated in place, matching the Go writer's upsert-by-locator contract
