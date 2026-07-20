"""Pin tests for the ``mine_provenance`` module (openspec/changes/
mine-ontology-candidates, design.md D8, task 6.3).

Unlike the other pass-1 test files in this wave, ``mine_provenance.py`` is
a Wave-1 shared module and already landed on this branch (merged from
``worktree-mine-ontology-candidates`` before this suite was written) -- so
these tests exercise real, already-implemented code, not a stub written
against a not-yet-existing contract. They mirror
``test_provenance.py``'s structure but pin the ``mine`` pipeline identity
(``msrd:activity-mine`` / ``agent:mine@<version>`` / ``urn:msr:run:mine/<ts>``)
instead of the extraction pipeline's.
"""

from __future__ import annotations

from msr_extraction.mine_provenance import (
    ACTIVITY_IRI,
    AGENT_IRI,
    MINE_VERSION,
    activity_insert_data,
    generation_edges_insert_data,
    run_activity_iri,
    stable_activity_insert_data,
    write_activity,
    write_generation_edges,
    write_stable_activity,
)

RUN_TS = "2026-07-20T00:00:00+00:00"
OTHER_RUN_TS = "2026-07-21T00:00:00+00:00"


class _FakeSparqlClient:
    """Captures ``.update(...)`` calls; never touches the network."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def update(self, sparql_update: str) -> None:
        self.calls.append(sparql_update)


def test_activity_iri_and_agent_iri_identify_the_mine_pipeline() -> None:
    assert ACTIVITY_IRI == "msrd:activity-mine"
    assert AGENT_IRI == f"<agent:mine@{MINE_VERSION}>"


def test_run_activity_iri_is_bracketed_and_namespaced_under_mine() -> None:
    assert run_activity_iri(RUN_TS) == f"<urn:msr:run:mine/{RUN_TS}>"


def test_activity_insert_data_targets_provenance_graph_and_is_fully_attributed() -> None:
    update = activity_insert_data(RUN_TS)
    assert "GRAPH <urn:msr:provenance>" in update
    assert f"<urn:msr:run:mine/{RUN_TS}> a prov:Activity" in update
    assert f"prov:wasAssociatedWith {AGENT_IRI}" in update
    assert "prov:startedAtTime" in update
    assert "prov:endedAtTime" in update
    assert "owl:versionInfo" in update


def test_activity_insert_data_distinct_run_ts_yields_distinct_subject() -> None:
    first = activity_insert_data(RUN_TS)
    second = activity_insert_data(OTHER_RUN_TS)
    assert f"urn:msr:run:mine/{RUN_TS}" in first
    assert f"urn:msr:run:mine/{RUN_TS}" not in second
    assert f"urn:msr:run:mine/{OTHER_RUN_TS}" in second
    assert f"urn:msr:run:mine/{OTHER_RUN_TS}" not in first


def test_activity_insert_data_is_deterministic_for_the_same_run_ts() -> None:
    assert activity_insert_data(RUN_TS) == activity_insert_data(RUN_TS)


def test_stable_activity_insert_data_targets_data_graph_with_no_timestamps() -> None:
    """Scenario: "The stable mine activity is typed idempotently in the
    data graph"."""
    update = stable_activity_insert_data()
    assert "GRAPH <urn:msr:data>" in update
    assert f"{ACTIVITY_IRI} a prov:Activity" in update
    assert f"prov:wasAssociatedWith {AGENT_IRI}" in update
    assert "owl:versionInfo" in update
    assert "prov:startedAtTime" not in update
    assert "prov:endedAtTime" not in update
    assert "xsd:dateTime" not in update


def test_stable_activity_insert_data_is_deterministic() -> None:
    assert stable_activity_insert_data() == stable_activity_insert_data()


def test_generation_edges_insert_data_sorted_and_targets_provenance_graph() -> None:
    """Scenario: "Per-run activity and lineage land in the provenance
    graph" -- one prov:wasGeneratedBy edge per fact, sorted for
    determinism."""
    update = generation_edges_insert_data(["msrd:b", "msrd:a"], RUN_TS)
    assert "GRAPH <urn:msr:provenance>" in update
    assert update.index("msrd:a") < update.index("msrd:b")
    assert update.count(f"<urn:msr:run:mine/{RUN_TS}>") == 2


def test_generation_edges_insert_data_is_deterministic() -> None:
    first = generation_edges_insert_data(["msrd:a", "msrd:b"], RUN_TS)
    second = generation_edges_insert_data(["msrd:b", "msrd:a"], RUN_TS)  # reversed input order
    assert first == second


def test_write_generation_edges_is_a_noop_when_empty() -> None:
    client = _FakeSparqlClient()
    write_generation_edges([], RUN_TS, client)
    assert client.calls == []


def test_write_generation_edges_sends_one_update_when_non_empty() -> None:
    client = _FakeSparqlClient()
    write_generation_edges(["msrd:x"], RUN_TS, client)
    assert len(client.calls) == 1
    assert "GRAPH <urn:msr:provenance>" in client.calls[0]


def test_write_activity_sends_exactly_one_update() -> None:
    client = _FakeSparqlClient()
    write_activity(RUN_TS, client)
    assert len(client.calls) == 1
    assert "GRAPH <urn:msr:provenance>" in client.calls[0]
    assert f"urn:msr:run:mine/{RUN_TS}" in client.calls[0]


def test_write_stable_activity_sends_exactly_one_update() -> None:
    client = _FakeSparqlClient()
    write_stable_activity(client)
    assert len(client.calls) == 1
    assert "GRAPH <urn:msr:data>" in client.calls[0]
    assert f"{ACTIVITY_IRI} a prov:Activity" in client.calls[0]
