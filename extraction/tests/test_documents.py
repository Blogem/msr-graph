"""Document-emission tests (task 9.5, design.md D6).

Pins the exact ``Document`` triple shape (deterministic IRI, no blank
nodes) and the ``INSERT DATA { GRAPH <urn:msr:data> { ... } } `` wrapper
(with required PREFIX declarations), against a fixed ``ManifestRecord``.
Comparisons collapse runs of whitespace so exact indentation in the
implementation isn't brittle. ``write_documents`` is exercised against a
fake SPARQL client that only records ``.update(...)`` calls (no network).
"""

from __future__ import annotations

import re

from msr_extraction.documents import document_triples, insert_data_update, write_documents
from msr_extraction.manifest import ManifestRecord


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


RECORD = ManifestRecord(
    report_number="ORNL-TM-2316",
    title="Physical Properties of Molten-Salt Reactor Fuel, Coolant, and Flush Salts",
    date="1968-11-01",
    ocr_path="ocr/ORNL-TM-2316.txt",
)

# A title with an embedded double quote, to pin literal escaping.
QUOTED_RECORD = ManifestRecord(
    report_number="ORNL-TM-0728",
    title='MSRE Design and Operations Report Part I: "Reactor Design"',
    date="1965-01-01",
    ocr_path="ocr/ORNL-TM-0728.txt",
)

# openspec/changes/provenance-run-lineage: the run timestamp threaded into
# write_documents' per-run generation edges (task 5.7).
RUN_TS = "2024-01-02T03:04:05+00:00"
OTHER_RUN_TS = "2024-06-07T08:09:10+00:00"


class _FakeSparqlClient:
    """Captures ``.update(...)`` calls; never touches the network."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def update(self, sparql_update: str) -> None:
        self.calls.append(sparql_update)


def test_document_triples_contains_deterministic_iri_and_fields() -> None:
    triples = _collapse_ws(document_triples(RECORD))
    assert "msrd:ORNL-TM-2316" in triples
    assert (
        'rdfs:label "Physical Properties of Molten-Salt Reactor Fuel, '
        'Coolant, and Flush Salts"' in triples
    )
    assert 'dcterms:identifier "ORNL-TM-2316"' in triples
    assert 'dcterms:date "1968-11-01"' in triples


def test_document_triples_has_no_blank_nodes() -> None:
    triples = document_triples(RECORD)
    assert "[" not in triples
    assert "_:" not in triples


def test_document_triples_escapes_embedded_quotes() -> None:
    triples = document_triples(QUOTED_RECORD)
    assert '\\"Reactor Design\\"' in triples
    # An unescaped embedded quote would break out of the label literal.
    assert 'rdfs:label "MSRE Design and Operations Report Part I: "Reactor' not in triples


def test_insert_data_update_wraps_graph_and_prefixes() -> None:
    update = _collapse_ws(insert_data_update([RECORD]))
    assert "INSERT DATA" in update
    assert "GRAPH <urn:msr:data>" in update
    assert "PREFIX msr:" in update
    assert "PREFIX msrd:" in update
    assert "PREFIX rdfs:" in update
    assert "PREFIX dcterms:" in update
    assert "msrd:ORNL-TM-2316" in update


def test_write_documents_sends_zero_updates_for_empty_records() -> None:
    client = _FakeSparqlClient()
    write_documents([], client, RUN_TS)
    assert len(client.calls) == 0


# --- openspec/changes/provenance-model additions (task 6.6) ----------------
#
# spec "document-graph" ADDED requirement "Document nodes carry generation
# provenance": each written msr:Document SHALL carry prov:wasGeneratedBy
# the deterministic msrd:activity-extraction Activity IRI (design D6).


def test_document_triples_carries_generation_provenance() -> None:
    """Covers the "Document node references the ingest activity" scenario:
    the node carries prov:wasGeneratedBy msrd:activity-extraction alongside
    its report number, title, and date."""
    triples = _collapse_ws(document_triples(RECORD))
    assert "prov:wasGeneratedBy msrd:activity-extraction" in triples
    # The manifest-sourced metadata (already pinned above) must survive
    # alongside the new edge, not be replaced by it.
    assert 'dcterms:identifier "ORNL-TM-2316"' in triples


def test_document_triples_generation_edge_is_deterministic_across_calls() -> None:
    """Covers the "Generation edge preserves idempotency" scenario: because
    the document IRI and the referenced msrd:activity-extraction IRI are
    both deterministic, re-emitting the same record's triples twice is
    byte-identical (a set-semantics no-op on re-run)."""
    first = document_triples(RECORD)
    second = document_triples(RECORD)
    assert first == second
    assert "prov:wasGeneratedBy msrd:activity-extraction" in first


# --- openspec/changes/provenance-run-lineage additions (task 5.7) ----------
#
# write_documents gains a run_ts parameter (task 3.3/3.4) and now sends TWO
# updates via the client for a non-empty record list: (1) the existing
# urn:msr:data INSERT DATA -- unchanged, still carrying each document's
# stable prov:wasGeneratedBy msrd:activity-extraction edge -- and (2) a new
# urn:msr:provenance INSERT DATA carrying one
# <document> prov:wasGeneratedBy <urn:msr:run:extraction/<run_ts>> per-run
# generation edge per written document. No read-before-write: every record
# in the input list gets a generation edge (design D3 "touched" semantics).
#
# ASSUMPTION (pass-1, flagged for reconciliation at merge): this pins
# write_documents(records, client, run_ts) sending exactly two client.update
# calls in the order [urn:msr:data, urn:msr:provenance] for a non-empty
# record list -- mirroring the write_mentions contract in
# tests/test_mentions.py. If the coder's task-3.3 change lands with a
# different call shape, this needs reconciling at merge, not the acceptance
# intent it encodes.


def test_write_documents_sends_two_updates_for_nonempty_records() -> None:
    client = _FakeSparqlClient()
    write_documents([RECORD], client, RUN_TS)
    assert len(client.calls) == 2


def test_write_documents_first_update_is_the_unchanged_data_graph_write() -> None:
    """The urn:msr:data update -- and the document's stable
    prov:wasGeneratedBy msrd:activity-extraction edge inside it -- is
    unchanged by the run_ts addition."""
    client = _FakeSparqlClient()
    write_documents([RECORD], client, RUN_TS)
    data_update = _collapse_ws(client.calls[0])
    assert "GRAPH <urn:msr:data>" in data_update
    assert "msrd:ORNL-TM-2316" in data_update
    assert "prov:wasGeneratedBy msrd:activity-extraction" in data_update


def test_write_documents_second_update_carries_per_run_generation_edge() -> None:
    """Covers 5.7: the written document IRI gets a
    prov:wasGeneratedBy <urn:msr:run:extraction/<run_ts>> edge in a
    urn:msr:provenance update."""
    client = _FakeSparqlClient()
    write_documents([RECORD], client, RUN_TS)
    prov_update = _collapse_ws(client.calls[1])
    assert "GRAPH <urn:msr:provenance>" in prov_update
    assert (
        f"msrd:ORNL-TM-2316 prov:wasGeneratedBy <urn:msr:run:extraction/{RUN_TS}>"
        in prov_update
    )


def test_write_documents_distinct_run_ts_yields_distinct_generation_edges() -> None:
    """Two invocations at distinct run_ts values append disjoint per-run
    generation edges -- urn:msr:provenance is append-only (design D2/D4)."""
    client_a = _FakeSparqlClient()
    write_documents([RECORD], client_a, RUN_TS)
    client_b = _FakeSparqlClient()
    write_documents([RECORD], client_b, OTHER_RUN_TS)

    assert f"urn:msr:run:extraction/{RUN_TS}" in client_a.calls[1]
    assert f"urn:msr:run:extraction/{OTHER_RUN_TS}" not in client_a.calls[1]
    assert f"urn:msr:run:extraction/{OTHER_RUN_TS}" in client_b.calls[1]
    assert f"urn:msr:run:extraction/{RUN_TS}" not in client_b.calls[1]


def test_write_documents_data_graph_update_is_idempotent_across_run_ts() -> None:
    """The urn:msr:data update does not depend on run_ts at all, so two
    runs at distinct run_ts values still produce a byte-identical
    urn:msr:data write (only urn:msr:provenance grows)."""
    client_a = _FakeSparqlClient()
    write_documents([RECORD], client_a, RUN_TS)
    client_b = _FakeSparqlClient()
    write_documents([RECORD], client_b, OTHER_RUN_TS)
    assert client_a.calls[0] == client_b.calls[0]
