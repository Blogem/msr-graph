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

# openspec/changes/provenance-run-lineage: the run timestamp threaded into
# write_mentions' per-run generation edges (task 5.7).
RUN_TS = "2024-01-02T03:04:05+00:00"
OTHER_RUN_TS = "2024-06-07T08:09:10+00:00"


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


def test_write_mentions_sends_zero_updates_for_empty_mentions() -> None:
    client = _FakeSparqlClient()
    write_mentions([], client, RUN_TS)
    assert len(client.calls) == 0


def test_write_mentions_is_idempotent_shape_for_a_fixed_run_ts() -> None:
    """Re-invoking write_mentions with the same run_ts is deterministic: both
    the urn:msr:data write and the urn:msr:provenance write are pure
    functions of (mentions, run_ts), so a repeated call at the same run_ts
    (e.g. a genuine re-send) produces byte-identical updates in both slots
    (design D4: "a genuine re-send of the same run is still a no-op")."""
    client = _FakeSparqlClient()
    write_mentions([MENTION], client, RUN_TS)
    write_mentions([MENTION], client, RUN_TS)
    assert len(client.calls) == 4
    assert client.calls[0] == client.calls[2]  # urn:msr:data write
    assert client.calls[1] == client.calls[3]  # urn:msr:provenance write


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
    write_mentions([mention_b, mention_a], client_forward, RUN_TS)
    client_reversed = _FakeSparqlClient()
    write_mentions([mention_a, mention_b], client_reversed, RUN_TS)
    assert client_forward.calls[0] == client_reversed.calls[0]


# --- openspec/changes/provenance-model additions (tasks 6.6/6.7) -----------
#
# design D6 / spec "mention-graph-writing" ADDED requirement "Mentions
# carry generation provenance": each written msr:Mention SHALL carry
# prov:wasGeneratedBy the deterministic msrd:activity-extraction Activity
# IRI, in addition to its existing msr:inDocument. These tests are written
# against that requirement.


def test_mention_triples_carries_generation_provenance() -> None:
    """Covers 6.6: a written mention carries prov:wasGeneratedBy
    msrd:activity-extraction (its msr:inDocument remains the derivation
    source, per the "A written mention references the extraction
    activity" scenario)."""
    triples = mention_triples(MENTION)
    assert "prov:wasGeneratedBy msrd:activity-extraction" in triples
    assert f"msr:inDocument <{DOCUMENT_IRI}>" in triples


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


# --- openspec/changes/provenance-run-lineage additions (task 5.7) ----------
#
# write_mentions gains a run_ts parameter (task 3.2/3.4) and now sends TWO
# updates via the client for a non-empty mention list: (1) the existing
# urn:msr:data INSERT DATA -- unchanged, still carrying each mention's
# stable prov:wasGeneratedBy msrd:activity-extraction edge -- and (2) a new
# urn:msr:provenance INSERT DATA carrying one
# <mention> prov:wasGeneratedBy <urn:msr:run:extraction/<run_ts>> per-run
# generation edge per written mention. No read-before-write: every mention
# in the input list gets a generation edge, whether or not it was already
# present in urn:msr:data (design D3 "touched" semantics).
#
# ASSUMPTION (pass-1, flagged for reconciliation at merge): this pins
# write_mentions(mentions, client, run_ts) sending exactly two client.update
# calls in the order [urn:msr:data, urn:msr:provenance] for a non-empty
# mention list. If the coder's task-3.2 change lands in a different order
# or as N+1 discrete provenance updates instead of one batched update, this
# needs reconciling at merge -- the acceptance intent (both edges exist,
# both idempotent/append-only as designed) is what must survive, not the
# exact call ordering/count.


def test_write_mentions_sends_two_updates_for_nonempty_mentions() -> None:
    client = _FakeSparqlClient()
    write_mentions([MENTION], client, RUN_TS)
    assert len(client.calls) == 2


def test_write_mentions_first_update_is_the_unchanged_data_graph_write() -> None:
    """The urn:msr:data update -- and the mention's stable
    prov:wasGeneratedBy msrd:activity-extraction edge inside it -- is
    unchanged by the run_ts addition."""
    client = _FakeSparqlClient()
    write_mentions([MENTION], client, RUN_TS)
    data_update = _collapse_ws(client.calls[0])
    assert "GRAPH <urn:msr:data>" in data_update
    assert "msrd:mention-ORNL-TM-2316-10-18" in data_update
    assert "prov:wasGeneratedBy msrd:activity-extraction" in data_update


def test_write_mentions_second_update_carries_per_run_generation_edge() -> None:
    """Covers 5.7: the written mention IRI gets a
    prov:wasGeneratedBy <urn:msr:run:extraction/<run_ts>> edge in a
    urn:msr:provenance update."""
    client = _FakeSparqlClient()
    write_mentions([MENTION], client, RUN_TS)
    prov_update = _collapse_ws(client.calls[1])
    assert "GRAPH <urn:msr:provenance>" in prov_update
    assert (
        f"msrd:mention-ORNL-TM-2316-10-18 prov:wasGeneratedBy <urn:msr:run:extraction/{RUN_TS}>"
        in prov_update
    )


def test_write_mentions_distinct_run_ts_yields_distinct_generation_edges() -> None:
    """Two invocations at distinct run_ts values append disjoint per-run
    generation edges -- urn:msr:provenance is append-only (design D2/D4)."""
    client_a = _FakeSparqlClient()
    write_mentions([MENTION], client_a, RUN_TS)
    client_b = _FakeSparqlClient()
    write_mentions([MENTION], client_b, OTHER_RUN_TS)

    assert f"urn:msr:run:extraction/{RUN_TS}" in client_a.calls[1]
    assert f"urn:msr:run:extraction/{OTHER_RUN_TS}" not in client_a.calls[1]
    assert f"urn:msr:run:extraction/{OTHER_RUN_TS}" in client_b.calls[1]
    assert f"urn:msr:run:extraction/{RUN_TS}" not in client_b.calls[1]


def test_write_mentions_data_graph_update_is_idempotent_across_run_ts() -> None:
    """The urn:msr:data update does not depend on run_ts at all, so two
    runs at distinct run_ts values still produce a byte-identical
    urn:msr:data write (only urn:msr:provenance grows)."""
    client_a = _FakeSparqlClient()
    write_mentions([MENTION], client_a, RUN_TS)
    client_b = _FakeSparqlClient()
    write_mentions([MENTION], client_b, OTHER_RUN_TS)
    assert client_a.calls[0] == client_b.calls[0]
