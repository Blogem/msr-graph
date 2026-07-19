"""Tests for the core-dataset graph reader (design.md D1, task 3.1/3.2).

A fake ``select_fn`` is injected everywhere so these tests never touch
httpx or a real GraphDB endpoint. The behavioral core-dataset read-guard
acceptance test (design.md D10, task 10.4) is authored separately.
"""

from __future__ import annotations

from msr_extraction.config import Config
from msr_extraction.graph_reader import (
    CORE_GRAPHS,
    MSR,
    MSRD,
    VOC,
    GraphReader,
    KnownEntity,
)


def _binding(iri: str, label: str) -> dict[str, dict[str, str]]:
    return {
        "c": {"value": iri, "type": "uri"},
        "label": {"value": label, "type": "literal"},
    }


def test_build_query_params_restricts_to_three_core_graphs() -> None:
    reader = GraphReader("http://example/repositories/msr")
    params = reader.build_query_params("SELECT * WHERE { ?s ?p ?o }")

    assert params[0] == ("query", "SELECT * WHERE { ?s ?p ?o }")
    graph_params = [value for key, value in params if key == "default-graph-uri"]
    assert graph_params == list(CORE_GRAPHS)


def test_build_query_params_never_includes_staging_or_proposal() -> None:
    reader = GraphReader("http://example/repositories/msr")
    params = reader.build_query_params("SELECT * WHERE { ?s ?p ?o }")

    graph_params = {value for key, value in params if key == "default-graph-uri"}
    assert "urn:msr:staging" not in graph_params
    assert not any(value.startswith("urn:msr:proposal") for value in graph_params)


def test_from_config_targets_sparql_query_endpoint() -> None:
    config = Config(graphdb_url="http://localhost:7200", graphdb_repo="msr")
    reader = GraphReader.from_config(config)

    assert reader.query_endpoint == config.sparql_query_endpoint
    assert reader.query_endpoint == "http://localhost:7200/repositories/msr"


def test_read_version_parses_version_binding() -> None:
    def select_fn(query: str) -> list[dict[str, dict[str, str]]]:
        return [{"version": {"value": "0.1.0-seed", "type": "literal"}}]

    reader = GraphReader("http://example", select_fn=select_fn)
    assert reader.read_version() == "0.1.0-seed"


def test_read_version_returns_none_when_absent() -> None:
    def select_fn(query: str) -> list[dict[str, dict[str, str]]]:
        return []

    reader = GraphReader("http://example", select_fn=select_fn)
    assert reader.read_version() is None


def test_read_known_entities_merges_labels_and_classifies_by_source() -> None:
    concept_iri = f"{VOC}viscosity"
    class_iri = f"{MSR}MoltenSalt"
    property_iri = f"{MSR}viscosity"
    salt_iri = f"{MSRD}salt-BeF2-LiF-34.0-66.0"

    responses = {
        "skos:Concept": [
            _binding(concept_iri, "viscosity"),
            _binding(concept_iri, "dynamic viscosity"),
        ],
        "owl:Class": [_binding(class_iri, "MoltenSalt")],
        "msr:PhysicalProperty": [_binding(property_iri, "viscosity")],
        "msr:MoltenSalt": [_binding(salt_iri, "LiF-BeF2 (34.0-66.0)")],
    }

    def select_fn(query: str) -> list[dict[str, dict[str, str]]]:
        for marker, bindings in responses.items():
            if marker in query:
                return bindings
        raise AssertionError(f"unexpected query: {query}")

    reader = GraphReader("http://example", select_fn=select_fn)
    entities = reader.read_known_entities()

    by_iri = {e.target_iri: e for e in entities}

    assert by_iri[concept_iri] == KnownEntity(
        target_iri=concept_iri,
        labels=("viscosity", "dynamic viscosity"),
        kind="concept",
    )
    assert by_iri[class_iri].kind == "class"
    assert by_iri[class_iri].labels == ("MoltenSalt",)
    assert by_iri[property_iri].kind == "class"
    assert by_iri[property_iri].labels == ("viscosity",)
    assert by_iri[salt_iri] == KnownEntity(
        target_iri=salt_iri,
        labels=("LiF-BeF2 (34.0-66.0)",),
        kind="salt",
    )

    # Deterministic ordering by target_iri.
    assert [e.target_iri for e in entities] == sorted(e.target_iri for e in entities)


def test_read_known_entities_skips_empty_or_whitespace_labels() -> None:
    concept_iri = f"{VOC}molten-salts"

    def select_fn(query: str) -> list[dict[str, dict[str, str]]]:
        if "skos:Concept" in query:
            return [_binding(concept_iri, ""), _binding(concept_iri, "   ")]
        return []

    reader = GraphReader("http://example", select_fn=select_fn)
    entities = reader.read_known_entities()

    assert entities == []


def test_known_iris_is_union_of_all_kinds() -> None:
    concept_iri = f"{VOC}viscosity"
    class_iri = f"{MSR}MoltenSaltReactor"
    salt_iri = f"{MSRD}salt-BeF2-LiF-34.0-66.0"

    responses = {
        "skos:Concept": [_binding(concept_iri, "viscosity")],
        "owl:Class": [_binding(class_iri, "MoltenSaltReactor")],
        "msr:PhysicalProperty": [],
        "msr:MoltenSalt": [_binding(salt_iri, "LiF-BeF2 (34.0-66.0)")],
    }

    def select_fn(query: str) -> list[dict[str, dict[str, str]]]:
        for marker, bindings in responses.items():
            if marker in query:
                return bindings
        raise AssertionError(f"unexpected query: {query}")

    reader = GraphReader("http://example", select_fn=select_fn)
    assert reader.known_iris() == {concept_iri, class_iri, salt_iri}


def test_module_exposes_public_constants() -> None:
    assert MSR == "https://w3id.org/msr-kg/ontology#"
    assert MSRD == "https://w3id.org/msr-kg/data#"
    assert VOC == "https://w3id.org/msr-kg/vocab#"
    assert CORE_GRAPHS == ("urn:msr:ontology", "urn:msr:data", "urn:msr:vocab")
