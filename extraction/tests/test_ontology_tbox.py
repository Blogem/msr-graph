"""Reintroduced role/reactor TBox test (task 8.13, tasks.md 5.0/5.0a).

Parses ``ontology/msr.ttl`` and ``ontology/vocab.ttl`` with rdflib and pins
the reintroduced OWL role/reactor layer: ``msr:SaltRole`` + its closed
``FuelSalt``/``CoolantSalt``/``FlushSalt`` individuals, ``msr:hasRole``
(domain ``MoltenSalt``, range ``SaltRole``), ``msr:MoltenSaltReactor``, and
``msr:usedIn`` (domain ``MoltenSalt``, range ``MoltenSaltReactor``); no
reactor individuals are seeded (they are minted at extraction time, task
6.1); the extraction-provenance datatype properties
``msr:extractionConfidence``/``msr:extractionRationale`` are declared; and
the role/reactor SKOS concepts still resolve in ``vocab.ttl``.

This is the one test file in this pass-1 suite that needs a real
dependency (rdflib) beyond stdlib -- added to the ``test`` extra in
``pyproject.toml`` for this reason.
"""

from __future__ import annotations

from pathlib import Path

import rdflib
from rdflib.namespace import OWL, RDF, RDFS

MSR = rdflib.Namespace("https://w3id.org/msr-kg/ontology#")
VOC = rdflib.Namespace("https://w3id.org/msr-kg/vocab#")
SKOS = rdflib.Namespace("http://www.w3.org/2004/02/skos/core#")

ONTOLOGY_DIR = Path(__file__).resolve().parents[2] / "ontology"


def _load_msr_graph() -> rdflib.Graph:
    graph = rdflib.Graph()
    graph.parse(ONTOLOGY_DIR / "msr.ttl", format="turtle")
    return graph


def _load_vocab_graph() -> rdflib.Graph:
    graph = rdflib.Graph()
    graph.parse(ONTOLOGY_DIR / "vocab.ttl", format="turtle")
    return graph


def test_msr_ttl_parses_as_valid_turtle() -> None:
    graph = _load_msr_graph()
    assert len(graph) > 0


def test_vocab_ttl_parses_as_valid_turtle() -> None:
    graph = _load_vocab_graph()
    assert len(graph) > 0


def test_salt_role_is_an_owl_class() -> None:
    graph = _load_msr_graph()
    assert (MSR.SaltRole, RDF.type, OWL.Class) in graph


def test_salt_role_individuals_are_typed() -> None:
    graph = _load_msr_graph()
    for individual in (MSR.FuelSalt, MSR.CoolantSalt, MSR.FlushSalt):
        assert (individual, RDF.type, MSR.SaltRole) in graph


def test_has_role_domain_and_range() -> None:
    graph = _load_msr_graph()
    assert (MSR.hasRole, RDFS.domain, MSR.MoltenSalt) in graph
    assert (MSR.hasRole, RDFS.range, MSR.SaltRole) in graph


def test_molten_salt_reactor_is_an_owl_class() -> None:
    graph = _load_msr_graph()
    assert (MSR.MoltenSaltReactor, RDF.type, OWL.Class) in graph


def test_used_in_domain_and_range() -> None:
    graph = _load_msr_graph()
    assert (MSR.usedIn, RDFS.domain, MSR.MoltenSalt) in graph
    assert (MSR.usedIn, RDFS.range, MSR.MoltenSaltReactor) in graph


def test_extraction_confidence_and_rationale_are_datatype_properties() -> None:
    graph = _load_msr_graph()
    assert (MSR.extractionConfidence, RDF.type, OWL.DatatypeProperty) in graph
    assert (MSR.extractionRationale, RDF.type, OWL.DatatypeProperty) in graph


def test_no_reactor_individuals_are_seeded() -> None:
    """Reactor individuals are minted at extraction time (task 6.1), not
    seeded into the ontology TBox file."""
    graph = _load_msr_graph()
    reactors = list(graph.subjects(RDF.type, MSR.MoltenSaltReactor))
    assert reactors == []


def test_reactor_skos_concept_still_resolves_in_vocab() -> None:
    graph = _load_vocab_graph()
    assert (VOC["molten-salt-reactors"], RDF.type, SKOS.Concept) in graph
    labels = set(graph.objects(VOC["molten-salt-reactors"], SKOS.prefLabel))
    assert any("reactor" in str(label).lower() for label in labels)


def test_role_skos_concepts_still_resolve_in_vocab() -> None:
    graph = _load_vocab_graph()
    for concept in (VOC["fuel-salt"], VOC["coolant-salt"], VOC["flush-salt"]):
        assert (concept, RDF.type, SKOS.Concept) in graph
