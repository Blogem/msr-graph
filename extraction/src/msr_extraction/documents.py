"""Document provenance node writer.

Emits ``msr:Document`` individuals keyed by report number into the shared
``urn:msr:data`` graph via SPARQL UPDATE (design.md D6). IRIs are
deterministic and there are no blank nodes, so re-running the writer is a
set-semantics no-op.
"""

from __future__ import annotations

from msr_extraction.manifest import ManifestRecord
from msr_extraction.provenance import ACTIVITY_IRI
from msr_extraction.sparql import SparqlClient

_PREFIXES = """\
PREFIX msr: <https://w3id.org/msr-kg/ontology#>
PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX dcterms: <http://purl.org/dc/terms/>
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


def write_documents(records: list[ManifestRecord], client: SparqlClient) -> None:
    """Build the INSERT DATA update for records and send it via client.

    Builds the update via :func:`insert_data_update` and sends it with
    ``client.update``. Additive and idempotent: deterministic IRIs mean
    repeated calls with the same records are a no-op.
    """
    if not records:
        return
    client.update(insert_data_update(records))
