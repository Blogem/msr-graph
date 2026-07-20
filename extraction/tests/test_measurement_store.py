"""SQLite measurement_value store tests (task 8.5, SQLite half).

Pins ``connect(db_path) -> sqlite3.Connection`` (WAL disabled: ``PRAGMA
journal_mode=delete``, a non-zero ``busy_timeout``, no ``-wal``/``-shm``
sidecar files) and ``upsert_rows(conn, rows)`` upserting on the ``locator``
primary key (idempotent re-insert, in-place update on a changed
coefficient). Hermetic: all I/O is a ``tmp_path`` SQLite file, no network.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from msr_extraction.measurement_store import MeasurementRow, connect, upsert_rows

LOCATOR = "doc/ORNL-TM-2316/viscosity#BeF2-LiF|34.0-66.0"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    # A fresh, not-yet-existing DB file -- connect() is responsible for
    # creating the measurement_value schema on first connection (it is the
    # only schema-creation entry point in the pinned API: connect,
    # upsert_rows, MeasurementRow -- no separate init/migrate function).
    return tmp_path / "msr.db"


def _row(**overrides: object) -> MeasurementRow:
    fields: dict[str, object] = dict(
        locator=LOCATOR,
        salt="BeF2-LiF-34.0-66.0",
        property="viscosity",
        c0=0.084,
        c1=4340,
        c2=None,
        c3=None,
        c4=None,
        t_min=None,
        t_max=None,
        equation_form="Arrhenius",
        uncertainty=None,
        source="document",
        doc_id="ORNL-TM-2316",
    )
    fields.update(overrides)
    return MeasurementRow(**fields)


def test_connect_disables_wal_and_sets_busy_timeout(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert journal_mode == "delete"
        assert busy_timeout > 0
    finally:
        conn.close()


def test_connect_leaves_no_wal_or_shm_sidecar_files(db_path: Path, tmp_path: Path) -> None:
    conn = connect(db_path)
    upsert_rows(conn, [_row()])
    conn.close()
    assert not (tmp_path / "msr.db-wal").exists()
    assert not (tmp_path / "msr.db-shm").exists()


def test_upsert_inserts_exactly_one_row_with_expected_values(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        upsert_rows(conn, [_row()])
        rows = conn.execute(
            "SELECT locator, salt, property, c0, c1, doc_id, source, equation_form "
            "FROM measurement_value"
        ).fetchall()
        assert len(rows) == 1
        locator, salt, prop, c0, c1, doc_id, source, form = rows[0]
        assert locator == LOCATOR
        assert salt == "BeF2-LiF-34.0-66.0"
        assert prop == "viscosity"
        assert c0 == 0.084
        assert c1 == 4340
        assert doc_id == "ORNL-TM-2316"
        assert source == "document"
        assert form == "Arrhenius"
    finally:
        conn.close()


def test_upsert_identical_row_twice_is_idempotent(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        upsert_rows(conn, [_row()])
        upsert_rows(conn, [_row()])
        count = conn.execute("SELECT COUNT(*) FROM measurement_value").fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_upsert_with_changed_coefficient_updates_in_place(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        upsert_rows(conn, [_row()])
        upsert_rows(conn, [_row(c0=0.099)])
        rows = conn.execute(
            "SELECT c0 FROM measurement_value WHERE locator = ?", (LOCATOR,)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 0.099
        count = conn.execute("SELECT COUNT(*) FROM measurement_value").fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_locator_is_the_primary_key(db_path: Path) -> None:
    """Introspects the created schema: ``locator`` must be declared PRIMARY
    KEY (pk index == 1 in ``PRAGMA table_info``), matching the pinned DDL."""
    conn = connect(db_path)
    try:
        upsert_rows(conn, [_row()])
        columns = conn.execute("PRAGMA table_info(measurement_value)").fetchall()
        by_name = {row[1]: row for row in columns}
        assert "locator" in by_name
        # PRAGMA table_info row shape: (cid, name, type, notnull, dflt_value, pk)
        assert by_name["locator"][5] == 1
    finally:
        conn.close()


def test_source_check_constraint_rejects_an_invalid_value(db_path: Path) -> None:
    """The schema's ``CHECK (source IN ('nist','document'))`` constraint is
    enforced at the SQLite level, independent of any app-side validation."""
    conn = connect(db_path)
    try:
        upsert_rows(conn, [_row()])  # ensures the table exists
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO measurement_value (locator, source) VALUES (?, ?)",
                ("some-other-locator", "bogus"),
            )
            conn.commit()
    finally:
        conn.close()
