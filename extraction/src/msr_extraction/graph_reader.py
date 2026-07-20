"""Core-dataset SPARQL query (read) client (design.md D1).

Mirrors the Go ``internal/graph`` client's core-dataset enforcement on the
Python side: every read is restricted to the three core graphs
(``urn:msr:ontology``, ``urn:msr:data``, ``urn:msr:vocab``) via the SPARQL
protocol's ``default-graph-uri`` parameter, so pending evolution proposals
sitting in ``urn:msr:staging``/``urn:msr:proposal/{id}`` never leak into a
read — in particular, never seed the NER matcher (entity-ruler-seeding
spec, "Seeding reads the core dataset only").

This is the read counterpart to the chunk-5 ``SparqlClient`` (UPDATE-only,
``extraction/src/msr_extraction/sparql.py``): a genuinely new client, since
it targets the repository's query endpoint (no ``/statements`` suffix) with
explicit dataset-graph parameters rather than posting an UPDATE body.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlencode

from msr_extraction.config import Config

MSR = "https://w3id.org/msr-kg/ontology#"
MSRD = "https://w3id.org/msr-kg/data#"
VOC = "https://w3id.org/msr-kg/vocab#"

# The three core graphs every read is restricted to (design.md D1). Staging
# (``urn:msr:staging``) and proposal (``urn:msr:proposal/{id}``) graphs are
# deliberately never included here.
CORE_GRAPHS = ("urn:msr:ontology", "urn:msr:data", "urn:msr:vocab")

# SPARQL-JSON bindings: one dict per result row, var name -> {"value": ..., "type": ...}.
Bindings = list[dict[str, dict[str, str]]]
SelectFn = Callable[[str], Bindings]

_SKOS_CONCEPTS_QUERY = """\
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT ?c ?label WHERE {
    ?c a skos:Concept .
    { ?c skos:prefLabel ?label } UNION { ?c skos:altLabel ?label }
}
"""

_ONTOLOGY_CLASSES_QUERY = """\
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?c ?label WHERE {
    ?c a owl:Class ; rdfs:label ?label .
}
"""

_PHYSICAL_PROPERTIES_QUERY = """\
PREFIX msr: <https://w3id.org/msr-kg/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?c ?label WHERE {
    ?c a msr:PhysicalProperty ; rdfs:label ?label .
}
"""

_MOLTEN_SALTS_QUERY = """\
PREFIX msr: <https://w3id.org/msr-kg/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?c ?label WHERE {
    ?c a msr:MoltenSalt ; rdfs:label ?label .
}
"""

_SALT_ROLES_QUERY = """\
PREFIX msr: <https://w3id.org/msr-kg/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?c ?label WHERE {
    ?c a msr:SaltRole ; rdfs:label ?label .
}
"""

_REACTOR_CONCEPTS_QUERY = """\
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT ?c WHERE { ?c skos:broader* <https://w3id.org/msr-kg/vocab#molten-salt-reactors> . }
"""

_VERSION_QUERY = """\
PREFIX owl: <http://www.w3.org/2002/07/owl#>
SELECT ?version WHERE {
    <https://w3id.org/msr-kg/ontology> owl:versionInfo ?version .
}
"""


@dataclass(frozen=True)
class KnownEntity:
    """A known entity read from the core dataset, ready to seed the matcher."""

    target_iri: str
    labels: tuple[str, ...]
    kind: str  # "concept" | "class" | "salt"


class GraphReader:
    """Reads the core dataset (vocab + ontology + salt catalog) over SPARQL.

    Every query is restricted to :data:`CORE_GRAPHS` via
    :meth:`build_query_params` — this is the enforcement mechanism, not the
    query text itself (GraphDB's no-dataset default is the union of all
    graphs, so the restriction must come from the protocol parameters).
    """

    def __init__(
        self,
        query_endpoint: str,
        *,
        select_fn: SelectFn | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.query_endpoint = query_endpoint
        self.timeout = timeout
        self._select = select_fn if select_fn is not None else self._default_select

    @classmethod
    def from_config(cls, config: Config) -> GraphReader:
        """Build a GraphReader targeting ``config.sparql_query_endpoint``."""
        return cls(config.sparql_query_endpoint)

    def build_query_params(self, query: str) -> list[tuple[str, str]]:
        """Build the form-encoded params enforcing the core-dataset restriction.

        Injects ``default-graph-uri`` once per core graph (design.md D1) —
        this, not the query text, is what keeps staging/proposal graphs out
        of every read.
        """
        params = [("query", query)]
        params.extend(("default-graph-uri", graph) for graph in CORE_GRAPHS)
        return params

    def _default_select(self, query: str) -> Bindings:
        # deferred import: `import httpx` belongs inside this function body —
        # httpx is a third-party dependency and must not be required merely
        # to import this module (mirrors sparql.py's convention).
        import httpx

        # `build_query_params` returns a list of tuples (not a Mapping),
        # since `default-graph-uri` must be repeated once per core graph.
        # httpx's `data=` parameter expects a Mapping and mishandles a list
        # of tuples as the request content stream, so the params must be
        # form-encoded explicitly and sent via `content=` instead.
        body = urlencode(self.build_query_params(query))
        response = httpx.post(
            self.query_endpoint,
            content=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/sparql-results+json",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()["results"]["bindings"]

    def read_version(self) -> str | None:
        """Read ``owl:versionInfo`` of the ontology, or None if absent."""
        bindings = self._select(_VERSION_QUERY)
        if not bindings:
            return None
        return bindings[0]["version"]["value"]

    def read_known_entities(self) -> list[KnownEntity]:
        """Read the known-entity set from the core dataset.

        Covers vocab SKOS concepts, ontology classes and physical
        properties, and the loaded salt catalog. One :class:`KnownEntity`
        per subject IRI; multiple labels for the same subject are merged
        into a single ``labels`` tuple. Results are sorted by ``target_iri``
        for determinism.
        """
        merged: dict[str, tuple[str, list[str]]] = {}

        def _merge(bindings: Bindings, kind: str) -> None:
            for binding in bindings:
                iri = binding["c"]["value"]
                label = binding["label"]["value"]
                if not label or not label.strip():
                    continue
                if iri not in merged:
                    merged[iri] = (kind, [])
                merged[iri][1].append(label)

        _merge(self._select(_SKOS_CONCEPTS_QUERY), "concept")
        _merge(self._select(_ONTOLOGY_CLASSES_QUERY), "class")
        _merge(self._select(_PHYSICAL_PROPERTIES_QUERY), "class")
        _merge(self._select(_MOLTEN_SALTS_QUERY), "salt")

        entities = [
            KnownEntity(target_iri=iri, labels=tuple(labels), kind=kind)
            for iri, (kind, labels) in merged.items()
        ]
        entities.sort(key=lambda e: e.target_iri)
        return entities

    def known_iris(self) -> set[str]:
        """The set of all known target IRIs (union across all entity kinds)."""
        return {entity.target_iri for entity in self.read_known_entities()}

    def read_salt_roles(self) -> set[str]:
        """Read the closed set of ``msr:SaltRole`` individual IRIs.

        Covers the fixed role vocabulary (``msr:FuelSalt``,
        ``msr:CoolantSalt``, ``msr:FlushSalt``) used to validate extracted
        salt-role relations against a known, closed set.
        """
        bindings = self._select(_SALT_ROLES_QUERY)
        return {binding["c"]["value"] for binding in bindings}

    def read_physical_properties(self) -> set[str]:
        """Read the closed set of ``msr:PhysicalProperty`` individual IRIs.

        Distinct from :meth:`read_known_entities`, which lumps physical
        properties in with all other ``owl:Class`` subjects under kind
        ``"class"``; this accessor isolates property IRIs so extracted
        property relations can be validated against a closed set.
        """
        bindings = self._select(_PHYSICAL_PROPERTIES_QUERY)
        return {binding["c"]["value"] for binding in bindings}

    def read_molten_salts(self) -> set[str]:
        """Read the closed set of loaded ``msr:MoltenSalt`` individual IRIs.

        Used to validate the salt referent of an extracted relation against
        the closed set of salts actually loaded into the core dataset.
        """
        bindings = self._select(_MOLTEN_SALTS_QUERY)
        return {binding["c"]["value"] for binding in bindings}

    def read_reactor_concepts(self) -> set[str]:
        """Read the reactor SKOS-concept IRIs (chunk 7's grounding gate).

        Unlike :meth:`read_molten_salts`/:meth:`read_salt_roles`, this is
        not a closed set an extracted relation's referent must belong to
        outright — reactor *individuals* are minted, not validated against
        a closed set (design.md D3/D9, since ``ground-demo-in-real-docs``
        removed all reactor individuals). Instead this set is the source
        of the reactor **grounding gate**: a reactor relation is admitted
        only when its reactor reference is both a member of this set and a
        chunk-6 ``linked`` mention in the same sentence. ``skos:broader*``
        is reflexive, so the result includes
        ``voc:molten-salt-reactors`` itself as well as every narrower
        reactor concept.
        """
        bindings = self._select(_REACTOR_CONCEPTS_QUERY)
        return {binding["c"]["value"] for binding in bindings}
