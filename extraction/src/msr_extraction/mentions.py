"""Linked-mention triple emission and graph writer.

Emits ``msr:Mention`` individuals for linked spans into the shared
``urn:msr:data`` graph via additive SPARQL UPDATE (design.md D7, D8).
IRIs are deterministic (``msrd:mention-{report#}-{start}-{end}``) and
there are no blank nodes, so re-running the writer over the same
mentions is a set-semantics no-op. Each written mention additionally gets
a per-run generation edge into ``urn:msr:provenance`` (provenance-run-lineage
design.md D1-D3): ``<mention> prov:wasGeneratedBy <urn:msr:run:extraction/<ts>>``,
one per mention per invocation, so per-run lineage accumulates without
touching the idempotent ``urn:msr:data`` block.
"""

from __future__ import annotations

from dataclasses import dataclass

from msr_extraction.provenance import ACTIVITY_IRI, run_activity_iri
from msr_extraction.sparql import SparqlClient

MSR = "https://w3id.org/msr-kg/ontology#"
MSRD = "https://w3id.org/msr-kg/data#"
XSD = "http://www.w3.org/2001/XMLSchema#"

# Default mentions per INSERT DATA POST (scale-mention-linking D1). Each
# mention block is a few hundred bytes, so 500 keeps a POST body well under
# GraphDB's Tomcat maxPostSize; a single unbatched POST of a large report
# (~3.8k mentions, ~1.9 MB) otherwise exceeds it and is rejected with a 500.
DEFAULT_MENTION_BATCH_SIZE = 500

_PREFIXES = """\
PREFIX msr: <https://w3id.org/msr-kg/ontology#>
PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>"""

_PROVENANCE_PREFIXES = """\
PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX prov: <http://www.w3.org/ns/prov#>"""


@dataclass(frozen=True)
class Mention:
    """A single linked text span, ready to be written to the graph."""

    report: str
    start: int
    end: int
    surface_form: str
    target_iri: str
    document_iri: str


def _escape_literal(s: str) -> str:
    """Escape a string for use inside a double-quoted Turtle/SPARQL literal."""
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
    )


def mention_iri(report: str, start: int, end: int) -> str:
    """Return the deterministic ``msrd:`` CURIE for a mention (design.md D7).

    ``msrd:mention-{report#}-{start}-{end}`` — offsets are into the
    chunk-5 ``normalized.txt`` for ``report``.
    """
    return f"msrd:mention-{report}-{start}-{end}"


def mention_triples(m: Mention) -> str:
    """Return the Turtle triple block for one mention (no ``INSERT`` wrapper).

    Produces (with proper literal escaping)::

        msrd:mention-{report}-{start}-{end} a msr:Mention ;
            msr:linksTo <{target_iri}> ;
            msr:inDocument <{document_iri}> ;
            msr:surfaceForm "{surface}"^^xsd:string ;
            msr:startOffset "{start}"^^xsd:integer ;
            msr:endOffset "{end}"^^xsd:integer ;
            prov:wasGeneratedBy msrd:activity-extraction ;
            prov:wasDerivedFrom <{document_iri}> .

    The subject IRI is deterministic (:func:`mention_iri`); no blank nodes
    are used. ``linksTo``/``inDocument`` objects are full IRIs written in
    ``<...>`` form (not CURIEs) to avoid ambiguity across the
    vocab/ontology/data namespaces. ``prov:wasGeneratedBy`` references the
    deterministic extraction-run Activity IRI (design.md D2/D6). A literal
    ``prov:wasDerivedFrom`` pointing at the same ``document_iri`` as
    ``msr:inDocument`` is also asserted, so a PROV-only consumer (e.g. the
    chunk-13 SHACL shapes) can traverse the mention's derivation edge
    without knowing about ``msr:inDocument``; ``document_iri`` is
    deterministic, so this block remains idempotent.
    """
    subject = mention_iri(m.report, m.start, m.end)
    surface = _escape_literal(m.surface_form)
    return (
        f"{subject} a msr:Mention ;\n"
        f"    msr:linksTo <{m.target_iri}> ;\n"
        f"    msr:inDocument <{m.document_iri}> ;\n"
        f'    msr:surfaceForm "{surface}"^^xsd:string ;\n'
        f'    msr:startOffset "{m.start}"^^xsd:integer ;\n'
        f'    msr:endOffset "{m.end}"^^xsd:integer ;\n'
        f"    prov:wasGeneratedBy {ACTIVITY_IRI} ;\n"
        f"    prov:wasDerivedFrom <{m.document_iri}> ."
    )


def insert_data(triples_block: str) -> str:
    """Wrap a triples block in a full SPARQL ``INSERT DATA`` update.

    Includes the required prefix declarations (``msr:``, ``msrd:``,
    ``xsd:``) and targets ``GRAPH <urn:msr:data>``, matching the additive,
    graph-scoped write contract of design.md D7/D8.
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


def provenance_insert_data(mentions: list[Mention], run_ts: str) -> str:
    """Return the INSERT DATA update writing per-run generation edges.

    For each mention (sorted by ``(report, start, end)`` for determinism),
    emits ``<mention-iri> prov:wasGeneratedBy <urn:msr:run:extraction/{run_ts}>``
    into ``GRAPH <urn:msr:provenance>``. The subject reuses the exact
    ``msrd:mention-...`` CURIE form produced by :func:`mention_iri` — the
    same subject the stable ``urn:msr:data`` block uses. Callers should
    only invoke this (and send its result) when ``mentions`` is non-empty.
    """
    ordered = sorted(mentions, key=lambda m: (m.report, m.start, m.end))
    run_iri = run_activity_iri(run_ts)
    lines = [
        f"    {mention_iri(m.report, m.start, m.end)} prov:wasGeneratedBy {run_iri} ."
        for m in ordered
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


def write_mentions(
    mentions: list[Mention],
    client: SparqlClient,
    run_ts: str,
    *,
    batch_size: int = DEFAULT_MENTION_BATCH_SIZE,
) -> None:
    """Build the ``urn:msr:data`` and ``urn:msr:provenance`` updates and send them.

    Sends the ``urn:msr:data`` ``INSERT DATA`` (mention triples, each carrying
    the stable ``prov:wasGeneratedBy msrd:activity-extraction`` edge) via
    :func:`insert_data`, then the ``urn:msr:provenance`` ``INSERT DATA`` via
    :func:`provenance_insert_data` carrying one per-run generation edge per
    mention, keyed by ``run_ts`` (provenance-run-lineage design.md D1-D3).

    To keep any single POST body under GraphDB's Tomcat ``maxPostSize``
    (scale-mention-linking D1), the mentions are split into batches of at most
    ``batch_size``: one ``urn:msr:data`` request per batch is sent first, then
    one ``urn:msr:provenance`` request per batch. Every batch is additive
    ``INSERT DATA`` over deterministic, blank-node-free IRIs, so the union of
    batches is identical to a single unbatched write — batching changes only
    the number of requests, never the resulting triples or the re-run
    idempotency of ``urn:msr:data``. All batches order mentions by
    ``(report, start, end)`` for determinism. No-op (no writes at all) when
    ``mentions`` is empty.
    """
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")
    if not mentions:
        return
    ordered = sorted(mentions, key=lambda m: (m.report, m.start, m.end))
    batches = [ordered[i : i + batch_size] for i in range(0, len(ordered), batch_size)]
    for batch in batches:
        body = "\n\n".join(mention_triples(m) for m in batch)
        client.update(insert_data(body))
    for batch in batches:
        client.update(provenance_insert_data(batch, run_ts))
