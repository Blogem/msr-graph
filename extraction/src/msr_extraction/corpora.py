"""Corpus vocabulary: the single source of truth for corpus IRIs and derivation.

``proposal-observation-provenance`` design.md D2 introduces ``msr:Corpus`` as
a first-class resource so that a proposal's per-document observations can
group and aggregate by corpus in SPARQL, and so the corpus badge/label the
reviewer sees has somewhere to live. Today there are exactly two corpora:

- the msr-archive OCR corpus (chemistry genre, ``config.archive_dir``, ~637
  reports) -> :data:`CORPUS_CHEMISTRY`
- the IAEA/GIF/ORNL safety corpus (safety genre, ``config.safety_dir``, a
  handful of curated sources) -> :data:`CORPUS_SAFETY`

Every module that needs a corpus IRI or the genre-to-corpus mapping
(``documents.py`` when tagging a written ``msr:Document`` with
``msr:inCorpus``, ``novelty.py`` when stamping a candidate's per-document
:class:`~msr_extraction.mining_types.Observation`, ``proposals.py`` when
writing observation nodes, and the D4 backfill migration) imports from this
module rather than re-deriving or hard-coding the mapping, so the corpus
model can never drift between call sites.

Deliberately stdlib-only (no third-party imports, no imports of sibling
project modules) so this module has zero import-time dependencies, mirroring
``mining_types.py`` and ``provenance.py``.
"""

from __future__ import annotations

#: The msr-archive OCR corpus (chemistry genre) as a first-class
#: ``msr:Corpus`` individual, expressed as an ``msrd:`` CURIE (design.md D2).
CORPUS_CHEMISTRY = "msrd:corpus-chemistry"

#: The IAEA/GIF/ORNL safety corpus (safety genre) as a first-class
#: ``msr:Corpus`` individual, expressed as an ``msrd:`` CURIE (design.md D2).
CORPUS_SAFETY = "msrd:corpus-safety"

#: Turtle prefixes required by :func:`corpus_individual_triples`, matching
#: the declaration order/style ``documents.py``'s ``_PREFIXES`` uses.
_PREFIXES = """\
PREFIX msr: <https://w3id.org/msr-kg/ontology#>
PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX dcterms: <http://purl.org/dc/terms/>"""


def corpus_for_genre(genre: str) -> str:
    """Return the corpus CURIE a pipeline ``genre`` string belongs to.

    ``genre="safety"`` maps to :data:`CORPUS_SAFETY`; every other value
    (including the ``"chemistry"`` default used throughout ``novelty.py``/
    ``mine_runner.py``/``cli.py``, and any unrecognized string) maps to
    :data:`CORPUS_CHEMISTRY`. This function is deterministic and total: it
    never raises, even on an unknown ``genre`` -- callers that pass a typo'd
    or future genre string silently get the chemistry corpus rather than an
    exception, which is intentional (corpus tagging must never be the thing
    that crashes a mining/extraction run). Callers that need to distinguish
    "unknown genre" from "chemistry" should validate ``genre`` themselves
    before calling this.
    """
    if genre == "safety":
        return CORPUS_SAFETY
    return CORPUS_CHEMISTRY


def corpus_for_document(genre: str) -> str:
    """Return the corpus CURIE for a document processed under ``genre``.

    Thin alias of :func:`corpus_for_genre` for call sites that are tagging a
    specific ``msr:Document`` (``documents.py``'s writers, the D4 backfill)
    rather than reasoning about the pipeline genre in the abstract --
    reads more naturally as "this document's corpus is ...". Every document
    the pipeline writes is processed under exactly one genre for its whole
    lifetime (chemistry archive reports vs. the four safety sources), so the
    genre alone is sufficient to derive the corpus; no per-document
    override is needed.
    """
    return corpus_for_genre(genre)


def corpus_individual_triples() -> str:
    """Return the Turtle body declaring the two ``msr:Corpus`` individuals.

    Produces (with the required prefixes)::

        msrd:corpus-chemistry a msr:Corpus ;
            rdfs:label "msr-archive chemistry corpus" ;
            dcterms:description "..." .

        msrd:corpus-safety a msr:Corpus ;
            rdfs:label "IAEA/GIF/ORNL safety corpus" ;
            dcterms:description "..." .

    Both IRIs are deterministic and no blank nodes are used, so wrapping
    this body in an ``INSERT DATA`` (mirroring ``documents.py``'s
    ``insert_data_update``) is a set-semantics no-op on re-run: re-writing
    the same two individuals never duplicates or drifts them. This function
    returns only the triple body (not a full ``INSERT DATA`` update) so
    callers can compose it with other bundles the same way
    ``documents.py``'s ``document_triples``/``safety_document_triples`` do;
    :data:`_PREFIXES` documents the prefixes a caller must declare when
    wrapping this body in an update.
    """
    return (
        f"{CORPUS_CHEMISTRY} a msr:Corpus ;\n"
        '    rdfs:label "msr-archive chemistry corpus" ;\n'
        '    dcterms:description "The chemistry-genre OCR corpus of msr-archive '
        'molten-salt-reactor reports (config.archive_dir)." .\n'
        "\n"
        f"{CORPUS_SAFETY} a msr:Corpus ;\n"
        '    rdfs:label "IAEA/GIF/ORNL safety corpus" ;\n'
        '    dcterms:description "The safety-genre corpus of curated IAEA/GIF/ORNL '
        'molten-salt-reactor safety sources (config.safety_dir)." .'
    )
