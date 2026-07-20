"""Document provenance node writer.

Emits ``msr:Document`` individuals keyed by report number into the shared
``urn:msr:data`` graph via SPARQL UPDATE (design.md D6). IRIs are
deterministic and there are no blank nodes, so re-running the writer is a
set-semantics no-op. Each written document additionally gets a per-run
generation edge into ``urn:msr:provenance`` (provenance-run-lineage
design.md D1-D3): ``<document> prov:wasGeneratedBy <urn:msr:run:extraction/<ts>>``,
one per document per invocation.
"""

from __future__ import annotations

from msr_extraction.manifest import ManifestRecord
from msr_extraction.provenance import ACTIVITY_IRI, run_activity_iri
from msr_extraction.sparql import SparqlClient

_PREFIXES = """\
PREFIX msr: <https://w3id.org/msr-kg/ontology#>
PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX prov: <http://www.w3.org/ns/prov#>"""

_PROVENANCE_PREFIXES = """\
PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX prov: <http://www.w3.org/ns/prov#>"""


def _escape_literal(s: str) -> str:
    """Escape a string for use inside a double-quoted Turtle/SPARQL literal."""
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )


def document_triples(record: ManifestRecord) -> str:
    """Return the Turtle body describing one Document node.

    Produces (with proper literal escaping)::

        msrd:{report#} a msr:Document ;
            rdfs:label "{title}" ;
            dcterms:identifier "{report#}" ;
            dcterms:date "{date}" ;
            prov:wasGeneratedBy msrd:activity-extraction .

    The IRI ``msrd:{report#}`` is deterministic; no blank nodes are used.
    ``prov:wasGeneratedBy`` references the deterministic extraction-run
    Activity IRI (design.md D2/D6). Document nodes are derivation roots
    (identified by their real report number), so no ``prov:wasDerivedFrom``
    is asserted here.
    """
    report_number = record.report_number
    title = _escape_literal(record.title)
    date = _escape_literal(record.date)
    return (
        f"msrd:{report_number} a msr:Document ;\n"
        f'    rdfs:label "{title}" ;\n'
        f'    dcterms:identifier "{report_number}" ;\n'
        f'    dcterms:date "{date}" ;\n'
        f"    prov:wasGeneratedBy {ACTIVITY_IRI} ."
    )


def insert_data_update(records: list[ManifestRecord]) -> str:
    """Wrap Document triples for all records in an INSERT DATA update.

    Wraps the concatenated output of :func:`document_triples` for every
    record in ``INSERT DATA { GRAPH <urn:msr:data> { ... } }``, including
    the required prefix declarations: ``msr:``
    (``https://w3id.org/msr-kg/ontology#``), ``msrd:``
    (``https://w3id.org/msr-kg/data#``), ``rdfs:``, ``dcterms:``, and
    ``prov:``.
    """
    blocks = []
    for record in records:
        triples = document_triples(record)
        indented = "\n".join(f"    {line}" for line in triples.splitlines())
        blocks.append(indented)
    body = "\n\n".join(blocks)
    return (
        f"{_PREFIXES}\n"
        "INSERT DATA {\n"
        "  GRAPH <urn:msr:data> {\n"
        f"{body}\n"
        "  }\n"
        "}"
    )


def provenance_insert_data(records: list[ManifestRecord], run_ts: str) -> str:
    """Return the INSERT DATA update writing per-run generation edges.

    For each record, emits ``msrd:{report_number} prov:wasGeneratedBy
    <urn:msr:run:extraction/{run_ts}>`` into ``GRAPH <urn:msr:provenance>``.
    The subject reuses the exact ``msrd:{report_number}`` CURIE the stable
    ``urn:msr:data`` block uses. Callers should only invoke this (and send
    its result) when ``records`` is non-empty.
    """
    run_iri = run_activity_iri(run_ts)
    lines = [
        f"    msrd:{record.report_number} prov:wasGeneratedBy {run_iri} ."
        for record in records
    ]
    body = "\n".join(lines)
    return (
        f"{_PROVENANCE_PREFIXES}\n"
        "INSERT DATA {\n"
        "  GRAPH <urn:msr:provenance> {\n"
        f"{body}\n"
        "  }\n"
        "}"
    )


def write_documents(records: list[ManifestRecord], client: SparqlClient, run_ts: str) -> None:
    """Build the ``urn:msr:data`` and ``urn:msr:provenance`` updates and send both.

    Sends the existing ``urn:msr:data`` ``INSERT DATA`` (document triples,
    unchanged — each still carries the stable ``prov:wasGeneratedBy
    msrd:activity-extraction`` edge) via :func:`insert_data_update`, then a
    second ``INSERT DATA`` into ``urn:msr:provenance`` via
    :func:`provenance_insert_data` carrying one per-run generation edge per
    document, keyed by ``run_ts`` (provenance-run-lineage design.md D1-D3).
    Additive and idempotent for the ``urn:msr:data`` half: deterministic
    IRIs mean repeated calls with the same records are a no-op there.
    No-op (no writes at all) when ``records`` is empty.
    """
    if not records:
        return
    client.update(insert_data_update(records))
    client.update(provenance_insert_data(records, run_ts))
