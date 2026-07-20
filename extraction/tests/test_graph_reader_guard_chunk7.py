"""Core-dataset read-guard tests for the chunk-7 closed-set readers (task 8.7).

Distinct from ``test_graph_reader_guard.py`` (task 10.4, chunk 6's
``read_known_entities``/``known_iris``): this file exercises the three
closed-set readers chunk 7's relation validator consumes directly --
``read_molten_salts``, ``read_physical_properties``, ``read_salt_roles``
-- and reconfirms the same core-dataset restriction mechanism
(``build_query_params`` injecting ``default-graph-uri`` once per
``CORE_GRAPHS`` member, never ``urn:msr:staging``/``urn:msr:proposal``)
that keeps a pending evolution-proposal salt/property/role out of the
known set relation validation is built against.

Runnable now (uses the already-merged ``graph_reader`` module; no
dependency on the concurrently-written ``relations.py``).
"""

from __future__ import annotations

from msr_extraction.graph_reader import CORE_GRAPHS, GraphReader

QUERY_ENDPOINT = "http://x/repositories/msr"

APPROVED_SALT_IRI = "https://w3id.org/msr-kg/ontology#salt-approved"
STAGING_ONLY_SALT_IRI = "https://w3id.org/msr-kg/ontology#salt-staging-only"
APPROVED_PROPERTY_IRI = "https://w3id.org/msr-kg/ontology#viscosity"
APPROVED_ROLE_IRI = "https://w3id.org/msr-kg/ontology#CoolantSalt"


def _binding(iri: str, label: str) -> dict[str, dict[str, str]]:
    return {
        "c": {"value": iri, "type": "uri"},
        "label": {"value": label, "type": "literal"},
    }


def _fake_select_fn_core_dataset_only(query: str) -> list[dict[str, dict[str, str]]]:
    """Stand-in for a correctly ``CORE_GRAPHS``-scoped SPARQL SELECT transport.

    Dispatches on the distinguishing class name each of
    ``read_molten_salts``/``read_physical_properties``/``read_salt_roles``
    queries for (see ``graph_reader.py``'s ``_MOLTEN_SALTS_QUERY`` /
    ``_PHYSICAL_PROPERTIES_QUERY`` / ``_SALT_ROLES_QUERY``). A
    staging-only salt is never returned by any branch on purpose: a real
    store restricted to ``CORE_GRAPHS`` (via ``build_query_params``) would
    never surface it, since a staging-only individual lives in
    ``urn:msr:staging``, which the reader never asks the store about.
    """
    if "msr:MoltenSalt" in query:
        return [_binding(APPROVED_SALT_IRI, "Approved Salt")]
    if "msr:PhysicalProperty" in query:
        return [_binding(APPROVED_PROPERTY_IRI, "viscosity")]
    if "msr:SaltRole" in query:
        return [_binding(APPROVED_ROLE_IRI, "CoolantSalt")]
    return []


class TestBuildQueryParamsCoreDatasetOnly:
    def test_includes_all_three_core_graphs_as_default_graph_uri(self) -> None:
        reader = GraphReader(QUERY_ENDPOINT)
        params = reader.build_query_params("SELECT * WHERE {?s ?p ?o}")

        assert ("default-graph-uri", "urn:msr:data") in params
        assert ("default-graph-uri", "urn:msr:ontology") in params
        assert ("default-graph-uri", "urn:msr:vocab") in params
        assert CORE_GRAPHS == ("urn:msr:ontology", "urn:msr:data", "urn:msr:vocab")

    def test_never_scopes_in_staging_or_proposal_graphs(self) -> None:
        reader = GraphReader(QUERY_ENDPOINT)
        params = reader.build_query_params("SELECT * WHERE {?s ?p ?o}")

        for _key, value in params:
            assert "urn:msr:staging" not in value
            assert "urn:msr:proposal" not in value


class TestClosedSetReadersSurfaceOnlyWhatTheCoreScopedQueryReturns:
    def test_read_molten_salts_returns_exactly_the_stub_bindings(self) -> None:
        reader = GraphReader(QUERY_ENDPOINT, select_fn=_fake_select_fn_core_dataset_only)

        salts = reader.read_molten_salts()

        assert salts == {APPROVED_SALT_IRI}
        assert STAGING_ONLY_SALT_IRI not in salts

    def test_read_physical_properties_returns_exactly_the_stub_bindings(self) -> None:
        reader = GraphReader(QUERY_ENDPOINT, select_fn=_fake_select_fn_core_dataset_only)

        properties = reader.read_physical_properties()

        assert properties == {APPROVED_PROPERTY_IRI}

    def test_read_salt_roles_returns_exactly_the_stub_bindings(self) -> None:
        reader = GraphReader(QUERY_ENDPOINT, select_fn=_fake_select_fn_core_dataset_only)

        roles = reader.read_salt_roles()

        assert roles == {APPROVED_ROLE_IRI}
