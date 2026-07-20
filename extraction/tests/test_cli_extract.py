"""Hermetic end-to-end smoke test for the `extract` CLI umbrella
(`cli._cmd_extract`), plus task 8.12's run-level provenance ordering.

Mirrors `test_cli_link.py`'s posture exactly: the three network-touching
collaborator factories `_cmd_extract` constructs (`GraphReader.from_config`,
`SparqlClient.from_config`, `FlashClient.from_config`) are monkeypatched to
hermetic fakes in the `cli` module namespace, `curated.CURATED_REPORTS` is
pinned to one synthetic report, and a tmp corpus dir supplies
`segments.jsonl` + `mentions.jsonl`. A tmp SQLite file backs `config.db_path`
with the `measurement_value` table pre-created (mirroring
`test_measurement_store.py`'s fixture), since `_cmd_extract` writes through
`measurement_store`/`measurements.write_measurement` to it.

Written pass-1 against the pinned `_cmd_extract` contract (chunk 7, task
8.12) while a sibling coder writes `_cmd_extract` itself concurrently in a
separate worktree -- `cli._cmd_extract` does not exist yet here, so this
module is expected to error at collection until pass 2 merges it.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from msr_extraction import cli, curated
from msr_extraction.config import Config
from msr_extraction.graph_reader import KnownEntity

SALT = "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"
VISC = "https://w3id.org/msr-kg/ontology#viscosity"
COOLANT = "https://w3id.org/msr-kg/ontology#CoolantSalt"
MSRE = "https://w3id.org/msr-kg/vocab#msre-reactor"
REPORT = "ORNL-TM-2316"

MEASUREMENT_IRI = "msrd:m-doc-ORNL-TM-2316-viscosity-BeF2-LiF-34.0-66.0"

QUDT_UNITS_PATH = Path(__file__).resolve().parents[2] / "ontology" / "qudt-units.json"
ONTOLOGY_DIR = QUDT_UNITS_PATH.parent

_MEASUREMENT_VALUE_SCHEMA = """
CREATE TABLE measurement_value (
  locator TEXT PRIMARY KEY, salt TEXT, property TEXT,
  c0 REAL, c1 REAL, c2 REAL, c3 REAL, c4 REAL,
  t_min REAL, t_max REAL, equation_form TEXT, uncertainty TEXT,
  source TEXT NOT NULL CHECK (source IN ('nist','document')), doc_id TEXT
);
"""

_FLASH_JSON = (
    '{"relations": [ '
    '{"kind":"measurement","salt":"' + SALT + '","property":"' + VISC + '",'
    '"unit":"cP","form_hint":"Arrhenius","coefficients":[0.084,4340],'
    '"confidence":0.95,"rationale":"eta=0.084 exp(4340/T)"}, '
    '{"kind":"reactor","salt":"' + SALT + '","reactor":"' + MSRE + '",'
    '"confidence":0.9,"rationale":"used in MSRE"} ] }'
)


class _FakeGraphReader:
    """Hermetic stand-in for `GraphReader`: fixed in-memory known-entity +
    closed-set data. Implements exactly the surface `_cmd_extract`/
    `KGSchemaPromptCache`/`relations.KnownSets`-building need -- no network.
    """

    def __init__(self, known: list[KnownEntity]) -> None:
        self._known = known

    def read_known_entities(self) -> list[KnownEntity]:
        return list(self._known)

    def read_version(self) -> str:
        return "0.4.0"

    def known_iris(self) -> set[str]:
        return {entity.target_iri for entity in self._known}

    def read_molten_salts(self) -> set[str]:
        return {SALT}

    def read_physical_properties(self) -> set[str]:
        return {VISC}

    def read_salt_roles(self) -> set[str]:
        return {COOLANT}

    def read_reactor_concepts(self) -> set[str]:
        return {MSRE}


class _FakeSparqlClient:
    """Records every `update(sparql)` call instead of hitting a live GraphDB."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def update(self, sparql_update: str) -> None:
        self.calls.append(sparql_update)


class _StubFlashCompleter:
    """Returns a fixed JSON reply for every sentence -- one measurement, one
    reactor relation, both referencing `SALT`/`VISC`/`MSRE`."""

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        return _FLASH_JSON


def _known_entities() -> list[KnownEntity]:
    return [
        KnownEntity(target_iri=VISC, labels=("viscosity",), kind="concept"),
        KnownEntity(
            target_iri=SALT,
            labels=("BeF2-LiF (34.0-66.0 mol%)", "LiF-BeF2"),
            kind="salt",
        ),
        KnownEntity(target_iri=MSRE, labels=("MSRE",), kind="concept"),
    ]


def _write_corpus(tmp_path: Path, report: str) -> None:
    report_dir = tmp_path / report
    report_dir.mkdir(parents=True)
    text = "FLiBe's viscosity is 0.084 exp(4340/T) cP and it was used in the MSRE."
    segment = {
        "report": report,
        "index": 0,
        "text": text,
        "char_start": 0,
        "char_end": len(text),
    }
    (report_dir / "segments.jsonl").write_text(json.dumps(segment) + "\n", encoding="utf-8")

    salt_mention = {
        "report": report,
        "seg_index": 0,
        "char_start": 0,
        "char_end": 5,
        "status": "linked",
        "surface_form": "FLiBe",
        "target_iri": SALT,
        "target_kind": "salt",
    }
    reactor_mention = {
        "report": report,
        "seg_index": 0,
        "char_start": 60,
        "char_end": 64,
        "status": "linked",
        "surface_form": "MSRE",
        "target_iri": MSRE,
        "target_kind": "concept",
    }
    mentions_path = report_dir / "mentions.jsonl"
    with mentions_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(salt_mention) + "\n")
        fh.write(json.dumps(reactor_mention) + "\n")


def _make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "msr.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_MEASUREMENT_VALUE_SCHEMA)
    conn.commit()
    conn.close()
    return db_path


def _setup(tmp_path: Path, monkeypatch, report: str = REPORT) -> tuple[Config, _FakeSparqlClient]:
    """Patch `_cmd_extract`'s collaborators + env, write the tmp corpus +
    SQLite DB, and return the resulting `(Config, fake_sparql)`."""
    db_path = _make_db(tmp_path)

    monkeypatch.setenv("MSR_CORPUS_DIR", str(tmp_path))
    monkeypatch.setenv("MSR_DB_PATH", str(db_path))
    monkeypatch.setenv("MSR_ONTOLOGY_DIR", str(ONTOLOGY_DIR))
    monkeypatch.setattr(curated, "CURATED_REPORTS", [report])

    known = _known_entities()
    monkeypatch.setattr(
        cli,
        "GraphReader",
        SimpleNamespace(from_config=lambda config: _FakeGraphReader(known)),
    )

    fake_sparql = _FakeSparqlClient()
    monkeypatch.setattr(
        cli,
        "SparqlClient",
        SimpleNamespace(from_config=lambda config: fake_sparql),
    )

    monkeypatch.setattr(
        cli,
        "FlashClient",
        SimpleNamespace(from_config=lambda config: _StubFlashCompleter()),
    )

    _write_corpus(tmp_path, report)

    config = Config.from_env()
    return config, fake_sparql


def _row_count(db_path: Path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        (count,) = conn.execute(
            "SELECT COUNT(*) FROM measurement_value WHERE source = 'document'"
        ).fetchone()
        return count
    finally:
        conn.close()


def test_cmd_extract_missing_flash_client_is_a_noop(tmp_path, monkeypatch) -> None:
    """Pinned behavior #2: no Flash client configured -> `_cmd_extract` logs
    a warning and returns 0 without writing anything (no SPARQL update, no
    SQLite row)."""
    config, fake_sparql = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "FlashClient", SimpleNamespace(from_config=lambda config: None))

    result = cli._cmd_extract(config)

    assert result == 0
    assert fake_sparql.calls == []
    assert _row_count(config.db_path) == 0


def test_cmd_extract_smoke_writes_measurements_edges_and_summary(tmp_path, monkeypatch, capsys) -> None:
    """`cli._cmd_extract(config)` runs the full extract pipeline hermetically
    end-to-end (task 8.12): a per-run `prov:Activity` node is written before
    any generation edge, the written measurement carries
    `prov:wasGeneratedBy`/`prov:wasDerivedFrom` + a per-run generation edge,
    the grounded reactor relation mints+links a reactor individual,
    `relations.jsonl` records a written disposition, the SQLite row is
    written exactly once, and a summary line is printed.
    """
    config, fake_sparql = _setup(tmp_path, monkeypatch)

    result = cli._cmd_extract(config)
    assert result == 0

    calls = fake_sparql.calls
    assert calls, "expected _cmd_extract to issue at least one SPARQL update"

    # --- Ordering (8.12): stable + per-run activity before any fact write ---
    def _first_index(predicate) -> int:
        for i, call in enumerate(calls):
            if predicate(call):
                return i
        raise AssertionError(f"no matching call found in: {calls}")

    stable_activity_idx = _first_index(
        lambda c: "msrd:activity-extraction" in c and "GRAPH <urn:msr:data>" in c
    )
    run_activity_idx = _first_index(
        lambda c: "<urn:msr:run:extraction/" in c
        and "a prov:Activity" in c
        and "GRAPH <urn:msr:provenance>" in c
    )
    first_fact_write_idx = _first_index(
        lambda c: "msr:PropertyMeasurement" in c or "msr:hasRole" in c or "msr:usedIn" in c
    )

    assert stable_activity_idx < first_fact_write_idx, calls
    assert run_activity_idx < first_fact_write_idx, calls

    # --- Measurement provenance in the data graph ---
    measurement_data_calls = [
        c for c in calls if "a msr:PropertyMeasurement" in c and "GRAPH <urn:msr:data>" in c
    ]
    assert measurement_data_calls, f"expected a PropertyMeasurement data-graph write, got: {calls}"
    measurement_call = measurement_data_calls[0]
    assert "prov:wasGeneratedBy msrd:activity-extraction" in measurement_call
    assert "prov:wasDerivedFrom msrd:ORNL-TM-2316" in measurement_call
    assert "msr:citedIn msrd:ORNL-TM-2316" in measurement_call

    # --- Per-run generation edge for the measurement ---
    assert any(
        "GRAPH <urn:msr:provenance>" in c
        and "prov:wasGeneratedBy <urn:msr:run:extraction/" in c
        and MEASUREMENT_IRI in c
        for c in calls
    ), f"expected a per-run generation edge for {MEASUREMENT_IRI}, got: {calls}"

    # --- Reactor mint + usedIn ---
    reactor_calls = [
        c
        for c in calls
        if "msrd:reactor-msre a msr:MoltenSaltReactor" in c and "msr:usedIn msrd:reactor-msre" in c
    ]
    assert reactor_calls, f"expected a minted-reactor + usedIn write, got: {calls}"

    # --- relations.jsonl trace ---
    relations_path = config.relations_path(REPORT)
    assert relations_path.exists(), "expected _cmd_extract to write relations.jsonl"
    records = [
        json.loads(line)
        for line in relations_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    written = [r for r in records if r["disposition"] == "written"]
    assert written, f"expected >=1 written relation record, got: {records}"

    # --- SQLite: exactly one document-sourced row ---
    assert _row_count(config.db_path) == 1

    # --- Summary line ---
    captured = capsys.readouterr()
    assert "extract: report=ORNL-TM-2316" in captured.out


def test_cmd_extract_second_run_appends_activity_and_upserts_idempotently(
    tmp_path, monkeypatch
) -> None:
    """Task 8.12: a second invocation (distinct `run_ts`) appends a second
    per-run activity node while the SQLite row count stays at one (the
    upsert is idempotent) and the measurement's `urn:msr:data` write is
    byte-identical across runs (the data graph itself is unchanged)."""
    config, fake_sparql = _setup(tmp_path, monkeypatch)

    timestamps = iter(["2024-01-01T00:00:00+00:00", "2024-01-02T00:00:00+00:00"])
    monkeypatch.setattr(cli.provenance, "run_timestamp", lambda: next(timestamps))

    assert cli._cmd_extract(config) == 0
    run1_call_count = len(fake_sparql.calls)
    assert cli._cmd_extract(config) == 0

    calls = fake_sparql.calls
    run1_calls = calls[:run1_call_count]
    run2_calls = calls[run1_call_count:]

    run_activity_iris = set(re.findall(r"<urn:msr:run:extraction/[^>]+>", "\n".join(calls)))
    assert len(run_activity_iris) >= 2, f"expected >=2 distinct run activity IRIs, got: {calls}"

    def _measurement_data_call(call_list: list[str]) -> str:
        matches = [
            c for c in call_list if "a msr:PropertyMeasurement" in c and "GRAPH <urn:msr:data>" in c
        ]
        assert matches, f"expected a PropertyMeasurement data-graph write, got: {call_list}"
        return matches[0]

    assert _measurement_data_call(run1_calls) == _measurement_data_call(run2_calls)

    assert _row_count(config.db_path) == 1
