"""Salt role/reactor edge triple emission and graph writer.

Emits validated direct edges into the shared ``urn:msr:data`` graph for
two closed-vocabulary relations extracted from report text (design.md,
chunk 7):

- ``msr:hasRole`` — a loaded ``msr:MoltenSalt`` individual to one of the
  closed seed roles (``msr:FuelSalt``/``msr:CoolantSalt``/``msr:FlushSalt``).
- ``msr:usedIn`` — a loaded ``msr:MoltenSalt`` individual to a *minted*
  ``msr:MoltenSaltReactor`` individual, grounded to a vocab.ttl reactor
  concept via ``skos:exactMatch`` (not ``msr:linksTo``, whose domain is
  ``msr:Mention`` and would otherwise trip the SHACL
  ``LinksToTargetKindShape``).

Each direct edge is accompanied by a deterministic ``rdf:Statement``
reification node carrying ``msr:extractionConfidence``/
``msr:extractionRationale``, a ``msr:citedIn`` pointer to the source
document, and stable generation provenance
(``prov:wasGeneratedBy msr:activity-extraction`` / ``prov:wasDerivedFrom
<document>``) — mirroring ``mentions.py``'s reification-free mention
block, but reified here because the *edge itself* (not a node) is what
carries the confidence/rationale annotation.

All subject IRIs (reification nodes, minted reactors) are deterministic
functions of the input edge — there are no blank nodes — so re-running
the writer over the same edges is a set-semantics no-op in
``urn:msr:data``. Each written individual (reification node or minted
reactor) additionally gets a per-run generation edge into
``urn:msr:provenance`` (provenance-run-lineage design.md D1-D3):
``<individual> prov:wasGeneratedBy <urn:msr:run:extraction/<ts>>``, one per
individual per invocation, so per-run lineage accumulates without
touching the idempotent ``urn:msr:data`` block.
"""

from __future__ import annotations

from dataclasses import dataclass

from msr_extraction.provenance import ACTIVITY_IRI, run_activity_iri
from msr_extraction.sparql import SparqlClient

MSR = "https://w3id.org/msr-kg/ontology#"
MSRD = "https://w3id.org/msr-kg/data#"
VOC = "https://w3id.org/msr-kg/vocab#"

_PREFIXES = """\
PREFIX msr: <https://w3id.org/msr-kg/ontology#>
PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX voc: <https://w3id.org/msr-kg/vocab#>"""

_PROVENANCE_PREFIXES = """\
PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX prov: <http://www.w3.org/ns/prov#>"""


@dataclass(frozen=True)
class RoleEdge:
    """A ``msr:hasRole`` edge candidate, ready to be written to the graph."""

    salt_iri: str
    role_iri: str
    report: str
    document_iri: str
    confidence: float
    rationale: str


@dataclass(frozen=True)
class ReactorEdge:
    """A ``msr:usedIn`` edge candidate (with a to-be-minted reactor)."""

    salt_iri: str
    reactor_slug: str
    reactor_label: str
    grounding_concept_iri: str
    report: str
    document_iri: str
    confidence: float
    rationale: str


def _escape_literal(s: str) -> str:
    """Escape a string for use inside a double-quoted Turtle/SPARQL literal."""
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
    )


def _term(iri: str) -> str:
    """Return a Turtle term for ``iri``: a CURIE for known namespaces, else ``<iri>``.

    ``iri`` may arrive as a full IRI (from the graph reader) or already as
    a ``msr:``/``msrd:``/``voc:`` CURIE (from a caller that already
    shortened it) — both are handled so callers never have to normalize
    first.
    """
    if iri.startswith("msr:") or iri.startswith("msrd:") or iri.startswith("voc:"):
        return iri
    if iri.startswith(MSR):
        return f"msr:{iri[len(MSR):]}"
    if iri.startswith(MSRD):
        return f"msrd:{iri[len(MSRD):]}"
    if iri.startswith(VOC):
        return f"voc:{iri[len(VOC):]}"
    return f"<{iri}>"


def _local(iri: str) -> str:
    """Return the local name of ``iri``: after ``#`` for a full IRI, after ``:`` for a CURIE."""
    if "#" in iri:
        return iri.rsplit("#", 1)[1]
    if ":" in iri:
        return iri.rsplit(":", 1)[1]
    return iri


def slugify(s: str) -> str:
    """Slugify ``s`` using the exact Go rule (loader parity).

    Replaces each of ``' '``, ``'/'``, ``'#'``, ``'|'``, ``'='``, ``'@'``
    with ``'-'``, collapses repeated ``--`` to ``-``, and strips leading
    and trailing ``-``.
    """
    out = s
    for ch in (" ", "/", "#", "|", "=", "@"):
        out = out.replace(ch, "-")
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


def reactor_iri(slug: str) -> str:
    """Return the deterministic ``msrd:`` CURIE for a minted reactor individual."""
    return f"msrd:reactor-{slug}"


def role_statement_iri(e: RoleEdge) -> str:
    """Return the deterministic reification-node IRI for a ``RoleEdge``.

    ``msrd:edge-{report}-{salt_local}-hasRole-{role_local}``, where
    ``salt_local`` is the slugified local name of ``e.salt_iri`` and
    ``role_local`` is the (already vocabulary-safe) local name of
    ``e.role_iri``.
    """
    salt_local = slugify(_local(e.salt_iri))
    role_local = _local(e.role_iri)
    return f"msrd:edge-{e.report}-{salt_local}-hasRole-{role_local}"


def reactor_statement_iri(e: ReactorEdge) -> str:
    """Return the deterministic reification-node IRI for a ``ReactorEdge``.

    ``msrd:edge-{report}-{salt_local}-usedIn-reactor-{slug}``, where
    ``salt_local`` is the slugified local name of ``e.salt_iri``.
    """
    salt_local = slugify(_local(e.salt_iri))
    return f"msrd:edge-{e.report}-{salt_local}-usedIn-reactor-{e.reactor_slug}"


def role_edge_triples(e: RoleEdge) -> str:
    """Return the Turtle triple block for one ``RoleEdge`` (no ``INSERT`` wrapper).

    Produces the direct ``msr:hasRole`` edge plus its ``rdf:Statement``
    reification, carrying ``msr:extractionConfidence``/
    ``msr:extractionRationale``, a ``msr:citedIn`` pointer to
    ``e.document_iri``, and stable generation provenance. No blank nodes;
    the reification subject is :func:`role_statement_iri`.
    """
    salt = _term(e.salt_iri)
    role = _term(e.role_iri)
    document = _term(e.document_iri)
    statement = role_statement_iri(e)
    rationale = _escape_literal(e.rationale)
    return (
        f"{salt} msr:hasRole {role} .\n"
        f"{statement} a rdf:Statement ;\n"
        f"    rdf:subject {salt} ;\n"
        f"    rdf:predicate msr:hasRole ;\n"
        f"    rdf:object {role} ;\n"
        f'    msr:extractionConfidence "{e.confidence}"^^xsd:decimal ;\n'
        f'    msr:extractionRationale "{rationale}"^^xsd:string ;\n'
        f"    msr:citedIn {document} ;\n"
        f"    prov:wasGeneratedBy {ACTIVITY_IRI} ;\n"
        f"    prov:wasDerivedFrom {document} ."
    )


def reactor_edge_triples(e: ReactorEdge) -> str:
    """Return the Turtle triple block for one ``ReactorEdge`` (no ``INSERT`` wrapper).

    Produces the minted ``msr:MoltenSaltReactor`` individual (labeled,
    grounded to ``e.grounding_concept_iri`` via ``skos:exactMatch``, and
    carrying stable generation provenance), the direct ``msr:usedIn`` edge,
    and its ``rdf:Statement`` reification carrying
    ``msr:extractionConfidence``/``msr:extractionRationale`` and a
    ``msr:citedIn`` pointer to ``e.document_iri``. No blank nodes; the
    minted reactor subject is :func:`reactor_iri` and the reification
    subject is :func:`reactor_statement_iri`.
    """
    salt = _term(e.salt_iri)
    reactor = reactor_iri(e.reactor_slug)
    grounding = _term(e.grounding_concept_iri)
    document = _term(e.document_iri)
    statement = reactor_statement_iri(e)
    label = _escape_literal(e.reactor_label)
    rationale = _escape_literal(e.rationale)
    return (
        f"{reactor} a msr:MoltenSaltReactor ;\n"
        f'    rdfs:label "{label}"^^xsd:string ;\n'
        f"    skos:exactMatch {grounding} ;\n"
        f"    prov:wasGeneratedBy {ACTIVITY_IRI} ;\n"
        f"    prov:wasDerivedFrom {document} .\n"
        f"{salt} msr:usedIn {reactor} .\n"
        f"{statement} a rdf:Statement ;\n"
        f"    rdf:subject {salt} ;\n"
        f"    rdf:predicate msr:usedIn ;\n"
        f"    rdf:object {reactor} ;\n"
        f'    msr:extractionConfidence "{e.confidence}"^^xsd:decimal ;\n'
        f'    msr:extractionRationale "{rationale}"^^xsd:string ;\n'
        f"    msr:citedIn {document} ;\n"
        f"    prov:wasGeneratedBy {ACTIVITY_IRI} ;\n"
        f"    prov:wasDerivedFrom {document} ."
    )


def insert_data(triples_block: str) -> str:
    """Wrap a triples block in a full SPARQL ``INSERT DATA`` update.

    Includes the required prefix declarations (``msr:``, ``msrd:``,
    ``prov:``, ``xsd:``, ``rdf:``, ``rdfs:``, ``skos:``, ``voc:``) and
    targets ``GRAPH <urn:msr:data>``, matching the additive, graph-scoped
    write contract used by ``mentions.py``.
    """
    indented = "\n".join(f"    {line}" for line in triples_block.splitlines())
    return (
        f"{_PREFIXES}\n"
        "INSERT DATA {\n"
        "  GRAPH <urn:msr:data> {\n"
        f"{indented}\n"
        "  }\n"
        "}"
    )


def asserted_individual_iris(
    role_edges: list[RoleEdge], reactor_edges: list[ReactorEdge]
) -> list[str]:
    """Return the deterministic, de-duplicated, sorted list of newly asserted individuals.

    Covers only the reification nodes (:func:`role_statement_iri`,
    :func:`reactor_statement_iri`) and minted reactor individuals
    (:func:`reactor_iri`) — *not* the direct edges themselves, since those
    connect already-provenanced individuals (the loaded salt and the
    closed-vocabulary role, or the minted reactor which is covered
    separately). Used to build the per-run provenance generation edges.
    """
    iris: set[str] = set()
    for e in role_edges:
        iris.add(role_statement_iri(e))
    for e in reactor_edges:
        iris.add(reactor_iri(e.reactor_slug))
        iris.add(reactor_statement_iri(e))
    return sorted(iris)


def provenance_insert_data(individual_iris: list[str], run_ts: str) -> str:
    """Return the INSERT DATA update writing per-run generation edges.

    For each individual IRI (already sorted for determinism by the
    caller), emits ``<iri> prov:wasGeneratedBy
    <urn:msr:run:extraction/{run_ts}>`` into ``GRAPH <urn:msr:provenance>``.
    """
    run_iri = run_activity_iri(run_ts)
    lines = [f"    {iri} prov:wasGeneratedBy {run_iri} ." for iri in individual_iris]
    body = "\n".join(lines)
    return (
        f"{_PROVENANCE_PREFIXES}\n"
        "INSERT DATA {\n"
        "  GRAPH <urn:msr:provenance> {\n"
        f"{body}\n"
        "  }\n"
        "}"
    )


def write_edges(
    role_edges: list[RoleEdge],
    reactor_edges: list[ReactorEdge],
    client: SparqlClient,
    run_ts: str,
) -> None:
    """Build the ``urn:msr:data`` and ``urn:msr:provenance`` updates and send both.

    Orders role edges by ``(report, salt_iri, role_iri)`` and reactor
    edges by ``(report, salt_iri, reactor_slug)`` for determinism, builds
    one ``urn:msr:data`` ``INSERT DATA`` (all role blocks, then all
    reactor blocks) via :func:`insert_data` and sends it, then builds one
    ``urn:msr:provenance`` ``INSERT DATA`` over
    :func:`asserted_individual_iris` via :func:`provenance_insert_data`
    and sends it. No-op (zero ``client.update`` calls) when both
    ``role_edges`` and ``reactor_edges`` are empty.
    """
    if not role_edges and not reactor_edges:
        return
    ordered_roles = sorted(role_edges, key=lambda e: (e.report, e.salt_iri, e.role_iri))
    ordered_reactors = sorted(
        reactor_edges, key=lambda e: (e.report, e.salt_iri, e.reactor_slug)
    )
    blocks = [role_edge_triples(e) for e in ordered_roles] + [
        reactor_edge_triples(e) for e in ordered_reactors
    ]
    body = "\n\n".join(blocks)
    client.update(insert_data(body))
    iris = asserted_individual_iris(role_edges, reactor_edges)
    client.update(provenance_insert_data(iris, run_ts))
