"""Extraction-run provenance tests (openspec/changes/provenance-model, tasks
6.6/6.7, design D6).

Pins the shared provenance helper's Activity-record builder/writer: the
deterministic ``msrd:activity-extraction`` Activity IRI, the timestamped
run named graph ``urn:msr:run:extraction/<ts>``, and the required
``prov:wasAssociatedWith agent:extraction@<version>`` /
``prov:startedAtTime`` / ``prov:endedAtTime`` / ``owl:versionInfo``
attribution (design D2, D6; spec "provenance-model" ADDED requirement
"Generating activities record agent, timestamps, and ontology version" and
"Per-source and per-run named graphs carry an Activity record").

ASSUMPTION (pass-1, flagged in the tester handoff report for
reconciliation at merge): this targets a new ``msr_extraction.provenance``
module exposing ``activity_insert_data(run_ts: str) -> str`` (the pure
Turtle/SPARQL builder, mirroring ``mentions.insert_data`` /
``documents.insert_data_update``'s existing shape) and
``write_activity(run_ts: str, client: SparqlClient) -> None`` (the network
call, mirroring ``mentions.write_mentions`` / ``documents.write_documents``).
This module does not exist yet on this isolated pass-1 branch; every test
below is expected to fail at collection (ImportError) until the coder's
task-3.1 provenance helper lands.
"""

from __future__ import annotations

import re

from msr_extraction.provenance import activity_insert_data, write_activity

RUN_TS = "2024-01-02T03-04-05Z"


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class _FakeSparqlClient:
    """Captures ``.update(...)`` calls; never touches the network."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def update(self, sparql_update: str) -> None:
        self.calls.append(sparql_update)


def test_activity_insert_data_targets_the_timestamped_run_graph() -> None:
    update = _collapse_ws(activity_insert_data(RUN_TS))
    assert "INSERT DATA" in update
    assert f"GRAPH <urn:msr:run:extraction/{RUN_TS}>" in update


def test_activity_insert_data_is_fully_attributed() -> None:
    """Covers the "An extraction-run activity is fully attributed" scenario:
    the Activity carries prov:wasAssociatedWith agent:extraction@<version>,
    start/end timestamps, and the ontology owl:versionInfo.
    """
    update = _collapse_ws(activity_insert_data(RUN_TS))
    assert "a prov:Activity" in update
    assert "msrd:activity-extraction" in update
    assert "prov:wasAssociatedWith <agent:extraction@" in update
    assert "prov:startedAtTime" in update
    assert "prov:endedAtTime" in update
    assert "owl:versionInfo" in update


def test_activity_insert_data_writes_exactly_one_activity_record() -> None:
    """Covers 6.6's "exactly one prov:Activity record is written ... per
    run": the builder must not emit more than one Activity typing triple
    for a single run_ts.
    """
    update = activity_insert_data(RUN_TS)
    assert update.count("a prov:Activity") == 1


def test_activity_insert_data_is_deterministic_for_the_same_run_ts() -> None:
    first = activity_insert_data(RUN_TS)
    second = activity_insert_data(RUN_TS)
    assert first == second


def test_write_activity_sends_exactly_one_update() -> None:
    client = _FakeSparqlClient()
    write_activity(RUN_TS, client)
    assert len(client.calls) == 1
    assert "msrd:activity-extraction" in client.calls[0]
    assert f"urn:msr:run:extraction/{RUN_TS}" in client.calls[0]
