"""Salt role / reactor edge tests (tasks 8.6 + 8.14-reactor, spec
salt-role-reactor-edges).

Pins ``role_edge_triples``/``reactor_edge_triples`` (deterministic,
reified, no-blank-node triple blocks) and ``write_edges`` (exactly two
``client.update`` calls for a non-empty edge set: one ``urn:msr:data``
write, one ``urn:msr:provenance`` per-run generation-edge write mirroring
``provenance.py``'s ``run_activity_iri``). Also pins ``reactor_iri`` and
the 8.14-reactor SHACL-adjacent requirement that reactor grounding uses
``skos:exactMatch``, never ``msr:linksTo`` (avoiding a
``LinksToTargetKindShape``/domain trip since ``msr:linksTo`` is declared
with ``rdfs:domain msr:Mention``).
"""

from __future__ import annotations

from msr_extraction.edges import (
    ReactorEdge,
    RoleEdge,
    reactor_edge_triples,
    reactor_iri,
    role_edge_triples,
    write_edges,
)

SALT_IRI = "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"
ROLE_IRI = "https://w3id.org/msr-kg/ontology#CoolantSalt"
REPORT = "ORNL-TM-2316"
DOCUMENT_IRI = "https://w3id.org/msr-kg/data#ORNL-TM-2316"
REACTOR_GROUNDING = "https://w3id.org/msr-kg/vocab#molten-salt-reactors"

ROLE_EDGE = RoleEdge(
    report=REPORT,
    salt_iri=SALT_IRI,
    role_iri=ROLE_IRI,
    document_iri=DOCUMENT_IRI,
    confidence=0.9,
    rationale="the text states MSRE's coolant salt is BeF2-LiF",
)

REACTOR_EDGE = ReactorEdge(
    report=REPORT,
    salt_iri=SALT_IRI,
    reactor_slug="msre",
    reactor_label="MSRE",
    grounding_concept_iri=REACTOR_GROUNDING,
    document_iri=DOCUMENT_IRI,
    confidence=0.85,
    rationale="the text links BeF2-LiF's use to the MSRE",
)


class FakeClient:
    """Captures ``.update(...)`` calls; never touches the network."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def update(self, sparql_update: str) -> None:
        self.calls.append(sparql_update)


# --- role edges (task 8.6) --------------------------------------------------


def test_role_edge_triples_contain_the_direct_hasrole_edge() -> None:
    block = role_edge_triples(ROLE_EDGE)
    assert "msrd:salt-BeF2-LiF-34.0-66.0 msr:hasRole msr:CoolantSalt" in block


def test_role_edge_triples_contain_a_reification_with_predicate_and_object() -> None:
    block = role_edge_triples(ROLE_EDGE)
    assert "a rdf:Statement" in block
    assert "rdf:predicate msr:hasRole" in block
    assert "rdf:object msr:CoolantSalt" in block


def test_role_edge_triples_reification_carries_confidence_and_rationale() -> None:
    block = role_edge_triples(ROLE_EDGE)
    assert "msr:extractionConfidence" in block
    assert "msr:extractionRationale" in block


def test_role_edge_triples_reification_carries_generation_provenance() -> None:
    block = role_edge_triples(ROLE_EDGE)
    assert "prov:wasGeneratedBy msrd:activity-extraction" in block
    assert f"prov:wasDerivedFrom <{DOCUMENT_IRI}>" in block or (
        "prov:wasDerivedFrom msrd:ORNL-TM-2316" in block
    )


def test_role_edge_triples_have_no_blank_nodes() -> None:
    block = role_edge_triples(ROLE_EDGE)
    assert "[" not in block
    assert "_:" not in block


def test_role_edge_triples_are_deterministic() -> None:
    assert role_edge_triples(ROLE_EDGE) == role_edge_triples(ROLE_EDGE)


# --- reactor edges (task 8.6 + 8.14-reactor) --------------------------------


def test_reactor_iri_is_deterministic() -> None:
    assert reactor_iri("msre") == "msrd:reactor-msre"


def test_reactor_edge_triples_mint_the_reactor_individual() -> None:
    block = reactor_edge_triples(REACTOR_EDGE)
    assert "msrd:reactor-msre a msr:MoltenSaltReactor" in block
    assert 'rdfs:label "MSRE"' in block


def test_reactor_edge_triples_ground_via_skos_exact_match_not_linksto() -> None:
    """8.14-reactor: reactor grounding must use skos:exactMatch, never
    msr:linksTo (msr:linksTo's rdfs:domain is msr:Mention, so using it here
    would trip the merged SHACL LinksToTargetKindShape/domain shape)."""
    block = reactor_edge_triples(REACTOR_EDGE)
    assert "skos:exactMatch voc:molten-salt-reactors" in block
    assert "msr:linksTo" not in block


def test_reactor_edge_triples_contain_the_direct_usedin_edge() -> None:
    block = reactor_edge_triples(REACTOR_EDGE)
    assert "msrd:salt-BeF2-LiF-34.0-66.0 msr:usedIn msrd:reactor-msre" in block


def test_reactor_edge_triples_contain_a_reification_for_usedin() -> None:
    block = reactor_edge_triples(REACTOR_EDGE)
    assert "a rdf:Statement" in block
    assert "rdf:predicate msr:usedIn" in block


def test_reactor_edge_triples_have_no_blank_nodes() -> None:
    block = reactor_edge_triples(REACTOR_EDGE)
    assert "[" not in block
    assert "_:" not in block


def test_reactor_edge_triples_are_deterministic() -> None:
    assert reactor_edge_triples(REACTOR_EDGE) == reactor_edge_triples(REACTOR_EDGE)


# --- write_edges -------------------------------------------------------------


def test_write_edges_sends_zero_updates_for_empty_edges() -> None:
    client = FakeClient()
    write_edges([], [], client, "2026-01-01T00:00:00+00:00")
    assert len(client.calls) == 0


def test_write_edges_sends_exactly_two_updates_for_nonempty_edges() -> None:
    client = FakeClient()
    write_edges([ROLE_EDGE], [REACTOR_EDGE], client, "2026-01-01T00:00:00+00:00")
    assert len(client.calls) == 2


def test_write_edges_second_update_targets_the_provenance_graph() -> None:
    client = FakeClient()
    run_ts = "2026-01-01T00:00:00+00:00"
    write_edges([ROLE_EDGE], [REACTOR_EDGE], client, run_ts)
    prov_update = client.calls[1]
    assert "GRAPH <urn:msr:provenance>" in prov_update


def _reification_subject(block: str) -> str:
    """Extract the reification node's subject IRI/CURIE from a
    role/reactor_edge_triples block (the token immediately preceding
    ``a rdf:Statement``)."""
    idx = block.index("a rdf:Statement")
    before = block[:idx].rstrip()
    return before.splitlines()[-1].strip()


def test_write_edges_second_update_references_the_run_activity_and_reactor() -> None:
    client = FakeClient()
    run_ts = "2026-01-01T00:00:00+00:00"
    write_edges([ROLE_EDGE], [REACTOR_EDGE], client, run_ts)
    prov_update = client.calls[1]
    assert f"prov:wasGeneratedBy <urn:msr:run:extraction/{run_ts}>" in prov_update
    # The provenance write references the minted reactor individual...
    assert "msrd:reactor-msre" in prov_update
    # ...and each edge's reification-node subject (per-run generation edge).
    role_subject = _reification_subject(role_edge_triples(ROLE_EDGE))
    reactor_subject = _reification_subject(reactor_edge_triples(REACTOR_EDGE))
    assert role_subject in prov_update
    assert reactor_subject in prov_update
