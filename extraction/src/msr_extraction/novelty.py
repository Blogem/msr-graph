"""Novelty-detection miner (novelty-detection spec, refine-mine-salience design.md D1/D5).

Enumerates candidate terms from two sources without re-running the chunk-6
spaCy linker: (a) a **spaCy noun-chunk pass** (:func:`enumerate_spacy_terms`)
over the curated documents' ``segments.jsonl`` text -- content tokens kept
only when alphabetic, non-stopword, length >= 3, and not part of a
non-concept named entity, lemmatized, 1-3 surviving tokens per chunk -- and
(b) the chunk-6 ``mentions.jsonl`` artifacts' ``status:"novel"`` records
(unresolved salt-formula spans, unchanged). If the spaCy model cannot be
loaded (:func:`load_spacy_pipeline` returns ``None``), the miner falls back
to the prior lexical unigram/bigram/trigram pass
(:func:`enumerate_lexical_terms`, kept intact for exactly this purpose)
rather than failing (design D5). Chunk 6's matcher is a rules-only
``spacy.blank("en")`` pipeline that recognizes only seeded labels and
salt-formula-shaped spans, so it never surfaces arbitrary novel
terminology such as ``solubility`` or ``graphite`` -- the spaCy/lexical pass
is what makes those plain-prose terms discoverable at all.

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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

#: Named-entity types whose tokens are dropped from a spaCy noun chunk
#: (design D1): people, organizations, places, and non-concept numeric/
#: temporal entity types. A token survives only when spaCy assigns it
#: `ent_type_ == ""` (not part of any entity) or an entity type outside
#: this set.
_DROPPED_ENT_TYPES = frozenset(
    {
        "PERSON",
        "ORG",
        "GPE",
        "LOC",
        "FAC",
        "NORP",
        "DATE",
        "TIME",
        "CARDINAL",
        "ORDINAL",
        "MONEY",
        "PERCENT",
        "QUANTITY",
    }
)

#: spaCy pipeline components :func:`load_spacy_pipeline` keeps enabled
#: (design D1/1.2): `tok2vec` feeds every statistical component below it;
#: `tagger`/`attribute_ruler`/`lemmatizer` produce the lemmas
#: :func:`enumerate_spacy_terms` forms candidates from; `parser` (or
#: `senter`, kept if present) is what makes `doc.noun_chunks` available;
#: `ner` is the entity-type filter above. Any OTHER component the loaded
#: model happens to ship (e.g. a `textcat`) is disabled for perf, since
#: none of this module's logic consults it.
_KEEP_PIPES = frozenset(
    {"tok2vec", "tagger", "attribute_ruler", "lemmatizer", "parser", "senter", "ner"}
)

#: Maximum surviving-token window a single noun chunk contributes to a
#: candidate term (design D1: "form the candidate from 1-3 surviving
#: tokens"). A chunk with more than 3 surviving content tokens keeps only
#: the TRAILING `_MAX_CHUNK_TOKENS` of them: English noun-phrase heads are
#: overwhelmingly chunk-final (e.g. "molten salt reactor coolant" is
#: headed by "coolant"), so the trailing window is a deterministic,
#: reasonable proxy for "the head plus its nearest modifiers" without
#: inspecting `noun_chunk.root` explicitly (an assumption worth
#: reconsidering if it under-performs in practice).
_MAX_CHUNK_TOKENS = 3


def load_spacy_pipeline(config: Config) -> Any | None:
    """Lazily load the injectable spaCy pipeline used for noun-chunk enumeration.

    Deferred import (``import spacy``) so this module stays importable with
    zero third-party dependencies even when spaCy or its pinned model
    (``config.spacy_model``, default ``en_core_web_sm``) is unavailable
    (design D5) -- mirrors the ``import spacy``-inside-the-function
    convention already used by ``seeding.py``/``triage.py``.

    On any load failure (spaCy not installed, or the named model's data not
    present), logs a clear error and returns ``None`` -- the sentinel every
    caller (:func:`mine_candidates`) MUST treat as "fall back to the n-gram
    pass" rather than raising. On success, disables every pipeline
    component NOT in :data:`_KEEP_PIPES` (perf; design D1's "disable unused
    components where safe") and returns the loaded, trimmed pipeline.
    """
    try:
        import spacy
    except ImportError:
        logger.error(
            "spacy is not installed; falling back to n-gram candidate enumeration"
        )
        return None

    try:
        nlp = spacy.load(config.spacy_model)
    except OSError:
        logger.error(
            "spaCy model %r could not be loaded (missing model data?); "
            "falling back to n-gram candidate enumeration",
            config.spacy_model,
        )
        return None

    for name in list(nlp.pipe_names):
        if name not in _KEEP_PIPES:
            nlp.disable_pipe(name)
    return nlp


@dataclass(frozen=True)
class _SpacyTermHit:
    """One spaCy-enumerated term's collected evidence and representative surface form."""

    evidence: tuple[Evidence, ...]
    #: The shortest, then lexicographically-first, original chunk text
    #: observed for this term -- deterministic regardless of segment
    #: processing order (see :func:`enumerate_spacy_terms`).
    surface_form: str


def _surviving_chunk_tokens(chunk: Any) -> list[Any]:
    """Content tokens of spaCy `chunk` surviving the design-D1 filters, in order.

    Kept: alphabetic (`token.is_alpha`), non-stopword (`not
    token.is_stop`), length >= 3, and not part of a dropped-type named
    entity (`token.ent_type_` empty or outside :data:`_DROPPED_ENT_TYPES`).
    """
    survivors = []
    for token in chunk:
        if not token.is_alpha:
            continue
        if token.is_stop:
            continue
        if len(token.text) < 3:
            continue
        if token.ent_type_ in _DROPPED_ENT_TYPES:
            continue
        survivors.append(token)
    return survivors


def enumerate_spacy_terms(
    reports: list[str], config: Config, nlp: Any
) -> dict[str, _SpacyTermHit]:
    """spaCy noun-chunk candidate pass over each report's curated `segments.jsonl` (design D1).

    Reads each report's ``segments.jsonl`` exactly like
    :func:`enumerate_lexical_terms` (a missing file is a logged warning, not
    an error) so candidates carry identical :class:`Evidence` (report,
    document IRI, full segment ``sentence_text``, offsets) to the lexical
    pass. Runs every segment's text through `nlp.pipe` in one batch (perf);
    for each `doc.noun_chunks` entry, keeps only the surviving tokens
    (:func:`_surviving_chunk_tokens`) -- a chunk that reduces to zero
    surviving tokens contributes no candidate. Surviving tokens beyond
    :data:`_MAX_CHUNK_TOKENS` are trimmed to the trailing window; the
    candidate ``term`` is the casefolded, space-joined lemma sequence, and
    its ``surface_form`` is the original (untrimmed) chunk text.

    A term's evidence is deduplicated per segment exactly like the lexical
    pass (:data:`evidence_key` = ``(report, char_start)``); its
    `surface_form` is picked deterministically (shortest, then
    lexicographically-first observed chunk text for that term) since the
    same lemma-normalized term can surface from differently-worded chunks
    across segments/reports.

    Returns ``term -> _SpacyTermHit``, built without relying on dict
    iteration order (the caller, :func:`mine_candidates`, sorts its final
    output).
    """
    segment_meta: list[tuple[str, str, int, str]] = []
    for report in reports:
        path = config.segments_path(report)
        if not path.exists():
            logger.warning(
                "segments.jsonl missing for report %s at %s; skipping spaCy pass",
                report,
                path,
            )
            continue
        document_iri = f"{MSRD}{report}"
        for obj in _read_jsonl(path):
            segment_meta.append((report, document_iri, obj["char_start"], obj["text"]))

    evidence_by_term: dict[str, dict[tuple[str, int], Evidence]] = {}
    surface_forms_by_term: dict[str, set[str]] = {}

    texts = [text for (_, _, _, text) in segment_meta]
    docs = nlp.pipe(texts)
    for (report, document_iri, char_start, text), doc in zip(segment_meta, docs):
        evidence_key = (report, char_start)
        evidence = Evidence(
            report=report,
            document_iri=document_iri,
            sentence_text=text,
            start_offset=char_start,
            end_offset=char_start + len(text),
        )
        for chunk in doc.noun_chunks:
            survivors = _surviving_chunk_tokens(chunk)
            if not survivors:
                continue
            if len(survivors) > _MAX_CHUNK_TOKENS:
                survivors = survivors[-_MAX_CHUNK_TOKENS:]
            term = " ".join(tok.lemma_.casefold() for tok in survivors)
            if not term:
                continue
            evidence_bucket = evidence_by_term.setdefault(term, {})
            evidence_bucket.setdefault(evidence_key, evidence)
            surface_forms_by_term.setdefault(term, set()).add(chunk.text)

    return {
        term: _SpacyTermHit(
            evidence=tuple(evidence_bucket.values()),
            surface_form=min(surface_forms_by_term[term], key=lambda s: (len(s), s)),
        )
        for term, evidence_bucket in evidence_by_term.items()
    }


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


def _terms_in_text(text: str) -> list[str]:
    """Normalize `text` into its deduplicated n-gram terms (`_tokenize` + `_ngrams`).

    Shared by :func:`enumerate_lexical_terms` (candidate-term generation)
    and :func:`score_document_frequency` (per-document term generation) so
    both sides of the document-frequency membership check are produced by
    byte-identical normalization/filtering -- candidate terms and
    per-document terms can never drift apart in form.
    """
    return _ngrams(_tokenize(text))


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
            segment_terms = _terms_in_text(text)
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
    over ``config.archive_dir.rglob("*.txt")``); for each document, generates
    that document's own set of normalized n-gram terms via :func:`_terms_in_text`
    -- the *same* ``_tokenize`` + ``_ngrams`` path :func:`enumerate_lexical_terms`
    uses to build candidate terms -- and intersects it against `terms` in one
    hash-set operation, incrementing each matched term's count. This is
    O(docs * doc_ngrams) with O(1) hash lookups per document, independent of
    the candidate-set size, instead of the naive O(docs * terms * doclen)
    substring scan (``for text in corpus: for term in terms: term in text``),
    which is unusable at the full lexical-pass scale (hundreds of thousands
    of candidate terms over 637 documents took hours).

    Semantics note: because both sides come from the same normalized-token
    n-gram path, this is exact-match membership on normalized token n-grams,
    NOT substring containment. A term like ``"solubility"`` no longer
    incidentally matches inside ``"solubilities"`` -- this is the intended,
    more precise "token scan" reading. Counts may differ slightly from the
    old substring-based counts; the default ``salience_threshold`` (50) is
    robust to that shift.

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

    total_docs = len(corpus_texts)
    logger.info("scoring %d candidate terms over %d documents", len(terms), total_docs)
    counts: dict[str, int] = {term: 0 for term in terms}
    for doc_index, text in enumerate(corpus_texts, start=1):
        doc_terms = set(_terms_in_text(text))
        for term in doc_terms & terms:
            counts[term] += 1
        if doc_index % 100 == 0:
            logger.info("scored %d/%d documents", doc_index, total_docs)
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
