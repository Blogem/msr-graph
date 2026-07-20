"""Mention-emission tests (task 10.7, design.md D7, D8).

Pins the exact ``Mention`` triple shape (deterministic IRI, no blank
nodes), the ``INSERT DATA { GRAPH <urn:msr:data> { ... } } `` wrapper
(with required PREFIX declarations), surface-form literal escaping, and
``write_mentions`` idempotent-shape re-emission against a fake SPARQL
client (no network).
"""

from __future__ import annotations

import re

from msr_extraction.mentions import (
    Mention,
    insert_data,
    mention_iri,
    mention_triples,
    write_mentions,
)


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


SALT_IRI = "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"
DOCUMENT_IRI = "https://w3id.org/msr-kg/data#ORNL-TM-2316"

MENTION = Mention(
    report="ORNL-TM-2316",
    start=10,
    end=18,
    surface_form="LiF-BeF2",
    target_iri=SALT_IRI,
    document_iri=DOCUMENT_IRI,
)

# A surface form with an embedded double quote and a backslash, to pin
# literal escaping.
QUOTED_MENTION = Mention(
    report="ORNL-TM-2316",
    start=100,
    end=110,
    surface_form='Li"F\\BeF2',
    target_iri=SALT_IRI,
    document_iri=DOCUMENT_IRI,
)


class _FakeSparqlClient:
    """Captures ``.update(...)`` calls; never touches the network."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def update(self, sparql_update: str) -> None:
        self.calls.append(sparql_update)


def test_mention_iri_is_deterministic() -> None:
    assert mention_iri("ORNL-TM-2316", 10, 18) == "msrd:mention-ORNL-TM-2316-10-18"


def test_mention_triples_exact_shape() -> None:
    expected = (
        "msrd:mention-ORNL-TM-2316-10-18 a msr:Mention ;\n"
        f"    msr:linksTo <{SALT_IRI}> ;\n"
        f"    msr:inDocument <{DOCUMENT_IRI}> ;\n"
        '    msr:surfaceForm "LiF-BeF2"^^xsd:string ;\n'
        '    msr:startOffset "10"^^xsd:integer ;\n'
        '    msr:endOffset "18"^^xsd:integer ;\n'
        "    prov:wasGeneratedBy msrd:activity-extraction ;\n"
        f"    prov:wasDerivedFrom <{DOCUMENT_IRI}> ."
    )
    assert mention_triples(MENTION) == expected


def test_mention_triples_has_no_blank_nodes() -> None:
    triples = mention_triples(MENTION)
    assert "[" not in triples
    assert "_:" not in triples


def test_mention_triples_escapes_surface_form() -> None:
    triples = mention_triples(QUOTED_MENTION)
    assert '\\"' in triples
    assert "\\\\" in triples
    # An unescaped embedded quote/backslash would break out of the literal.
    assert 'msr:surfaceForm "Li"F\\BeF2"^^xsd:string' not in triples


def test_insert_data_wraps_graph_and_prefixes() -> None:
    update = _collapse_ws(insert_data(mention_triples(MENTION)))
    assert "INSERT DATA" in update
    assert "GRAPH <urn:msr:data>" in update
    assert "PREFIX msr:" in update
    assert "PREFIX msrd:" in update
    assert "PREFIX xsd:" in update
    assert "msrd:mention-ORNL-TM-2316-10-18" in update


def test_write_mentions_sends_exactly_one_update_for_nonempty_mentions() -> None:
    client = _FakeSparqlClient()
    write_mentions([MENTION], client)
    assert len(client.calls) == 1
    assert "INSERT DATA" in client.calls[0]
    assert "msrd:mention-ORNL-TM-2316-10-18" in client.calls[0]


def test_write_mentions_sends_zero_updates_for_empty_mentions() -> None:
    client = _FakeSparqlClient()
    write_mentions([], client)
    assert len(client.calls) == 0


def test_write_mentions_is_idempotent_shape() -> None:
    client = _FakeSparqlClient()
    write_mentions([MENTION], client)
    write_mentions([MENTION], client)
    assert len(client.calls) == 2
    assert client.calls[0] == client.calls[1]


def test_write_mentions_orders_deterministically_regardless_of_input_order() -> None:
    mention_a = Mention(
        report="ORNL-TM-2316",
        start=50,
        end=60,
        surface_form="FLiBe",
        target_iri=SALT_IRI,
        document_iri=DOCUMENT_IRI,
    )
    mention_b = MENTION  # start=10, end=18 — sorts before mention_a
    client_forward = _FakeSparqlClient()
    write_mentions([mention_b, mention_a], client_forward)
    client_reversed = _FakeSparqlClient()
    write_mentions([mention_a, mention_b], client_reversed)
    assert client_forward.calls[0] == client_reversed.calls[0]


# --- openspec/changes/provenance-model additions (tasks 6.6/6.7) -----------
#
# design D6 / spec "mention-graph-writing" ADDED requirement "Mentions
# carry generation provenance": each written msr:Mention SHALL carry
# prov:wasGeneratedBy the deterministic msrd:activity-extraction Activity
# IRI, in addition to its existing msr:inDocument. These tests are written
# against that requirement and are expected to fail on this isolated
# pass-1 branch until the coder's task-3.2 change to mentions.py lands
# (mention_triples does not yet emit this edge).


def test_mention_triples_carries_generation_provenance() -> None:
    """Covers 6.6: a written mention carries prov:wasGeneratedBy
    msrd:activity-extraction (its msr:inDocument remains the derivation
    source, per the "A written mention references the extraction
    activity" scenario)."""
    triples = mention_triples(MENTION)
    assert "prov:wasGeneratedBy msrd:activity-extraction" in triples
    assert f"msr:inDocument <{DOCUMENT_IRI}>" in triples


def test_write_mentions_generation_edge_is_deterministic_across_runs() -> None:
    """Covers 6.7: adding the generation edge keeps the mention write
    idempotent -- the deterministic msrd:activity-extraction IRI
    re-asserts as a set-semantics no-op, so a second run over the same
    mentions produces byte-identical output (design D8 / spec scenario
    "Generation edge preserves fact-store idempotency")."""
    client = _FakeSparqlClient()
    write_mentions([MENTION], client)
    write_mentions([MENTION], client)
    assert len(client.calls) == 2
    assert client.calls[0] == client.calls[1]
    assert "prov:wasGeneratedBy msrd:activity-extraction" in client.calls[0]


# --- prov:wasDerivedFrom fix ------------------------------------------------
#
# mention_triples now also asserts prov:wasDerivedFrom <{document_iri}> as
# its final triple, alongside the existing prov:wasGeneratedBy
# msrd:activity-extraction and msr:inDocument edges, so a PROV-only
# consumer (e.g. the SHACL shapes) can traverse the mention's derivation
# edge without knowing about msr:inDocument.


def test_mention_triples_carries_was_derived_from_document() -> None:
    """A written mention asserts prov:wasDerivedFrom pointing at the same
    document IRI as msr:inDocument, as the final triple in the block, in
    addition to the existing prov:wasGeneratedBy and msr:inDocument
    edges."""
    triples = mention_triples(MENTION)
    assert f"prov:wasDerivedFrom <{DOCUMENT_IRI}> ." in triples
    assert triples.rstrip().endswith(f"prov:wasDerivedFrom <{DOCUMENT_IRI}> .")
    # Same document IRI as msr:inDocument -- not some other IRI.
    assert f"msr:inDocument <{DOCUMENT_IRI}> ;" in triples
    # Existing edges are preserved alongside the new one.
    assert "prov:wasGeneratedBy msrd:activity-extraction ;" in triples


def test_write_mentions_was_derived_from_is_deterministic_across_runs() -> None:
    """The new prov:wasDerivedFrom edge uses the deterministic
    document_iri, so it keeps the mention write idempotent -- a second run
    over the same mentions produces byte-identical output."""
    client = _FakeSparqlClient()
    write_mentions([MENTION], client)
    write_mentions([MENTION], client)
    assert len(client.calls) == 2
    assert client.calls[0] == client.calls[1]
    assert f"prov:wasDerivedFrom <{DOCUMENT_IRI}>" in client.calls[0]
