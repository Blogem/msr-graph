"""Document provenance node writer.

Emits ``msr:Document`` individuals keyed by report number into the shared
``urn:msr:data`` graph via SPARQL UPDATE (design.md D6). IRIs are
deterministic and there are no blank nodes, so re-running the writer is a
set-semantics no-op.
"""

from __future__ import annotations

from msr_extraction.manifest import ManifestRecord
from msr_extraction.sparql import SparqlClient


def document_triples(record: ManifestRecord) -> str:
    """Return the Turtle body describing one Document node.

    Produces (with proper literal escaping)::

        msrd:{report#} a msr:Document ;
            rdfs:label "{title}" ;
            dcterms:identifier "{report#}" ;
            dcterms:date "{date}" .

    The IRI ``msrd:{report#}`` is deterministic; no blank nodes are used.
    """
    raise NotImplementedError("task 7.2")


def insert_data_update(records: list[ManifestRecord]) -> str:
    """Wrap Document triples for all records in an INSERT DATA update.

    Wraps the concatenated output of :func:`document_triples` for every
    record in ``INSERT DATA { GRAPH <urn:msr:data> { ... } }``, including
    the required prefix declarations: ``msr:``
    (``https://w3id.org/msr-kg/ontology#``), ``msrd:``
    (``https://w3id.org/msr-kg/data#``), ``rdfs:``, and ``dcterms:``.
    """
    raise NotImplementedError("task 7.2")


def write_documents(records: list[ManifestRecord], client: SparqlClient) -> None:
    """Build the INSERT DATA update for records and send it via client.

    Builds the update via :func:`insert_data_update` and sends it with
    ``client.update``. Additive and idempotent: deterministic IRIs mean
    repeated calls with the same records are a no-op.
    """
    raise NotImplementedError("task 7.2")
