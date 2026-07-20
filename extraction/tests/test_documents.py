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


def test_write_documents_sends_exactly_one_update_for_nonempty_records() -> None:
    client = _FakeSparqlClient()
    write_documents([RECORD], client)
    assert len(client.calls) == 1
    assert "INSERT DATA" in client.calls[0]
    assert "msrd:ORNL-TM-2316" in client.calls[0]


def test_write_documents_sends_zero_updates_for_empty_records() -> None:
    client = _FakeSparqlClient()
    write_documents([], client)
    assert len(client.calls) == 0


# --- openspec/changes/provenance-model additions (task 6.6) ----------------
#
# spec "document-graph" ADDED requirement "Document nodes carry generation
# provenance": each written msr:Document SHALL carry prov:wasGeneratedBy
# the deterministic msrd:activity-extraction Activity IRI (design D6).
# These tests are written against that requirement and are expected to
# fail on this isolated pass-1 branch until the coder's task-3.3 change to
# documents.py lands (document_triples does not yet emit this edge).


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
