"""Attributed safety-Document node tests (openspec/changes/ingest-iaea-safety,
spec ``safety-source-acquisition``, "Attributed Document provenance nodes"
requirement).

Mirrors ``test_documents.py``'s existing chemistry-genre coverage
(``document_triples``/``write_documents``) for the safety-genre variant,
pinned in the tester's task contract: ``documents.safety_document_triples(source)
-> str`` and ``documents.write_safety_documents(sources, client, run_ts)``.
Exercised against a fake SPARQL client that only records ``.update(...)``
calls -- no network.

ASSUMPTION (pass-1, flagged for reconciliation at merge): these two
functions do not exist yet on this isolated pass-1 branch -- expected to
fail with a collection error until the coder's ``documents.py`` change
lands. Modeled closely on ``document_triples``'s existing shape (subject
``msrd:{id}``, ``rdfs:label``, ``dcterms:identifier``, ``dcterms:date``,
``prov:wasGeneratedBy msrd:activity-extraction``) plus the four
safety-specific attribution predicates the spec requires
(``dcterms:publisher``, ``dcterms:rights``, ``dcterms:source``). Whether
a safety Document ALSO carries ``prov:wasDerivedFrom`` (the spec's
"established provenance edges (prov:wasDerivedFrom/prov:wasGeneratedBy)"
phrasing is ambiguous given the existing chemistry Document is a
derivation root with no ``wasDerivedFrom``) is deliberately left
unasserted either way here -- flagged as an open question in the tester
handoff report rather than pinned as a MUST/MUST NOT.
"""

from __future__ import annotations

import re

from msr_extraction.documents import safety_document_triples, write_safety_documents
from msr_extraction.safety_manifest import SafetySource

SOURCE = SafetySource(
    id="TEST-SRS-123",
    title="Test IAEA Safety Requirements",
    publisher="International Atomic Energy Agency",
    rights="(c) IAEA. Short excerpt used for testing under fair use.",
    url="https://www-pub.iaea.org/example/test-srs-123",
    date="2027",
    pdf_filename="test-srs-123.pdf",
    page_ranges=[(2, 3)],
    sections=["Test Section"],
)

QUOTED_SOURCE = SafetySource(
    id="TEST-GIF-Holcomb",
    title='Test GIF Report: "MSR Safety Analysis"',
    publisher="Generation IV International Forum",
    rights='(c) GIF. Short excerpt used for testing under fair use.',
    url="https://www.gen-4.org/example/test-gif-holcomb",
    date="2019",
    pdf_filename="test-gif-holcomb.pdf",
    page_ranges=None,
    sections=[],
)

RUN_TS = "2026-07-21T00:00:00+00:00"
OTHER_RUN_TS = "2026-08-01T00:00:00+00:00"


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class _FakeSparqlClient:
    """Captures ``.update(...)`` calls; never touches the network."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def update(self, sparql_update: str) -> None:
        self.calls.append(sparql_update)


# --- Document node carries mandatory attribution ----------------------------


def test_safety_document_triples_carries_mandatory_attribution() -> None:
    """Scenario: "Document node carries mandatory attribution" -- the
    written node carries a non-empty dcterms:publisher, dcterms:rights, and
    a resolvable dcterms:source URL, in addition to the standard document
    metadata and generation provenance."""
    triples = _collapse_ws(safety_document_triples(SOURCE))

    assert "msrd:TEST-SRS-123" in triples
    assert 'rdfs:label "Test IAEA Safety Requirements"' in triples
    assert 'dcterms:identifier "TEST-SRS-123"' in triples
    assert 'dcterms:date "2027"' in triples
    assert 'dcterms:publisher "International Atomic Energy Agency"' in triples
    assert "dcterms:rights" in triples
    assert "IAEA" in triples  # the rights statement text survives
    assert "dcterms:source <https://www-pub.iaea.org/example/test-srs-123>" in triples
    assert "prov:wasGeneratedBy msrd:activity-extraction" in triples


def test_safety_document_triples_has_no_blank_nodes() -> None:
    triples = safety_document_triples(SOURCE)
    assert "[" not in triples
    assert "_:" not in triples


def test_safety_document_triples_escapes_embedded_quotes() -> None:
    triples = safety_document_triples(QUOTED_SOURCE)
    assert '\\"MSR Safety Analysis\\"' in triples
    assert 'rdfs:label "Test GIF Report: "MSR' not in triples


def test_safety_document_triples_are_deterministic_across_calls() -> None:
    """Re-emitting the same source's triples twice is byte-identical (a
    set-semantics no-op on re-run, design.md D2)."""
    assert safety_document_triples(SOURCE) == safety_document_triples(SOURCE)


# --- Re-running acquisition is idempotent -----------------------------------


def test_write_safety_documents_sends_zero_updates_for_empty_sources() -> None:
    client = _FakeSparqlClient()
    write_safety_documents([], client, RUN_TS)
    assert len(client.calls) == 0


def test_write_safety_documents_sends_two_updates_for_nonempty_sources() -> None:
    """Mirrors ``write_documents``'s two-update contract (data + per-run
    provenance), design.md D2/D6."""
    client = _FakeSparqlClient()
    write_safety_documents([SOURCE], client, RUN_TS)
    assert len(client.calls) == 2


def test_write_safety_documents_first_update_targets_the_data_graph() -> None:
    client = _FakeSparqlClient()
    write_safety_documents([SOURCE], client, RUN_TS)
    data_update = _collapse_ws(client.calls[0])
    assert "GRAPH <urn:msr:data>" in data_update
    assert "msrd:TEST-SRS-123" in data_update
    assert "dcterms:publisher" in data_update


def test_write_safety_documents_second_update_targets_the_provenance_graph() -> None:
    """Scenario: "Re-running acquisition is idempotent in the data graph"
    -- the second update is the per-run generation edge into
    urn:msr:provenance (urn:msr:data itself never depends on run_ts)."""
    client = _FakeSparqlClient()
    write_safety_documents([SOURCE], client, RUN_TS)
    prov_update = _collapse_ws(client.calls[1])
    assert "GRAPH <urn:msr:provenance>" in prov_update
    assert f"msrd:TEST-SRS-123 prov:wasGeneratedBy <urn:msr:run:extraction/{RUN_TS}>" in prov_update


def test_write_safety_documents_data_graph_update_is_idempotent_across_run_ts() -> None:
    """Two runs at distinct run_ts values produce a byte-identical
    urn:msr:data write -- only urn:msr:provenance grows across runs."""
    client_a = _FakeSparqlClient()
    write_safety_documents([SOURCE], client_a, RUN_TS)
    client_b = _FakeSparqlClient()
    write_safety_documents([SOURCE], client_b, OTHER_RUN_TS)
    assert client_a.calls[0] == client_b.calls[0]
