"""Text-derived measurement dual-store writer tests (chunk 7, task 8.5
dual-store write + idempotency, 8.12 per-run provenance edge).

Exercises ``write_measurement`` against a temp SQLite ``measurement_value``
table (the exact DDL the Go loader creates) and a ``FakeClient`` that
records ``.update(...)`` calls instead of touching the network -- mirrors
``test_mentions.py``'s fake-client style and ``test_measurement_store.py``'s
``tmp_path`` SQLite fixture style. Also pins ``to_row``'s coefficient
mapping in isolation.

Written against ``msr_extraction.measurements`` before it exists (task 8.5
is implemented by a sibling coder in parallel); it is expected to fail
collection until the pass-2 merge. See the pass-1 handoff report for the
signature assumptions this file pins (flagged for reconciliation).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from msr_extraction.equations import EquationParse
from msr_extraction.measurement_store import connect
from msr_extraction.measurements import (
    measurement_provenance_insert_data,
    to_row,
    write_measurement,
)

SALT_IRI = "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"
PROPERTY_IRI = "https://w3id.org/msr-kg/ontology#viscosity"
PROPERTY_NAME = "viscosity"
UNIT_CURIE = "unit:MilliPA-SEC"
REPORT = "ORNL-TM-2316"
CONFIDENCE = 0.92
RATIONALE = "stated as ..."
RUN_TS = "2026-01-01T00:00:00+00:00"

EQUATION = EquationParse("Arrhenius", [0.084, 4340], None, None)

EXPECTED_LOCATOR = "doc/ORNL-TM-2316/viscosity#BeF2-LiF-34.0-66.0"
EXPECTED_MIRI = "msrd:m-doc-ORNL-TM-2316-viscosity-BeF2-LiF-34.0-66.0"

# The exact measurement_value DDL the Go loader creates at `load-seed`
# (internal/store), copied from test_measurement_store.py's fixture --
# write_measurement's SQLite half writes into this pre-existing table; it
# does not create the schema itself.
_SCHEMA = """
CREATE TABLE measurement_value (
  locator TEXT PRIMARY KEY, salt TEXT, property TEXT,
  c0 REAL, c1 REAL, c2 REAL, c3 REAL, c4 REAL,
  t_min REAL, t_max REAL, equation_form TEXT, uncertainty TEXT,
  source TEXT NOT NULL CHECK (source IN ('nist','document')), doc_id TEXT
);
"""


class FakeClient:
    """Captures ``.update(...)`` calls; never touches the network."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def update(self, sparql_update: str) -> None:
        self.calls.append(sparql_update)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "msr.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()
    return path


def _write_measurement_kwargs(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = dict(
        salt_iri=SALT_IRI,
        property_iri=PROPERTY_IRI,
        property_name=PROPERTY_NAME,
        unit_curie=UNIT_CURIE,
        equation=EQUATION,
        uncertainty=None,
        confidence=CONFIDENCE,
        rationale=RATIONALE,
        report=REPORT,
        run_ts=RUN_TS,
    )
    fields.update(overrides)
    return fields


def _graph_calls(calls: list[str], marker: str) -> list[str]:
    matches = [c for c in calls if marker in c]
    assert matches, f"no update call contains {marker!r} (calls={calls!r})"
    return matches


def test_write_measurement_returns_the_pinned_measurement_iri(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        fake = FakeClient()
        miri = write_measurement(**_write_measurement_kwargs(client=fake, conn=conn))
        assert miri == EXPECTED_MIRI
    finally:
        conn.close()


def test_write_measurement_inserts_exactly_one_sqlite_row_with_expected_values(
    db_path: Path,
) -> None:
    conn = connect(db_path)
    try:
        fake = FakeClient()
        write_measurement(**_write_measurement_kwargs(client=fake, conn=conn))
        rows = conn.execute(
            "SELECT locator, salt, property, equation_form, c0, c1, source, doc_id "
            "FROM measurement_value"
        ).fetchall()
        assert len(rows) == 1
        locator, salt, prop, form, c0, c1, source, doc_id = rows[0]
        assert locator == EXPECTED_LOCATOR
        assert salt == "BeF2-LiF-34.0-66.0"
        assert prop == "viscosity"
        assert form == "Arrhenius"
        assert c0 == 0.084
        assert c1 == 4340
        assert source == "document"
        assert doc_id == "ORNL-TM-2316"
    finally:
        conn.close()


def test_write_measurement_sends_a_data_graph_update_and_a_provenance_update(
    db_path: Path,
) -> None:
    """Covers 8.5 (dual-store write) + 8.12 (per-run generation edge): at
    least one update targets ``GRAPH <urn:msr:data>`` (the measurement
    triples) and at least one targets ``GRAPH <urn:msr:provenance>``
    carrying the measurement's per-run generation edge."""
    conn = connect(db_path)
    try:
        fake = FakeClient()
        miri = write_measurement(**_write_measurement_kwargs(client=fake, conn=conn))
        assert len(fake.calls) >= 2

        data_calls = _graph_calls(fake.calls, "GRAPH <urn:msr:data>")
        assert any(miri in c for c in data_calls)

        prov_calls = _graph_calls(fake.calls, "GRAPH <urn:msr:provenance>")
        expected_edge = f"{miri} prov:wasGeneratedBy <urn:msr:run:extraction/{RUN_TS}>"
        assert any(expected_edge in c for c in prov_calls)
    finally:
        conn.close()


def test_write_measurement_is_idempotent_in_sqlite_on_rerun(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        fake = FakeClient()
        write_measurement(**_write_measurement_kwargs(client=fake, conn=conn))
        write_measurement(**_write_measurement_kwargs(client=fake, conn=conn))
        count = conn.execute("SELECT COUNT(*) FROM measurement_value").fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_write_measurement_data_graph_update_is_byte_identical_on_rerun(
    db_path: Path,
) -> None:
    """The urn:msr:data write is a pure function of the measurement inputs
    (deterministic IRIs, no blank nodes), so re-running at the same run_ts
    re-emits a byte-identical urn:msr:data update (design D5/8.5)."""
    conn = connect(db_path)
    try:
        fake_first = FakeClient()
        write_measurement(**_write_measurement_kwargs(client=fake_first, conn=conn))
        first_data_calls = _graph_calls(fake_first.calls, "GRAPH <urn:msr:data>")

        fake_second = FakeClient()
        write_measurement(**_write_measurement_kwargs(client=fake_second, conn=conn))
        second_data_calls = _graph_calls(fake_second.calls, "GRAPH <urn:msr:data>")

        assert first_data_calls == second_data_calls
    finally:
        conn.close()


def test_write_measurement_leaves_no_wal_or_shm_sidecar_files(
    db_path: Path, tmp_path: Path
) -> None:
    conn = connect(db_path)
    try:
        fake = FakeClient()
        write_measurement(**_write_measurement_kwargs(client=fake, conn=conn))
    finally:
        conn.close()
    assert not (tmp_path / "msr.db-wal").exists()
    assert not (tmp_path / "msr.db-shm").exists()


# --- measurement_provenance_insert_data (8.12) ------------------------------


def test_measurement_provenance_insert_data_carries_the_per_run_edge() -> None:
    """Reconciled to the merged signature
    ``measurement_provenance_insert_data(measurement_iris: list[str], run_ts)``
    (a list of IRIs, mirroring ``mentions.provenance_insert_data``)."""
    update = measurement_provenance_insert_data([EXPECTED_MIRI], RUN_TS)
    assert "GRAPH <urn:msr:provenance>" in update
    assert (
        f"{EXPECTED_MIRI} prov:wasGeneratedBy <urn:msr:run:extraction/{RUN_TS}>" in update
    )


# --- to_row (8.5 SQLite mapping) --------------------------------------------


def test_to_row_maps_coefficients_positionally_and_pads_the_rest_with_none() -> None:
    """Reconciled to the merged ``to_row`` signature: it takes ``salt_iri``
    (the full salt IRI, from which the ``salt`` column slug is derived) and
    ``doc_id`` (not ``salt``/``report``), returning a
    ``measurement_store.MeasurementRow`` (attributes
    ``salt``/``property``/``equation_form``/``c0..c4``/``source``/``doc_id``)."""
    row = to_row(
        locator=EXPECTED_LOCATOR,
        salt_iri=SALT_IRI,
        property_name=PROPERTY_NAME,
        equation=EQUATION,
        uncertainty=None,
        doc_id=REPORT,
    )
    assert row.locator == EXPECTED_LOCATOR
    assert row.salt == "BeF2-LiF-34.0-66.0"
    assert row.property == "viscosity"
    assert row.equation_form == "Arrhenius"
    assert row.c0 == 0.084
    assert row.c1 == 4340
    assert row.c2 is None
    assert row.c3 is None
    assert row.c4 is None
    assert row.source == "document"
    assert row.doc_id == "ORNL-TM-2316"
