"""Extraction-run provenance tests (openspec/changes/provenance-run-lineage,
task 5.6, design D1/D2).

Pins the per-run provenance Activity builder: ``activity_insert_data(run_ts)``
now targets ``GRAPH <urn:msr:provenance>`` (replacing the archived
provenance-model's per-run named graph ``urn:msr:run:extraction/<ts>``),
with the per-run Activity node ``<urn:msr:run:extraction/<run_ts>>`` as the
SUBJECT typed ``a prov:Activity`` -- the run identifier survives only as a
*node* IRI now, not a graph name (design D1/D2). It carries
``prov:wasAssociatedWith agent:extraction@<version>``,
``prov:startedAtTime``/``prov:endedAtTime``, and ``owl:versionInfo``.
Distinct ``run_ts`` values must mint distinct subjects, so two runs'
provenance never collide.

ASSUMPTION (pass-1, flagged in the tester handoff report for
reconciliation at merge): the ``activity_insert_data(run_ts: str) -> str`` /
``write_activity(run_ts: str, client: SparqlClient) -> None`` signatures are
unchanged from the archived provenance-model change; only the GRAPH target
(``urn:msr:provenance`` instead of a per-run graph) and the Activity
subject (the per-run node, not ``msrd:activity-extraction``) change. These
tests are expected to fail on this isolated pass-1 branch until the coder's
task-3.1 change to ``provenance.py`` lands.
"""

from __future__ import annotations

import re

from msr_extraction.provenance import activity_insert_data, write_activity

RUN_TS = "2024-01-02T03:04:05+00:00"
OTHER_RUN_TS = "2024-06-07T08:09:10+00:00"


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class _FakeSparqlClient:
    """Captures ``.update(...)`` calls; never touches the network."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def update(self, sparql_update: str) -> None:
        self.calls.append(sparql_update)


def test_activity_insert_data_targets_the_provenance_graph() -> None:
    """Covers 5.6: activity_insert_data(run_ts) targets
    GRAPH <urn:msr:provenance> (not a per-run named graph)."""
    update = _collapse_ws(activity_insert_data(RUN_TS))
    assert "INSERT DATA" in update
    assert "GRAPH <urn:msr:provenance>" in update


def test_activity_insert_data_does_not_target_a_per_run_graph() -> None:
    """The per-run named graph the archived provenance-model change used
    (``GRAPH <urn:msr:run:extraction/<run_ts>>``) must not appear -- the run
    identifier is a node inside urn:msr:provenance now, not a graph name."""
    update = activity_insert_data(RUN_TS)
    assert f"GRAPH <urn:msr:run:extraction/{RUN_TS}>" not in update


def test_activity_insert_data_subject_is_the_per_run_activity_node() -> None:
    """Covers 5.6: subject <urn:msr:run:extraction/<run_ts>> typed
    a prov:Activity inside GRAPH <urn:msr:provenance> -- the run identifier
    is a node, not a graph name (design D1/D2)."""
    update = _collapse_ws(activity_insert_data(RUN_TS))
    assert f"<urn:msr:run:extraction/{RUN_TS}> a prov:Activity" in update


def test_activity_insert_data_is_fully_attributed() -> None:
    """Covers the "A per-run activity is fully attributed in the
    provenance graph" scenario: the per-run Activity carries
    prov:wasAssociatedWith agent:extraction@<version>, start/end
    timestamps, and the ontology owl:versionInfo.
    """
    update = _collapse_ws(activity_insert_data(RUN_TS))
    assert "a prov:Activity" in update
    assert "prov:wasAssociatedWith <agent:extraction@" in update
    assert "prov:startedAtTime" in update
    assert "prov:endedAtTime" in update
    assert "owl:versionInfo" in update


def test_activity_insert_data_writes_exactly_one_activity_record() -> None:
    """The builder must not emit more than one Activity typing triple for a
    single run_ts."""
    update = activity_insert_data(RUN_TS)
    assert update.count("a prov:Activity") == 1


def test_activity_insert_data_is_deterministic_for_the_same_run_ts() -> None:
    first = activity_insert_data(RUN_TS)
    second = activity_insert_data(RUN_TS)
    assert first == second


def test_activity_insert_data_distinct_run_ts_yields_distinct_subject() -> None:
    """Covers 5.6's "distinct run_ts -> distinct subject": two different
    run timestamps must mint two different per-run Activity node IRIs, so
    two runs' provenance records never collide on the same subject."""
    first = activity_insert_data(RUN_TS)
    second = activity_insert_data(OTHER_RUN_TS)
    assert f"<urn:msr:run:extraction/{RUN_TS}>" in first
    assert f"<urn:msr:run:extraction/{RUN_TS}>" not in second
    assert f"<urn:msr:run:extraction/{OTHER_RUN_TS}>" in second
    assert f"<urn:msr:run:extraction/{OTHER_RUN_TS}>" not in first


def test_write_activity_sends_exactly_one_update() -> None:
    client = _FakeSparqlClient()
    write_activity(RUN_TS, client)
    assert len(client.calls) == 1
    assert "GRAPH <urn:msr:provenance>" in client.calls[0]
    assert f"urn:msr:run:extraction/{RUN_TS}" in client.calls[0]
