"""Linked-mention triple emission and graph writer.

Emits ``msr:Mention`` individuals for linked spans into the shared
``urn:msr:data`` graph via additive SPARQL UPDATE (design.md D7, D8).
IRIs are deterministic (``msrd:mention-{report#}-{start}-{end}``) and
there are no blank nodes, so re-running the writer over the same
mentions is a set-semantics no-op.
"""

from __future__ import annotations

from dataclasses import dataclass

from msr_extraction.sparql import SparqlClient

MSR = "https://w3id.org/msr-kg/ontology#"
MSRD = "https://w3id.org/msr-kg/data#"
XSD = "http://www.w3.org/2001/XMLSchema#"

_PREFIXES = """\
PREFIX msr: <https://w3id.org/msr-kg/ontology#>
PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>"""


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
            msr:endOffset "{end}"^^xsd:integer .

    The subject IRI is deterministic (:func:`mention_iri`); no blank nodes
    are used. ``linksTo``/``inDocument`` objects are full IRIs written in
    ``<...>`` form (not CURIEs) to avoid ambiguity across the
    vocab/ontology/data namespaces.
    """
    subject = mention_iri(m.report, m.start, m.end)
    surface = _escape_literal(m.surface_form)
    return (
        f"{subject} a msr:Mention ;\n"
        f"    msr:linksTo <{m.target_iri}> ;\n"
        f"    msr:inDocument <{m.document_iri}> ;\n"
        f'    msr:surfaceForm "{surface}"^^xsd:string ;\n'
        f'    msr:startOffset "{m.start}"^^xsd:integer ;\n'
        f'    msr:endOffset "{m.end}"^^xsd:integer .'
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


def write_mentions(mentions: list[Mention], client: SparqlClient) -> None:
    """Build one INSERT DATA update over all mentions and send it via client.

    Mentions are sorted by ``(report, start, end)`` first so the emitted
    update is deterministic. Additive and idempotent: deterministic IRIs
    and no blank nodes mean repeated calls with the same mentions are a
    graph no-op.
    """
    if not mentions:
        return
    ordered = sorted(mentions, key=lambda m: (m.report, m.start, m.end))
    blocks = [mention_triples(m) for m in ordered]
    body = "\n\n".join(blocks)
    client.update(insert_data(body))
