"""SQLite writer for `measurement_value` rows (task 5.4, measurement-store spec).

Mirrors the Go `internal/store` contract exactly across the language
boundary: a connection helper that pins `journal_mode=DELETE` (never WAL --
no `-wal`/`-shm` sidecar files) plus a non-zero `busy_timeout`, and an
idempotent upsert-by-`locator` writer built on
`INSERT ... ON CONFLICT(locator) DO UPDATE SET ... = excluded....`.

This module does not create or migrate the `measurement_value` table -- the
Go loader (`load-seed`) owns that schema. It assumes the table already
exists with exactly the columns in the measurement-store spec:

    CREATE TABLE measurement_value (
      locator TEXT PRIMARY KEY, salt TEXT, property TEXT,
      c0 REAL, c1 REAL, c2 REAL, c3 REAL, c4 REAL,
      t_min REAL, t_max REAL, equation_form TEXT, uncertainty TEXT,
      source TEXT NOT NULL CHECK (source IN ('nist','document')), doc_id TEXT
    );

Stdlib only (`sqlite3`) -- no third-party SQLite driver is needed since this
writes to the same on-disk file the Go binary manages.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

# Non-zero busy_timeout (milliseconds) pinned on every connection, matching
# Go's internal/store.busyTimeoutMillis so both writers back off identically
# under lock contention instead of failing immediately with SQLITE_BUSY.
BUSY_TIMEOUT_MS = 5000


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a connection with journal_mode=DELETE + busy_timeout pinned.

    journal_mode=DELETE (never WAL) guarantees no `-wal`/`-shm` sidecar files
    are ever created next to the database file, matching the Go writer's
    runtime contract (internal/store.Open).
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    return conn


@dataclass(frozen=True)
class MeasurementRow:
    """One `measurement_value` row. Nullable columns default to None so
    callers only need to supply the fields they have."""

    locator: str
    salt: str
    property: str
    equation_form: str
    c0: float | None = None
    c1: float | None = None
    c2: float | None = None
    c3: float | None = None
    c4: float | None = None
    t_min: float | None = None
    t_max: float | None = None
    uncertainty: str | None = None
    doc_id: str | None = None
    source: str = "document"


# Inserts a measurement_value row, or updates every non-PK column from the
# excluded values when a row with the same locator already exists. This
# keeps writes idempotent by locator: re-upserting identical values is a
# no-op in effect, and re-upserting changed values updates the row in place
# rather than creating a duplicate. Mirrors internal/store.upsertSQL.
_UPSERT_SQL = """INSERT INTO measurement_value
    (locator, salt, property, c0, c1, c2, c3, c4, t_min, t_max, equation_form, uncertainty, source, doc_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(locator) DO UPDATE SET
        salt = excluded.salt,
        property = excluded.property,
        c0 = excluded.c0,
        c1 = excluded.c1,
        c2 = excluded.c2,
        c3 = excluded.c3,
        c4 = excluded.c4,
        t_min = excluded.t_min,
        t_max = excluded.t_max,
        equation_form = excluded.equation_form,
        uncertainty = excluded.uncertainty,
        source = excluded.source,
        doc_id = excluded.doc_id"""


def upsert_rows(conn: sqlite3.Connection, rows: list[MeasurementRow]) -> None:
    """Upsert rows by locator (INSERT ... ON CONFLICT(locator) DO UPDATE).

    Empty `rows` is a no-op (returns without touching the DB). Commits on
    success; the caller is responsible for handling/rolling back on
    exceptions raised by the underlying `executemany`.
    """
    if not rows:
        return

    conn.executemany(
        _UPSERT_SQL,
        [
            (
                row.locator,
                row.salt,
                row.property,
                row.c0,
                row.c1,
                row.c2,
                row.c3,
                row.c4,
                row.t_min,
                row.t_max,
                row.equation_form,
                row.uncertainty,
                row.source,
                row.doc_id,
            )
            for row in rows
        ],
    )
    conn.commit()
