"""Core-dataset read-guard tests (task 10.4, design.md D1 / D10).

Pins two things about ``msr_extraction.graph_reader.GraphReader``:

1. ``build_query_params`` always injects the three ``CORE_GRAPHS`` as
   ``default-graph-uri`` dataset parameters (mirroring the Go
   ``internal/graph`` core-dataset client) and never scopes in
   ``urn:msr:staging`` or ``urn:msr:proposal/{id}``.
2. Because of (1), a concept that exists only in ``urn:msr:staging`` can
   never reach ``read_known_entities()``/``known_iris()`` -- not because
   the reader filters it out after the fact, but because the reader never
   asks the store about that graph in the first place. The fake
   ``select_fn`` below documents this: ``read_known_entities()`` issues
   four separate SELECTs (SKOS concepts, ontology classes, physical
   properties, molten salts); the fake dispatches on a query substring and
   returns bindings for the approved concept only on the SKOS-concept
   SELECT, and an empty result for every other SELECT -- exactly what a
   correctly core-scoped store would produce, since the staging-only
   concept was never in scope to begin with.
"""

from __future__ import annotations

from msr_extraction.graph_reader import CORE_GRAPHS, GraphReader

APPROVED_IRI = "https://w3id.org/msr-kg/vocab#approved"
STAGING_ONLY_IRI = "https://w3id.org/msr-kg/vocab#staging-only"

QUERY_ENDPOINT = "http://x/repositories/msr"


def test_core_graphs_constant_is_the_three_core_graphs() -> None:
    assert CORE_GRAPHS == ("urn:msr:ontology", "urn:msr:data", "urn:msr:vocab")


class TestBuildQueryParams:
    def test_injects_all_three_core_graphs_as_default_graph_uri(self) -> None:
        reader = GraphReader(QUERY_ENDPOINT)
        params = reader.build_query_params("SELECT * WHERE {?s ?p ?o}")

        assert ("default-graph-uri", "urn:msr:ontology") in params
        assert ("default-graph-uri", "urn:msr:data") in params
        assert ("default-graph-uri", "urn:msr:vocab") in params

    def test_includes_the_query_parameter(self) -> None:
        reader = GraphReader(QUERY_ENDPOINT)
        query = "SELECT * WHERE {?s ?p ?o}"
        params = reader.build_query_params(query)

        query_values = [value for key, value in params if key == "query"]
        assert query_values == [query]

    def test_never_scopes_in_staging_or_proposal_graphs(self) -> None:
        reader = GraphReader(QUERY_ENDPOINT)
        params = reader.build_query_params("SELECT * WHERE {?s ?p ?o}")

        graph_values = [value for key, value in params if key == "default-graph-uri"]
        assert "urn:msr:staging" not in graph_values
        assert "urn:msr:proposal" not in graph_values
        # Belt-and-braces: neither string appears in *any* param value.
        for _key, value in params:
            assert "urn:msr:staging" not in value
            assert "urn:msr:proposal" not in value


def _binding(iri: str, label: str) -> dict[str, dict[str, str]]:
    return {
        "c": {"value": iri, "type": "uri"},
        "label": {"value": label, "type": "literal"},
    }


def _fake_select_fn_core_dataset_only(query: str) -> list[dict[str, dict[str, str]]]:
    """Stand-in for the real SPARQL SELECT transport.

    ``read_known_entities()`` issues four separate SELECTs, distinguishable
    by a substring in the query text (see ``graph_reader.py``'s
    ``_SKOS_CONCEPTS_QUERY`` / ``_ONTOLOGY_CLASSES_QUERY`` /
    ``_PHYSICAL_PROPERTIES_QUERY`` / ``_MOLTEN_SALTS_QUERY``). Only the
    SKOS-concept SELECT yields a row here (the approved concept); every
    other SELECT returns empty. A staging-only concept is absent from this
    fake's data on purpose -- a real store restricted to CORE_GRAPHS (via
    build_query_params) would never surface it, since urn:msr:staging is
    never part of the dataset asked for.
    """
    if "skos:Concept" in query:
        return [_binding(APPROVED_IRI, "Approved Concept")]
    return []


class TestReadKnownEntitiesCoreDatasetGuard:
    def test_approved_concept_is_present(self) -> None:
        reader = GraphReader(QUERY_ENDPOINT, select_fn=_fake_select_fn_core_dataset_only)

        entities = reader.read_known_entities()

        assert any(entity.target_iri == APPROVED_IRI for entity in entities)

    def test_staging_only_concept_is_absent(self) -> None:
        reader = GraphReader(QUERY_ENDPOINT, select_fn=_fake_select_fn_core_dataset_only)

        entities = reader.read_known_entities()

        assert all(entity.target_iri != STAGING_ONLY_IRI for entity in entities)

    def test_known_iris_includes_approved_and_excludes_staging(self) -> None:
        reader = GraphReader(QUERY_ENDPOINT, select_fn=_fake_select_fn_core_dataset_only)

        iris = reader.known_iris()

        assert isinstance(iris, set)
        assert APPROVED_IRI in iris
        assert STAGING_ONLY_IRI not in iris
