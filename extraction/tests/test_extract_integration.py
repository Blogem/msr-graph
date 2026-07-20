"""Guarded extract-pipeline integration test (task 8.11, design.md D2/D4-D8).

Mirrors ``test_link_integration.py``'s ``MSR_LINK_INTEGRATION`` opt-in
pattern (itself mirroring chunk 1's ``GRAPHDB_REQUIRED``/chunk 5's
``MSR_INGEST_INTEGRATION`` semantics): this module is skipped entirely
during normal/CI collection (no stack, no corpus, no network, no LLM
credentials) and only runs when explicitly opted into via the
``MSR_EXTRACT_INTEGRATION`` environment variable. Once opted in, the test
is a hard gate, not a soft one -- it FAILS (rather than skips) if the stack,
corpus, or SQLite store is unavailable, because passing here is the actual
acceptance criterion for chunk 7 (design.md D2/D4-D8, specs
``text-measurement-writing``/``relation-extraction``/
``salt-role-reactor-edges``/``measurement-store``).

How to run it
--------------
Bring up a seeded, catalogued, ingested, linked, SHACL-enabled stack and run
the full pipeline through ``extract`` first::

    make up && make load-nist && make ingest && make link && make extract

Then, from the repo root::

    MSR_EXTRACT_INTEGRATION=1 GRAPHDB_URL=http://localhost:7200 MSR_DB_PATH=./data/msr.db \\
        pytest extraction/tests/test_extract_integration.py

Any other ``GRAPHDB_*``/``MSR_*`` variables :class:`~msr_extraction.config.Config`
understands may also be set to point at a non-default stack/corpus/DB
location.

Note on heavy-dependency deferral: exactly like ``test_link_integration.py``
defers its chunk-6-only imports (and ``test_integration.py`` defers
``import httpx``) into the one function that needs them, this module defers
``httpx``, ``sqlite3``, and ``msr_extraction.cli`` imports into the test
bodies so the module COLLECTS cleanly (no live stack, no LLM credentials,
no on-disk DB required merely to *import* this file) even though its tests
are meant to be skipped by default.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("MSR_EXTRACT_INTEGRATION"),
    reason=(
        "guarded extract-pipeline integration test skipped: set "
        "MSR_EXTRACT_INTEGRATION=1 (after `make up && make load-nist && "
        "make ingest && make link && make extract`) to run it"
    ),
)

from msr_extraction.config import Config

MSR = "https://w3id.org/msr-kg/ontology#"
MSRD = "https://w3id.org/msr-kg/data#"

REPORT = "ORNL-TM-2316"
PROPERTY_LOCAL = "viscosity"

# The MSRE-coolant FLiBe individual minted by the chunk-2 NIST loader
# (design.md Context/D3), reused here as the expected ``msr:ofSalt`` target
# for the text-derived viscosity measurement over ORNL-TM-2316 -- mirrors
# ``test_link_integration.py``'s ``_COMPOSED_SALT_IRI``.
_SALT_IRI = f"{MSRD}salt-BeF2-LiF-34.0-66.0"

# Best-effort MSRE reactor individual (design.md D6, edges.py reactor_iri):
# only asserted if a linked MSRE-coolant mention is actually present, so a
# corpus/run that doesn't surface the reactor relation doesn't hard-fail
# this otherwise-authoritative test (see
# test_msre_reactor_individual_minted_if_linked).
_MSRE_REACTOR_IRI = f"{MSRD}reactor-msre"


def _sparql_select(config: Config, query: str) -> list[dict[str, dict[str, str]]]:
    """Run a SPARQL SELECT against the configured GraphDB repository.

    POSTs form-encoded ``query=`` to
    ``{graphdb_url}/repositories/{graphdb_repo}`` and returns the
    ``results.bindings`` list from the SPARQL JSON results response. Any
    connection error or non-2xx response is a hard failure (this module
    only runs when the caller has opted into requiring a live stack), not a
    skip. Mirrors ``test_link_integration.py``'s identical helper.
    """
    import httpx

    endpoint = f"{config.graphdb_url}/repositories/{config.graphdb_repo}"
    response = httpx.post(
        endpoint,
        data={"query": query},
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/sparql-results+json",
        },
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()["results"]["bindings"]


def _sparql_ask(config: Config, query: str) -> bool:
    """Run a SPARQL ASK against the configured GraphDB repository.

    Existence checks use ASK rather than ``SELECT (COUNT(*) …)`` over a
    fully-ground triple pattern (see ``test_integration.py``'s identical
    helper docstring): GraphDB returns 0 for a ground COUNT even when the
    triple exists, so ASK is the correct primitive here. Mirrors
    ``test_link_integration.py``'s identical helper.
    """
    import httpx

    endpoint = f"{config.graphdb_url}/repositories/{config.graphdb_repo}"
    response = httpx.post(
        endpoint,
        data={"query": query},
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/sparql-results+json",
        },
        timeout=30.0,
    )
    response.raise_for_status()
    return bool(response.json()["boolean"])


def _property_measurement_bindings(config: Config) -> list[dict[str, dict[str, str]]]:
    """SELECT the text-derived viscosity PropertyMeasurement(s) for REPORT.

    Queries by the exact ``?m a msr:PropertyMeasurement ; msr:citedIn
    msrd:ORNL-TM-2316 ; msr:forProperty msr:viscosity`` pattern the task
    contract specifies, additionally projecting ``msr:ofSalt``,
    ``msr:hasUnit``, ``msr:equationForm``, and ``msr:extractionConfidence``
    so a single query can support several assertions (design.md D5,
    ``measurements.py::measurement_triples``).
    """
    return _sparql_select(
        config,
        f"""
        PREFIX msr: <{MSR}>
        PREFIX msrd: <{MSRD}>
        PREFIX prov: <http://www.w3.org/ns/prov#>
        SELECT ?m ?salt ?unit ?equationForm ?confidence WHERE {{
            GRAPH <urn:msr:data> {{
                ?m a msr:PropertyMeasurement ;
                   msr:citedIn msrd:{REPORT} ;
                   msr:forProperty msr:{PROPERTY_LOCAL} ;
                   msr:ofSalt ?salt ;
                   msr:hasUnit ?unit ;
                   msr:equationForm ?equationForm ;
                   msr:extractionConfidence ?confidence ;
                   prov:wasGeneratedBy msrd:activity-extraction .
            }}
        }}
        """,
    )


def _run_extract_cli(config: Config) -> None:
    """Invoke ``python -m msr_extraction extract`` in-process against ``config``.

    Calls :func:`msr_extraction.cli.main` directly (rather than shelling out
    via ``subprocess``) so the second run reuses the exact same process
    environment (``GRAPHDB_URL``/``MSR_DB_PATH``/etc, already exported by
    the caller opting into this guarded test) without having to re-marshal
    it through a subprocess environment. ``cli.main`` re-derives its own
    ``Config.from_env()`` internally, so this only works correctly when the
    caller's process environment matches ``config`` -- true for every call
    site in this module.
    """
    from msr_extraction import cli

    exit_code = cli.main(["extract", "--report", REPORT])
    assert exit_code == 0, f"expected `extract --report {REPORT}` to exit 0, got {exit_code}"


def test_text_derived_viscosity_measurement_accepted_by_shacl() -> None:
    """A real `extract` run over ORNL-TM-2316 writes an accepted PropertyMeasurement.

    Pins specs/text-measurement-writing/spec.md's core acceptance scenario:
    after a real ``extract`` run, ``urn:msr:data`` contains a
    ``msr:PropertyMeasurement`` for ORNL-TM-2316's viscosity, carrying
    ``msr:citedIn``, ``prov:wasGeneratedBy msrd:activity-extraction``,
    ``msr:ofSalt`` the loaded MSRE-coolant FLiBe individual,
    ``msr:forProperty msr:viscosity``, an allowlisted ``msr:hasUnit``, an
    ``msr:equationForm``, and ``msr:extractionConfidence`` -- the seven
    required properties plus an allowlisted unit. Its mere presence proves
    the write was ACCEPTED by the SHACL-enabled ``msr`` repo (a shape
    violation would have made the underlying INSERT DATA fail instead).
    """
    config = Config.from_env()

    bindings = _property_measurement_bindings(config)
    assert bindings, (
        f"expected a text-derived msr:PropertyMeasurement for {REPORT}'s "
        f"{PROPERTY_LOCAL} in urn:msr:data -- run `make extract` first"
    )

    salt_iri = bindings[0]["salt"]["value"]
    assert salt_iri == _SALT_IRI, (
        f"expected the viscosity measurement's msr:ofSalt to be the loaded "
        f"MSRE-coolant salt {_SALT_IRI!r}, got {salt_iri!r}"
    )
    assert bindings[0]["unit"]["value"], "expected a non-empty msr:hasUnit"
    assert bindings[0]["equationForm"]["value"], "expected a non-empty msr:equationForm"
    assert bindings[0]["confidence"]["value"], "expected a non-empty msr:extractionConfidence"


def test_measurement_value_row_written_to_sqlite() -> None:
    """The corresponding `measurement_value` SQLite row exists after `extract`.

    Pins specs/measurement-store/spec.md's dual-write contract (design.md
    D5/D8): the same text-derived viscosity fact that landed in
    ``urn:msr:data`` (previous test) also has a `measurement_value` row in
    the SQLite store at ``config.db_path``, with ``source='document'``,
    ``doc_id='ORNL-TM-2316'``, ``property='viscosity'``.
    """
    import sqlite3

    config = Config.from_env()
    assert config.db_path.exists(), (
        f"expected the SQLite measurement store at {config.db_path} to "
        "exist -- run `make load-nist && make extract` first"
    )

    conn = sqlite3.connect(str(config.db_path))
    try:
        rows = conn.execute(
            "SELECT locator, salt, property, source, doc_id, equation_form, c0, c1 "
            "FROM measurement_value WHERE source = 'document' AND doc_id = ? "
            "AND property = ?",
            (REPORT, PROPERTY_LOCAL),
        ).fetchall()
    finally:
        conn.close()

    assert rows, (
        f"expected at least one measurement_value row with source='document', "
        f"doc_id={REPORT!r}, property={PROPERTY_LOCAL!r}"
    )
    locator, salt, property_, source, doc_id, equation_form, c0, c1 = rows[0]
    assert source == "document"
    assert doc_id == REPORT
    assert property_ == PROPERTY_LOCAL
    assert equation_form, "expected a non-empty equation_form"
    # Coefficients live only in SQLite (design.md D5) -- assert non-null
    # presence rather than hardcoding a value derived from the real corpus.
    assert c0 is not None
    assert c1 is not None
    assert locator.startswith(f"doc/{REPORT}/{PROPERTY_LOCAL}#")


def test_per_run_extraction_activity_present() -> None:
    """`urn:msr:provenance` contains at least one per-run extraction Activity node.

    Pins provenance-run-lineage design.md D1-D3 as applied to chunk 7's
    ``extract`` command (mirrors ``test_link_integration.py``'s equivalent
    coverage for ``link``): after a real ``extract`` run, at least one
    ``<urn:msr:run:extraction/...> a prov:Activity`` node exists in
    ``urn:msr:provenance``.
    """
    config = Config.from_env()

    present = _sparql_ask(
        config,
        """
        PREFIX prov: <http://www.w3.org/ns/prov#>
        ASK {
            GRAPH <urn:msr:provenance> {
                ?activity a prov:Activity .
                FILTER(STRSTARTS(STR(?activity), "urn:msr:run:extraction/"))
            }
        }
        """,
    )
    assert present, (
        "expected at least one urn:msr:run:extraction/... prov:Activity node "
        "in urn:msr:provenance"
    )


def test_second_extract_run_is_idempotent_in_data_and_sqlite() -> None:
    """Re-running `extract` leaves urn:msr:data/SQLite counts unchanged but appends a run activity.

    Pins design.md D4/D7's idempotency contract for the extract pipeline:
    deterministic measurement IRIs (locator-derived, no blank nodes) and a
    SQLite upsert-by-locator mean re-running ``extract`` over the same
    corpus is a set-semantics no-op in ``urn:msr:data`` and an
    upsert-in-place no-op in SQLite, while a second per-run
    ``urn:msr:run:extraction/...`` activity node still appears in
    ``urn:msr:provenance`` (each invocation gets its own timestamped run
    node, design.md D2-D3).
    """
    import sqlite3

    config = Config.from_env()
    assert config.db_path.exists(), (
        f"expected the SQLite measurement store at {config.db_path} to exist"
    )

    def _data_measurement_count() -> int:
        bindings = _sparql_select(
            config,
            f"""
            PREFIX msr: <{MSR}>
            SELECT (COUNT(*) AS ?count) WHERE {{
                GRAPH <urn:msr:data> {{
                    ?m a msr:PropertyMeasurement .
                }}
            }}
            """,
        )
        return int(bindings[0]["count"]["value"])

    def _sqlite_row_count() -> int:
        conn = sqlite3.connect(str(config.db_path))
        try:
            (count,) = conn.execute(
                "SELECT COUNT(*) FROM measurement_value WHERE source = 'document'"
            ).fetchone()
        finally:
            conn.close()
        return int(count)

    def _run_activity_count() -> int:
        bindings = _sparql_select(
            config,
            """
            PREFIX prov: <http://www.w3.org/ns/prov#>
            SELECT (COUNT(*) AS ?count) WHERE {
                GRAPH <urn:msr:provenance> {
                    ?activity a prov:Activity .
                    FILTER(STRSTARTS(STR(?activity), "urn:msr:run:extraction/"))
                }
            }
            """,
        )
        return int(bindings[0]["count"]["value"])

    before_data = _data_measurement_count()
    before_sqlite = _sqlite_row_count()
    before_runs = _run_activity_count()

    _run_extract_cli(config)

    after_data = _data_measurement_count()
    after_sqlite = _sqlite_row_count()
    after_runs = _run_activity_count()

    assert after_data == before_data, (
        f"expected urn:msr:data PropertyMeasurement count to be unchanged after "
        f"a repeat extract run, was {before_data} then {after_data}"
    )
    assert after_sqlite == before_sqlite, (
        f"expected measurement_value row count to be unchanged after a repeat "
        f"extract run, was {before_sqlite} then {after_sqlite}"
    )
    assert after_runs > before_runs, (
        "expected an additional urn:msr:run:extraction/... activity node after "
        f"a second extract run, was {before_runs} then {after_runs}"
    )


def test_msre_reactor_individual_minted_if_linked() -> None:
    """Best-effort: a minted msr:MoltenSaltReactor exists if MSRE coolant was linked.

    Pins specs/salt-role-reactor-edges/spec.md's reactor-minting scenario
    (design.md D6, ``edges.py::reactor_iri``/``write_edges``), but stays
    tolerant of a corpus/run that doesn't surface an MSRE-salt "used in"
    relation: this test only asserts the reactor individual's existence if
    at least one msr:Mention already links to the MSRE reactor concept
    (i.e. the linked precondition for the reactor-minting relation is
    actually present in this run's urn:msr:data). If that precondition is
    absent, the test passes trivially rather than hard-failing on a corpus
    variation outside this test's control.
    """
    config = Config.from_env()

    msre_mention_linked = _sparql_ask(
        config,
        """
        PREFIX msr: <https://w3id.org/msr-kg/ontology#>
        PREFIX voc: <https://w3id.org/msr-kg/vocab#>
        ASK {
            GRAPH <urn:msr:data> {
                ?m a msr:Mention ;
                   msr:linksTo voc:msre-reactor .
            }
        }
        """,
    )
    if not msre_mention_linked:
        pytest.skip(
            "no msr:Mention links to voc:msre-reactor in this run -- "
            "reactor-minting precondition not present, skipping tolerant check"
        )

    reactor_present = _sparql_ask(
        config,
        f"""
        PREFIX msr: <{MSR}>
        ASK {{
            GRAPH <urn:msr:data> {{
                <{_MSRE_REACTOR_IRI}> a msr:MoltenSaltReactor .
            }}
        }}
        """,
    )
    assert reactor_present, (
        f"expected a minted msr:MoltenSaltReactor individual <{_MSRE_REACTOR_IRI}> "
        "in urn:msr:data given a linked MSRE-coolant mention is present"
    )
