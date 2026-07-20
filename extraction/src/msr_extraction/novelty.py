"""Novelty-detection miner (novelty-detection spec, design.md D2/D9).

Enumerates candidate terms from two sources without re-running the chunk-6
spaCy linker: (a) a lexical term-candidate pass over the curated
documents' ``segments.jsonl`` text, and (b) the chunk-6
``mentions.jsonl`` artifacts' ``status:"novel"`` records (unresolved
salt-formula spans). Chunk 6's matcher is a rules-only
``spacy.blank("en")`` pipeline that recognizes only seeded labels and
salt-formula-shaped spans, so it never surfaces arbitrary novel
terminology such as ``solubility`` or ``graphite`` -- the lexical pass is
what makes those plain-prose terms discoverable at all.

Before scoring, candidates whose normalized term already resolves to a
known concept/class/individual in the **core dataset** (read through
:class:`msr_extraction.graph_reader.GraphReader`, which itself is
restricted to the three core ``FROM`` graphs) or that chunk 6 already
linked (a ``status:"linked"`` record) are dropped. Staging and proposal
graphs are never consulted -- the reader already excludes them, so this
module deliberately adds no graph parameters of its own.

Surviving candidates are scored by **document frequency**: the number of
the full 637-document OCR corpus (``config.archive_dir``, chunk 5's
LFS-skip clone) whose case-folded text contains the term. Only candidates
at or above ``config.salience_threshold`` are retained. Evidence
(sentence text, source ``Document``, and offsets into that document's
``normalized.txt``) is drawn only from the curated ~12-report set, where
those offsets and ``msr:Document`` nodes exist, even though the frequency
count itself spans all 637 documents.

Everything here is deterministic: no dict-order reliance, all returned
collections sorted for reproducibility. Deliberately stdlib-only at
module level (no third-party imports), mirroring ``mining_types.py`` and
``mine_provenance.py`` -- this module reads only artifacts already on
disk (``segments.jsonl``/``mentions.jsonl``/OCR ``*.txt``) and the graph
via an injected :class:`~msr_extraction.graph_reader.GraphReader`, whose
own third-party (``httpx``) dependency is deferred inside its call, not
imported here.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from msr_extraction.config import Config
from msr_extraction.curated import CURATED_REPORTS
from msr_extraction.graph_reader import GraphReader
from msr_extraction.mining_types import Candidate, Evidence

logger = logging.getLogger(__name__)

#: Document IRI prefix (mirrors ``linker.py``'s ``MSRD``): a report's
#: ``msr:Document`` node is ``f"{MSRD}{report}"``.
MSRD = "https://w3id.org/msr-kg/data#"

#: Small inline English stopword list for the lexical term pass. No NLTK
#: (or any third-party) dependency -- this is deliberately a short,
#: hand-picked list of common function words, not an attempt at a
#: linguistically complete stopword set.
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "was",
        "were",
        "are",
        "been",
        "being",
        "have",
        "has",
        "had",
        "not",
        "but",
        "can",
        "could",
        "would",
        "should",
        "will",
        "shall",
        "may",
        "might",
        "must",
        "than",
        "then",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "these",
        "those",
        "there",
        "their",
        "them",
        "they",
        "its",
        "into",
        "onto",
        "over",
        "under",
        "such",
        "also",
        "each",
        "any",
        "all",
        "some",
        "more",
        "most",
        "other",
        "only",
        "own",
        "same",
        "too",
        "very",
        "just",
        "about",
        "above",
        "after",
        "again",
        "against",
        "between",
        "during",
        "before",
        "below",
        "because",
        "does",
        "did",
        "doing",
    }
)

# Alphabetic tokens (allowing an internal hyphen/apostrophe, e.g.
# "off-gas", "reactor's") -- deliberately excludes anything that is a pure
# number or punctuation-only, since it never matches digit-only or
# punctuation-only runs.
_TOKEN_RE = re.compile(r"[A-Za-z]+(?:[-'][A-Za-z]+)*")

#: n-gram sizes the lexical pass emits (unigrams through trigrams).
_NGRAM_SIZES = (1, 2, 3)


def _read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL artifact into a list of dicts, one per non-blank line."""
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def _tokenize(text: str) -> list[str]:
    """Case-fold `text` into content-word tokens, dropping stopwords/short tokens.

    Pure numbers and punctuation-only runs never match :data:`_TOKEN_RE`
    (it requires at least one alphabetic run), so they are excluded by
    construction; tokens shorter than 3 characters and :data:`_STOPWORDS`
    entries are dropped explicitly.
    """
    tokens = [tok.casefold() for tok in _TOKEN_RE.findall(text)]
    return [tok for tok in tokens if len(tok) >= 3 and tok not in _STOPWORDS]


def _ngrams(tokens: list[str]) -> list[str]:
    """Build deduplicated unigram/bigram/trigram terms from `tokens`, order-preserving."""
    terms: list[str] = []
    seen: set[str] = set()
    for n in _NGRAM_SIZES:
        if n > len(tokens):
            continue
        for i in range(len(tokens) - n + 1):
            term = " ".join(tokens[i : i + n])
            if term not in seen:
                seen.add(term)
                terms.append(term)
    return terms


def enumerate_lexical_terms(reports: list[str], config: Config) -> dict[str, list[Evidence]]:
    """Lexical term-candidate pass over each report's curated `segments.jsonl`.

    Reads each report's ``segments.jsonl`` (the same JSONL shape
    ``linker._read_segments`` consumes: ``report``/``index``/``text``/
    ``char_start``/``char_end`` per line); a missing file is logged as a
    warning and skipped, not an error. Each segment's ``text`` is
    tokenized into case-folded unigrams/bigrams/trigrams (see
    :func:`_tokenize`/:func:`_ngrams`); every surviving term collects one
    :class:`Evidence` per segment it appears in, keyed by ``(report,
    start_offset)`` so a term repeated within one segment (e.g. a bigram
    and its constituent unigram both landing in the same sentence) only
    ever contributes a single evidence item for that segment.

    Returns ``term -> [Evidence, ...]``, both the outer mapping and the
    Evidence lists built without relying on dict iteration order for
    correctness (the caller, :func:`mine_candidates`, sorts its final
    output).
    """
    terms: dict[str, dict[tuple[str, int], Evidence]] = {}
    for report in reports:
        path = config.segments_path(report)
        if not path.exists():
            logger.warning(
                "segments.jsonl missing for report %s at %s; skipping lexical pass",
                report,
                path,
            )
            continue
        document_iri = f"{MSRD}{report}"
        for obj in _read_jsonl(path):
            text = obj["text"]
            char_start = obj["char_start"]
            segment_terms = _ngrams(_tokenize(text))
            if not segment_terms:
                continue
            evidence_key = (report, char_start)
            evidence = Evidence(
                report=report,
                document_iri=document_iri,
                sentence_text=text,
                start_offset=char_start,
                end_offset=char_start + len(text),
            )
            for term in segment_terms:
                bucket = terms.setdefault(term, {})
                bucket.setdefault(evidence_key, evidence)
    return {term: list(bucket.values()) for term, bucket in terms.items()}


def read_miss_candidates(reports: list[str], config: Config) -> list[Candidate]:
    """Read chunk-6 `status:"novel"` records from each report's `mentions.jsonl`.

    Each retained record becomes a ``source="miss"`` :class:`Candidate`
    whose ``term`` is the case-folded, normalized surface form and whose
    ``surface_form`` retains the original text; its single
    :class:`Evidence` item carries the report, document IRI, and the
    record's absolute ``char_start``/``char_end`` offsets. A missing
    ``mentions.jsonl`` is logged as a warning and skipped, not an error.
    """
    candidates: list[Candidate] = []
    for report in reports:
        path = config.mentions_path(report)
        if not path.exists():
            logger.warning(
                "mentions.jsonl missing for report %s at %s; skipping miss pass",
                report,
                path,
            )
            continue
        document_iri = f"{MSRD}{report}"
        for obj in _read_jsonl(path):
            if obj.get("status") != "novel":
                continue
            surface_form = obj["surface_form"]
            evidence = Evidence(
                report=report,
                document_iri=document_iri,
                sentence_text=surface_form or "",
                start_offset=obj["char_start"],
                end_offset=obj["char_end"],
            )
            candidates.append(
                Candidate(
                    term=surface_form.casefold(),
                    source="miss",
                    evidence=(evidence,),
                    surface_form=surface_form,
                )
            )
    return candidates


def build_exclusion_set(reader: GraphReader, reports: list[str], config: Config) -> set[str]:
    """Normalized terms already known to the core dataset or already linked.

    Combines every label of every :class:`~msr_extraction.graph_reader.KnownEntity`
    returned by ``reader.read_known_entities()`` (which is itself
    restricted to the three core ``FROM`` graphs -- staging/proposal
    graphs are never consulted, and this function adds no graph
    parameters of its own) with every ``status:"linked"`` record's
    ``surface_form`` from each report's `mentions.jsonl`. All entries are
    case-folded and stripped so lookups are normalization-consistent with
    :func:`enumerate_lexical_terms`/:func:`read_miss_candidates`.
    """
    excluded: set[str] = set()
    for entity in reader.read_known_entities():
        for label in entity.labels:
            normalized = label.strip().casefold()
            if normalized:
                excluded.add(normalized)

    for report in reports:
        path = config.mentions_path(report)
        if not path.exists():
            logger.warning(
                "mentions.jsonl missing for report %s at %s; skipping exclusion scan",
                report,
                path,
            )
            continue
        for obj in _read_jsonl(path):
            if obj.get("status") != "linked":
                continue
            surface_form = obj.get("surface_form")
            if surface_form:
                excluded.add(surface_form.strip().casefold())
    return excluded


def _build_corpus_index(archive_dir: Path) -> list[str]:
    """Case-folded text of every `*.txt` OCR sidecar under `archive_dir`, read once."""
    texts: list[str] = []
    for path in sorted(archive_dir.rglob("*.txt")):
        try:
            texts.append(path.read_text(encoding="utf-8", errors="ignore").casefold())
        except OSError:
            logger.warning("could not read OCR sidecar %s; excluding from corpus index", path)
    return texts


def score_document_frequency(terms: set[str], config: Config) -> dict[str, int]:
    """Document frequency of each term over the full 637-document OCR corpus.

    Builds the case-folded doc-text index once (via :func:`_build_corpus_index`
    over ``config.archive_dir.rglob("*.txt")``), then counts, per term, how
    many of those documents' text contains it as a case-folded substring.
    If `archive_dir` is missing or has no `.txt` sidecars, logs a warning
    and returns ``{term: 0 for term in terms}`` rather than raising.
    """
    if not terms:
        return {}

    archive_dir = config.archive_dir
    if not archive_dir.exists():
        logger.warning(
            "archive_dir %s does not exist; document-frequency scoring returns 0 for all terms",
            archive_dir,
        )
        return {term: 0 for term in terms}

    corpus_texts = _build_corpus_index(archive_dir)
    if not corpus_texts:
        logger.warning(
            "archive_dir %s has no .txt sidecars; document-frequency scoring returns 0 for all terms",
            archive_dir,
        )
        return {term: 0 for term in terms}

    counts: dict[str, int] = {term: 0 for term in terms}
    for text in corpus_texts:
        for term in terms:
            if term in text:
                counts[term] += 1
    return counts


def mine_candidates(
    config: Config, reader: GraphReader, reports: list[str] = CURATED_REPORTS
) -> list[Candidate]:
    """Enumerate, exclude, score, and retain novelty candidates (the umbrella entry point).

    Pipeline: enumerate lexical terms (:func:`enumerate_lexical_terms`) and
    read chunk-6 misses (:func:`read_miss_candidates`); drop any candidate
    whose normalized term is in :func:`build_exclusion_set`; score the
    surviving terms' document frequency (:func:`score_document_frequency`)
    over the full corpus; keep only candidates at or above
    ``config.salience_threshold``, attaching each kept candidate's
    ``doc_frequency`` and evidence (lexical terms carry the evidence
    collected during enumeration; miss candidates keep the evidence they
    were built with). Returns the retained candidates sorted by ``term``
    for determinism.
    """
    lexical_evidence = enumerate_lexical_terms(reports, config)
    miss_candidates = read_miss_candidates(reports, config)
    exclusion = build_exclusion_set(reader, reports, config)

    surviving_lexical = {
        term: evidence for term, evidence in lexical_evidence.items() if term not in exclusion
    }
    surviving_miss = [candidate for candidate in miss_candidates if candidate.term not in exclusion]

    all_terms = set(surviving_lexical) | {candidate.term for candidate in surviving_miss}
    frequencies = score_document_frequency(all_terms, config)

    retained: list[Candidate] = []
    for term, evidence in surviving_lexical.items():
        doc_frequency = frequencies.get(term, 0)
        if doc_frequency >= config.salience_threshold:
            retained.append(
                Candidate(
                    term=term,
                    source="lexical",
                    evidence=tuple(evidence),
                    doc_frequency=doc_frequency,
                )
            )
    for candidate in surviving_miss:
        doc_frequency = frequencies.get(candidate.term, 0)
        if doc_frequency >= config.salience_threshold:
            retained.append(
                Candidate(
                    term=candidate.term,
                    source=candidate.source,
                    evidence=candidate.evidence,
                    doc_frequency=doc_frequency,
                    surface_form=candidate.surface_form,
                )
            )

    retained.sort(key=lambda candidate: candidate.term)
    return retained
