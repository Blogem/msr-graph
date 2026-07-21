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

from msr_extraction import corpora
from msr_extraction.manifest import ManifestRecord
from msr_extraction.provenance import ACTIVITY_IRI, run_activity_iri
from msr_extraction.safety_manifest import SafetySource
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
            msr:inCorpus msrd:corpus-chemistry ;
            prov:wasGeneratedBy msrd:activity-extraction .

    The IRI ``msrd:{report#}`` is deterministic; no blank nodes are used.
    ``msr:inCorpus`` tags the document with the chemistry corpus
    (``corpora.CORPUS_CHEMISTRY`` -- every ``ManifestRecord`` comes from the
    msr-archive OCR manifest, so the corpus is always chemistry; see
    ``proposal-observation-provenance`` design.md D2 and
    ``msr_extraction.corpora``). ``prov:wasGeneratedBy`` references the
    deterministic extraction-run Activity IRI (design.md D2/D6). Document
    nodes are derivation roots (identified by their real report number), so
    no ``prov:wasDerivedFrom`` is asserted here.
    """
    report_number = record.report_number
    title = _escape_literal(record.title)
    date = _escape_literal(record.date)
    return (
        f"msrd:{report_number} a msr:Document ;\n"
        f'    rdfs:label "{title}" ;\n'
        f'    dcterms:identifier "{report_number}" ;\n'
        f'    dcterms:date "{date}" ;\n'
        f"    msr:inCorpus {corpora.CORPUS_CHEMISTRY} ;\n"
        f"    prov:wasGeneratedBy {ACTIVITY_IRI} ."
    )


def _corpus_individuals_block() -> str:
    """Return ``corpora.corpus_individual_triples()``, indented for embedding.

    Shared by :func:`insert_data_update` and :func:`safety_insert_data_update`
    (task 1.3: emit the two ``msr:Corpus`` individuals into ``urn:msr:data``
    whenever documents are written) and by :func:`_corpus_individuals_insert_data`
    (the standalone update :func:`write_corpus_tags` sends for the D4
    backfill). Declaring both corpus individuals from either writer is
    deliberate and harmless: deterministic IRIs + additive ``INSERT DATA``
    make re-declaring an already-present individual a set-semantics no-op,
    so idempotency holds regardless of which genre's writer runs first.
    """
    triples = corpora.corpus_individual_triples()
    return "\n".join(f"    {line}" for line in triples.splitlines())


def _corpus_individuals_insert_data() -> str:
    """Return a standalone ``INSERT DATA`` update for the two corpus individuals.

    Used by :func:`write_corpus_tags` to ensure ``msrd:corpus-chemistry``/
    ``msrd:corpus-safety`` exist even when it is the first writer to run
    for that corpus. Idempotent for the same reason as
    :func:`_corpus_individuals_block`.
    """
    return (
        f"{corpora._PREFIXES}\n"
        "INSERT DATA {\n"
        "  GRAPH <urn:msr:data> {\n"
        f"{_corpus_individuals_block()}\n"
        "  }\n"
        "}"
    )


def insert_data_update(records: list[ManifestRecord]) -> str:
    """Wrap Document triples for all records in an INSERT DATA update.

    Wraps the concatenated output of :func:`document_triples` for every
    record, plus the two ``msr:Corpus`` individuals
    (:func:`_corpus_individuals_block`, task 1.3), in
    ``INSERT DATA { GRAPH <urn:msr:data> { ... } }``, including the required
    prefix declarations: ``msr:`` (``https://w3id.org/msr-kg/ontology#``),
    ``msrd:`` (``https://w3id.org/msr-kg/data#``), ``rdfs:``, ``dcterms:``,
    and ``prov:``. Folding the corpus individuals into this same update
    (rather than a separate ``client.update`` call) keeps
    :func:`write_documents` at exactly two updates per invocation, unchanged
    from before this task.
    """
    blocks = []
    for record in records:
        triples = document_triples(record)
        indented = "\n".join(f"    {line}" for line in triples.splitlines())
        blocks.append(indented)
    blocks.append(_corpus_individuals_block())
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


def safety_document_triples(source: SafetySource) -> str:
    """Return the Turtle body describing one safety-source Document node.

    Produces (with proper literal escaping)::

        msrd:{id} a msr:Document ;
            rdfs:label "{title}" ;
            dcterms:identifier "{id}" ;
            dcterms:date "{date}" ;
            dcterms:publisher "{publisher}" ;
            dcterms:rights "{rights}" ;
            dcterms:source <{url}> ;
            msr:inCorpus msrd:corpus-safety ;
            prov:wasGeneratedBy msrd:activity-extraction .

    Mirrors :func:`document_triples` (design.md D2/D6), adding the
    safety-genre attribution predicates mandated by D2:
    ``dcterms:publisher``, ``dcterms:rights``, and ``dcterms:source`` (an
    IRI in angle brackets, not a literal, since it is the source URL).
    ``msr:inCorpus`` tags the document with the safety corpus
    (``corpora.CORPUS_SAFETY`` -- every ``SafetySource`` is one of the four
    curated IAEA/GIF/ORNL safety sources; see
    ``proposal-observation-provenance`` design.md D2 and
    ``msr_extraction.corpora``). Safety Document nodes are derivation roots
    exactly like their corpus counterparts, so no ``prov:wasDerivedFrom`` is
    asserted here.
    """
    source_id = source.id
    title = _escape_literal(source.title)
    date = _escape_literal(source.date)
    publisher = _escape_literal(source.publisher)
    rights = _escape_literal(source.rights)
    return (
        f"msrd:{source_id} a msr:Document ;\n"
        f'    rdfs:label "{title}" ;\n'
        f'    dcterms:identifier "{source_id}" ;\n'
        f'    dcterms:date "{date}" ;\n'
        f'    dcterms:publisher "{publisher}" ;\n'
        f'    dcterms:rights "{rights}" ;\n'
        f"    dcterms:source <{source.url}> ;\n"
        f"    msr:inCorpus {corpora.CORPUS_SAFETY} ;\n"
        f"    prov:wasGeneratedBy {ACTIVITY_IRI} ."
    )


def safety_insert_data_update(sources: list[SafetySource]) -> str:
    """Wrap safety Document triples for all sources in an INSERT DATA update.

    Mirrors :func:`insert_data_update`: wraps the concatenated output of
    :func:`safety_document_triples` for every source, plus the two
    ``msr:Corpus`` individuals (:func:`_corpus_individuals_block`, task 1.3),
    in ``INSERT DATA { GRAPH <urn:msr:data> { ... } }``, with the same
    prefix declarations. Folding the corpus individuals into this same
    update keeps :func:`write_safety_documents` at exactly two updates per
    invocation, unchanged from before this task.
    """
    blocks = []
    for source in sources:
        triples = safety_document_triples(source)
        indented = "\n".join(f"    {line}" for line in triples.splitlines())
        blocks.append(indented)
    blocks.append(_corpus_individuals_block())
    body = "\n\n".join(blocks)
    return (
        f"{_PREFIXES}\n"
        "INSERT DATA {\n"
        "  GRAPH <urn:msr:data> {\n"
        f"{body}\n"
        "  }\n"
        "}"
    )


def safety_provenance_insert_data(sources: list[SafetySource], run_ts: str) -> str:
    """Return the INSERT DATA update writing per-run generation edges.

    Mirrors :func:`provenance_insert_data`: for each source, emits
    ``msrd:{id} prov:wasGeneratedBy <urn:msr:run:extraction/{run_ts}>`` into
    ``GRAPH <urn:msr:provenance>``. Callers should only invoke this (and
    send its result) when ``sources`` is non-empty.
    """
    run_iri = run_activity_iri(run_ts)
    lines = [
        f"    msrd:{source.id} prov:wasGeneratedBy {run_iri} ."
        for source in sources
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


def write_safety_documents(
    sources: list[SafetySource], client: SparqlClient, run_ts: str
) -> None:
    """Build the ``urn:msr:data`` and ``urn:msr:provenance`` updates and send both.

    Mirrors :func:`write_documents` for the safety genre: sends the
    ``urn:msr:data`` ``INSERT DATA`` (safety Document triples) via
    :func:`safety_insert_data_update`, then a second ``INSERT DATA`` into
    ``urn:msr:provenance`` via :func:`safety_provenance_insert_data`
    carrying one per-run generation edge per document, keyed by ``run_ts``.
    Additive and idempotent for the ``urn:msr:data`` half: deterministic
    IRIs mean repeated calls with the same sources are a no-op there.
    No-op (no writes at all) when ``sources`` is empty.
    """
    if not sources:
        return
    client.update(safety_insert_data_update(sources))
    client.update(safety_provenance_insert_data(sources, run_ts))


def corpus_tag_insert_data(document_iris: list[str], corpus: str) -> str:
    """Return an ``INSERT DATA`` update tagging existing documents with ``msr:inCorpus``.

    Produces::

        INSERT DATA {
          GRAPH <urn:msr:data> {
            <doc1> msr:inCorpus <corpus> .
            <doc2> msr:inCorpus <corpus> .
          }
        }

    ``document_iris`` are ready-to-use RDF term strings for each document's
    subject position -- either an ``msrd:`` CURIE (e.g.
    ``"msrd:ORNL-TM-2316"``, the same convention :func:`document_triples`/
    :func:`safety_document_triples` use for a document's own subject IRI) or
    a bracketed absolute IRI (e.g.
    ``"<https://w3id.org/msr-kg/data#ORNL-TM-2316>"``) if the caller already
    resolved one from a SPARQL result. This function does not add a prefix
    or angle brackets itself -- pass each entry exactly as it should appear
    in the triple. ``corpus`` is similarly a ready-to-use term, normally
    ``corpora.CORPUS_CHEMISTRY`` or ``corpora.CORPUS_SAFETY``.

    Pure builder, no I/O -- this is the reusable primitive the D4 backfill
    (task 4, a later change) calls to tag an arbitrary set of already-
    existing documents in bulk (task 1.3/4.2). Deterministic and additive:
    re-running with the same inputs is a set-semantics no-op (idempotent),
    matching every other writer in this module. Returns an update whose
    ``GRAPH`` block is empty (but still syntactically valid) when
    ``document_iris`` is empty; callers doing I/O should guard against
    sending a no-op update the way :func:`write_documents` guards on
    ``records`` (see :func:`write_corpus_tags`).
    """
    lines = [f"    {doc_iri} msr:inCorpus {corpus} ." for doc_iri in document_iris]
    body = "\n".join(lines)
    return (
        f"{_PREFIXES}\n"
        "INSERT DATA {\n"
        "  GRAPH <urn:msr:data> {\n"
        f"{body}\n"
        "  }\n"
        "}"
    )


def write_corpus_tags(document_iris: list[str], corpus: str, client: SparqlClient) -> None:
    """Send the corpus-tag INSERT DATA and ensure the corpus individuals exist.

    Thin I/O writer wrapping :func:`corpus_tag_insert_data` (task 1.3/4.2):
    the reusable primitive the D4 backfill calls to tag an arbitrary set of
    already-existing ``msr:Document``s with their corpus, keyed by the same
    ``document_iris``/``corpus`` convention as :func:`corpus_tag_insert_data`
    (see that function's docstring for the exact term format). Also sends
    :func:`_corpus_individuals_insert_data` so ``msrd:corpus-chemistry``/
    ``msrd:corpus-safety`` (label/description) exist even if this is the
    first writer to run for that corpus, mirroring how
    :func:`write_documents`/:func:`write_safety_documents` ensure the same.
    Additive and idempotent: deterministic IRIs, no blank nodes, so
    re-running with the same inputs is a no-op. No-op (no writes at all,
    not even the corpus-individuals write) when ``document_iris`` is empty.
    """
    if not document_iris:
        return
    client.update(corpus_tag_insert_data(document_iris, corpus))
    client.update(_corpus_individuals_insert_data())
