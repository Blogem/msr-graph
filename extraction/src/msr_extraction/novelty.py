"""Novelty-detection miner (novelty-detection spec, refine-mine-salience design.md D1-D3/D5).

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

**Genre-aware mining (chunk 11 / ingest-iaea-safety D3, task 3.1).**
:func:`mine_candidates`/:func:`enumerate_spacy_terms` take a keyword-only
``genre`` (default ``"chemistry"``, byte-identical to this module's
pre-chunk-11 behavior). ``genre="safety"`` (a) relaxes the noun-chunk
survivor window from :data:`_MAX_CHUNK_TOKENS` (3) to
``config.safety_max_chunk_tokens`` (6) and preserves the noun-chunk head
phrase's intervening stopwords/prepositions (:func:`_survivor_span_tokens`)
so prepositional safety concepts ("confinement of radioactive material",
"removal of residual heat") survive candidate enumeration as multi-word
phrases rather than being reduced to a stopword-stripped lemma join; and
(b) reads segments from ``config.safety_segments_path(report)`` and scores
document frequency over ``config.safety_dir`` instead of the chemistry
corpus paths (``config.segments_path``/``config.archive_dir``). The DF
floor/ceiling values, the known/linked exclusion mechanism
(:func:`build_exclusion_set`), and the curated-set evidence-sentence
capture are reused unchanged by both genres.

Before scoring, candidates whose normalized term already resolves to a known
concept/class/individual in the **core dataset** (read through
:class:`msr_extraction.graph_reader.GraphReader`, which itself is restricted
to the three core ``FROM`` graphs -- SKOS concepts incl. reactor concepts,
ontology classes, physical properties, salts, and chunk-7's salt-role
labels) or that chunk 6 already linked (a ``status:"linked"`` record) are
dropped. Exclusion is normalization/token-sequence aware (design D2): both
candidate terms and known labels are casefolded, camelCase-split, and
separator-collapsed into a token sequence, and a candidate is excluded when
some known label's *full* token sequence is a contiguous run within the
candidate's (so ``molten salt`` excludes on the class label
``MoltenSalt``, but a candidate merely sharing one token with a
multi-token label is not excluded). Staging and proposal graphs are never
consulted -- the reader already excludes them, so this module deliberately
adds no graph parameters of its own.

Document frequency (:func:`score_document_frequency`, unchanged) is a
**coarse cost bound only, never a novelty rank** (design D3 -- the POC
showed DF does not separate genuine targets from common/known phrases):
surviving candidates below ``config.salience_threshold`` (the floor) are
dropped, and if more than ``config.mine_max_candidates`` (the ceiling)
survive, only the top-N by document frequency (deterministic
``(-doc_frequency, term)`` tie-break) are kept as a pure runaway guard on
triage fan-out, with the cut count logged. No keyness/weirdness/TF-IDF
ranking is computed anywhere in this module. Evidence (sentence text,
source ``Document``, and offsets into that document's ``normalized.txt``)
is drawn only from the curated ~12-report set, where those offsets and
``msr:Document`` nodes exist, even though the frequency count itself spans
all 637 documents.

Everything here is deterministic: no dict-order reliance, all returned
collections sorted for reproducibility (spaCy inference is deterministic at
eval time -- no sampling). Deliberately stdlib-only at module level (no
third-party imports, including spaCy itself -- see :func:`load_spacy_pipeline`),
mirroring ``mining_types.py`` and ``mine_provenance.py`` -- this module reads
only artifacts already on disk (``segments.jsonl``/``mentions.jsonl``/OCR
``*.txt``) and the graph via an injected
:class:`~msr_extraction.graph_reader.GraphReader`, whose own third-party
(``httpx``) dependency is deferred inside its call, not imported here.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
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
#: reconsidering if it under-performs in practice). This is the
#: ``genre="chemistry"`` (default) window; the ``genre="safety"`` window is
#: ``config.safety_max_chunk_tokens`` instead (chunk 11 / ingest-iaea-safety
#: D3, task 3.1) -- see :func:`enumerate_spacy_terms`.
_MAX_CHUNK_TOKENS = 3

# camelCase word-boundary split: a zero-width position between a
# lower/digit and a following upper ("moltenSalt" -> "molten Salt"), or
# between an upper letter and a following upper+lower pair ("MSRSalt" ->
# "MSR Salt", isolating a trailing capitalized word after a run of
# capitals/an acronym). `.sub(" ", text)` inserts a space at each such
# position without consuming any character.
_CAMEL_SPLIT_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

# Any run of non-alphanumeric characters is a token boundary (whitespace,
# hyphens, underscores, punctuation, ...) once camelCase has already been
# split into separate words above.
_SEPARATOR_RE = re.compile(r"[^A-Za-z0-9]+")


def _normalize_token_sequence(text: str) -> tuple[str, ...]:
    """Normalize `text` into a casefolded token sequence (design D2).

    Splits camelCase word boundaries (case-sensitive, so this MUST run
    before casefolding), then collapses any run of non-alphanumeric
    characters into a token boundary and casefolds every token. A raw known
    label (``"MoltenSalt"``, ``"molten salt"``, ``"molten_salt"``) and an
    already-casefolded, space-joined candidate term (``"molten salt"``) all
    normalize to the identical token sequence ``("molten", "salt")``, which
    is what makes :class:`ExclusionIndex`'s token-sequence containment
    check spelling-variant-proof.
    """
    spaced = _CAMEL_SPLIT_RE.sub(" ", text)
    return tuple(tok.casefold() for tok in _SEPARATOR_RE.split(spaced) if tok)


def _normalize_plain_tokens(text: str) -> tuple[str, ...]:
    """Normalize `text` into a casefolded token sequence WITHOUT camelCase splitting.

    Used for chunk-6 mention `surface_form`s (the already-linked exclusion):
    those are OCR'd natural-language/chemistry-formula spans (e.g.
    ``"FLiBe"``, ``"LiF-BeF2"``), not authored compound-word identifiers, so
    running them through :func:`_normalize_token_sequence`'s camelCase
    splitter would spuriously fragment a single token on incidental
    internal capitalization (``"FLiBe"`` -> ``"f li be"`` instead of
    ``"flibe"``). :func:`_normalize_token_sequence` is reserved for
    genuinely camelCase-authored **ontology labels** (e.g. the class label
    ``"MoltenSalt"``, design D2's own example); candidate terms reaching
    :class:`ExclusionIndex` are always already-casefolded plain text (no
    uppercase survives), so applying the camelCase-aware normalizer to them
    at lookup time is a no-op -- only the *known-label* side needs the
    choice of normalizer to matter.
    """
    return tuple(tok.casefold() for tok in _SEPARATOR_RE.split(text) if tok)


def _normalize_salt_label(label: str) -> tuple[str, ...]:
    """Normalize a salt-catalog label into a casefolded token sequence (design D2 fix).

    Salt-catalog (`KnownEntity(kind="salt")`) labels are formula strings
    with a trailing concentration suffix (e.g. ``"LiF-BeF2 (34.0-66.0
    mol%)"``) -- authored chemistry notation, not camelCase-authored
    identifiers. Running them through :func:`_normalize_token_sequence`
    would camelCase-split each formula at every lower->upper boundary
    (``BeF2`` -> ``be f2``) AND turn the concentration digits into extra
    tokens, producing a ~9-token sequence (e.g. ``("li", "f", "be", "f2",
    "34", "0", "66", "0", "mol")``) no real candidate term could ever
    contain, so salt labels would never actually exclude anything. Instead:
    (1) strip everything from the first ``(`` onward (the concentration/
    mol% suffix), then (2) normalize the remainder with
    :func:`_normalize_plain_tokens` (casefold + separator collapse, no
    camelCase split) -- identical treatment to the linked-mention
    `surface_form` handling, since both are formula-shaped chemistry spans,
    not authored compound-word labels. ``"LiF-BeF2 (34.0-66.0 mol%)"`` thus
    normalizes to ``("lif", "bef2")``.
    """
    formula = label.split("(", 1)[0]
    return _normalize_plain_tokens(formula)


class ExclusionIndex:
    """Normalized-label token-sequence exclusion index (design D2).

    Built by :func:`build_exclusion_set` from every known label (core
    dataset + chunk-6 linked mentions); supports ``term in index`` for a
    raw candidate term string. Membership normalizes `term` the same way
    every indexed label was normalized (:func:`_normalize_token_sequence`)
    and returns ``True`` iff some indexed label's *full* normalized token
    sequence is a contiguous run within the term's token sequence -- so a
    known label's sequence must appear whole (in order, back-to-back), not
    merely share individual tokens with the candidate.
    """

    def __init__(self, sequences: Iterable[tuple[str, ...]]) -> None:
        by_length: dict[int, set[tuple[str, ...]]] = {}
        for seq in sequences:
            if not seq:
                continue
            by_length.setdefault(len(seq), set()).add(seq)
        self._by_length: dict[int, frozenset[tuple[str, ...]]] = {
            length: frozenset(seqs) for length, seqs in by_length.items()
        }

    def __contains__(self, term: str) -> bool:
        term_tokens = _normalize_token_sequence(term)
        n = len(term_tokens)
        if n == 0:
            return False
        for length, sequences in self._by_length.items():
            if length > n:
                continue
            for start in range(n - length + 1):
                if term_tokens[start : start + length] in sequences:
                    return True
        return False


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


def _merge_prepositional_chunks(doc: Any) -> list[Any]:
    """Bridge adjacent `doc.noun_chunks` connected by a single preposition (safety genre only).

    spaCy's ``doc.noun_chunks`` never spans a preposition boundary: "the
    confinement of radioactive material" parses as **two** separate chunks
    ("The confinement", "radioactive material") with the single token "of"
    (``pos_ == "ADP"``) sitting in the gap between them -- confirmed against
    the real ``en_core_web_sm`` parse. Design D3's prepositional safety
    concepts ("confinement of radioactive material", "removal of residual
    heat", "control of reactivity", "defence in depth") are therefore
    unreachable from a per-noun-chunk pass alone, however the window/phrase
    logic is adjusted -- the fix has to happen one level up, at chunk
    selection.

    This function merges consecutive noun chunks into one :class:`Span`
    whenever the gap between them is EXACTLY one ADP token (chained,
    so three-plus-chunk prepositional phrases merge fully); any other gap
    shape (no gap / non-ADP token(s) / more than one token) leaves the
    chunks unmerged. Returns the merged sequence of spans, still in
    document order, for :func:`enumerate_spacy_terms` to iterate exactly
    like ``doc.noun_chunks`` did before -- used only for ``genre="safety"``;
    the chemistry genre keeps iterating ``doc.noun_chunks`` directly.
    """
    chunks = list(doc.noun_chunks)
    if not chunks:
        return []

    merged: list[Any] = []
    index = 0
    while index < len(chunks):
        start = chunks[index].start
        end = chunks[index].end
        next_index = index + 1
        while next_index < len(chunks):
            gap_start = end
            gap_end = chunks[next_index].start
            if gap_end - gap_start == 1 and doc[gap_start].pos_ == "ADP":
                end = chunks[next_index].end
                next_index += 1
                continue
            break
        merged.append(doc[start:end])
        index = next_index
    return merged


def _survivor_span_tokens(survivors: list[Any]) -> list[Any]:
    """All doc tokens spanning `survivors[0]` through `survivors[-1]` inclusive, in order.

    Used only by the ``genre="safety"`` phrase-preserving term construction
    (chunk 11 / ingest-iaea-safety D3, task 3.1): unlike the chemistry path,
    which joins the surviving content tokens' lemmas alone (dropping any
    stopword/preposition between them), the safety genre's term is built
    from the natural phrase span -- so a preposition sitting *between* two
    surviving tokens (e.g. "of" in "confinement of radioactive material",
    "in" in "defence in depth") is preserved in the emitted candidate term,
    while any leading/trailing stopword tokens OUTSIDE the surviving span
    are still dropped (mirroring the chemistry trailing-window trim intent).
    Returns `[]` for an empty `survivors` list.
    """
    if not survivors:
        return []
    doc = survivors[0].doc
    start = survivors[0].i
    end = survivors[-1].i
    return [doc[i] for i in range(start, end + 1)]


def enumerate_spacy_terms(
    reports: list[str], config: Config, nlp: Any, *, genre: str = "chemistry"
) -> dict[str, _SpacyTermHit]:
    """spaCy noun-chunk candidate pass over each report's `segments.jsonl` (design D1).

    Reads each report's ``segments.jsonl`` exactly like
    :func:`enumerate_lexical_terms` (a missing file is a logged warning, not
    an error) so candidates carry identical :class:`Evidence` (report,
    document IRI, full segment ``sentence_text``, offsets) to the lexical
    pass. For ``genre="safety"`` (chunk 11 / ingest-iaea-safety D3, task
    3.1), segments are read from ``config.safety_segments_path(report)``
    (the safety cache) instead of ``config.segments_path(report)`` (the
    chemistry corpus) -- the default ``genre="chemistry"`` path is
    byte-identical to before this parameter existed. Runs every segment's
    text through `nlp.pipe` in one batch (perf); iterates `doc.noun_chunks`
    for chemistry, or -- for safety -- the sequence :func:`_merge_prepositional_chunks`
    returns (adjacent noun chunks bridged by a single preposition token
    merged into one span, since a real ``en_core_web_sm`` parse never spans
    a preposition boundary within a single ``doc.noun_chunks`` entry: "the
    confinement of radioactive material" parses as two separate chunks
    joined only by the gap token "of"). Either way, keeps only the
    surviving tokens (:func:`_surviving_chunk_tokens`) -- a chunk that
    reduces to zero surviving tokens contributes no candidate.

    Surviving tokens beyond the genre's window (:data:`_MAX_CHUNK_TOKENS`
    for chemistry, ``config.safety_max_chunk_tokens`` for safety) are
    trimmed to the trailing window. For chemistry, the candidate ``term``
    is the casefolded, space-joined lemma sequence of the surviving tokens
    alone (unchanged). For safety, the term is instead built from the full
    phrase span between the first and last surviving token
    (:func:`_survivor_span_tokens`) so prepositional multi-word safety
    concepts survive as candidates with their surface syntax intact (e.g.
    "confinement of radioactive material", not "confinement radioactive
    material"). Either way, ``surface_form`` is the original (untrimmed)
    chunk text.

    A term's evidence is deduplicated per segment exactly like the lexical
    pass (:data:`evidence_key` = ``(report, char_start)``); its
    `surface_form` is picked deterministically (shortest, then
    lexicographically-first observed chunk text for that term) since the
    same normalized term can surface from differently-worded chunks across
    segments/reports.

    Returns ``term -> _SpacyTermHit``, built without relying on dict
    iteration order (the caller, :func:`mine_candidates`, sorts its final
    output).
    """
    max_chunk_tokens = config.safety_max_chunk_tokens if genre == "safety" else _MAX_CHUNK_TOKENS

    segment_meta: list[tuple[str, str, int, str]] = []
    for report in reports:
        path = config.safety_segments_path(report) if genre == "safety" else config.segments_path(report)
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
        chunks = _merge_prepositional_chunks(doc) if genre == "safety" else doc.noun_chunks
        for chunk in chunks:
            survivors = _surviving_chunk_tokens(chunk)
            if not survivors:
                continue
            if len(survivors) > max_chunk_tokens:
                survivors = survivors[-max_chunk_tokens:]
            if genre == "safety":
                span_tokens = _survivor_span_tokens(survivors)
                term = " ".join(tok.lemma_.casefold() for tok in span_tokens if tok.is_alpha)
            else:
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


def enumerate_lexical_terms(
    reports: list[str], config: Config, *, genre: str = "chemistry"
) -> dict[str, list[Evidence]]:
    """Lexical term-candidate pass over each report's `segments.jsonl` (D5 fallback).

    Reads each report's ``segments.jsonl`` (the same JSONL shape
    ``linker._read_segments`` consumes: ``report``/``index``/``text``/
    ``char_start``/``char_end`` per line) -- for ``genre="safety"``, from
    ``config.safety_segments_path(report)`` (the safety cache) instead of
    ``config.segments_path(report)`` (the chemistry corpus), mirroring
    :func:`enumerate_spacy_terms`; a missing file is logged as a warning and
    skipped, not an error. Each segment's ``text`` is tokenized into
    case-folded unigrams/bigrams/trigrams (see :func:`_tokenize`/
    :func:`_ngrams`); every surviving term collects one :class:`Evidence`
    per segment it appears in, keyed by ``(report, start_offset)`` so a term
    repeated within one segment (e.g. a bigram and its constituent unigram
    both landing in the same sentence) only ever contributes a single
    evidence item for that segment.

    Returns ``term -> [Evidence, ...]``, both the outer mapping and the
    Evidence lists built without relying on dict iteration order for
    correctness (the caller, :func:`mine_candidates`, sorts its final
    output).
    """
    terms: dict[str, dict[tuple[str, int], Evidence]] = {}
    for report in reports:
        path = config.safety_segments_path(report) if genre == "safety" else config.segments_path(report)
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


def build_exclusion_set(reader: GraphReader, reports: list[str], config: Config) -> ExclusionIndex:
    """Build the normalization/token-sequence-aware exclusion index (design D2/4.1).

    Sources ALL core labels the `GraphReader` exposes: every label of every
    :class:`~msr_extraction.graph_reader.KnownEntity` from
    ``reader.read_known_entities()`` (SKOS `prefLabel`/`altLabel` -- incl.
    reactor concepts, ontology classes, physical properties, salts) PLUS
    chunk-7's salt-role labels (``reader.read_role_reactor_labels()``) --
    all read only through the three core ``FROM`` graphs, so this function
    adds no graph parameters of its own and staging/proposal are never
    consulted. Also folds in every ``status:"linked"`` record's
    ``surface_form`` from each report's `mentions.jsonl` (chunk 6's own
    already-resolved mentions).

    Ontology/concept labels (`entity.kind` `"concept"`/`"class"`) are
    normalized via :func:`_normalize_token_sequence` (casefold + camelCase
    split + separator collapse), so the returned :class:`ExclusionIndex`
    excludes spelling/spacing/camelCase variants of a known label (e.g.
    `molten salt` vs the class label `MoltenSalt`). Salt-catalog labels
    (`entity.kind == "salt"`) are formula strings with a concentration
    suffix (e.g. `"LiF-BeF2 (34.0-66.0 mol%)"`), not camelCase-authored
    identifiers, so they are normalized instead via
    :func:`_normalize_salt_label`: the parenthetical concentration/`mol%`
    suffix is stripped and the remaining formula is normalized WITHOUT
    camelCase splitting (like linked-mention surface forms below), so
    `"LiF-BeF2 (34.0-66.0 mol%)"` indexes as `("lif", "bef2")` rather than
    fragmenting into single letters plus stray concentration digits.
    Linked-mention `surface_form`s are normalized via
    :func:`_normalize_plain_tokens` (casefold + separator collapse, no
    camelCase split): those are OCR'd formula/nickname spans (e.g.
    `"FLiBe"`), not authored compound identifiers, and camelCase-splitting
    them would spuriously fragment a single token.
    """
    sequences: set[tuple[str, ...]] = set()

    def _index_label(label: str) -> None:
        tokens = _normalize_token_sequence(label)
        if tokens:
            sequences.add(tokens)

    def _index_salt_label(label: str) -> None:
        tokens = _normalize_salt_label(label)
        if tokens:
            sequences.add(tokens)

    def _index_surface(surface_form: str) -> None:
        tokens = _normalize_plain_tokens(surface_form)
        if tokens:
            sequences.add(tokens)

    for entity in reader.read_known_entities():
        for label in entity.labels:
            if entity.kind == "salt":
                _index_salt_label(label)
            else:
                _index_label(label)

    for label in reader.read_role_reactor_labels():
        _index_label(label)

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
                _index_surface(surface_form)

    return ExclusionIndex(sequences)


def _build_corpus_index(archive_dir: Path) -> list[str]:
    """Case-folded text of every `*.txt` OCR sidecar under `archive_dir`, read once."""
    texts: list[str] = []
    for path in sorted(archive_dir.rglob("*.txt")):
        try:
            texts.append(path.read_text(encoding="utf-8", errors="ignore").casefold())
        except OSError:
            logger.warning("could not read OCR sidecar %s; excluding from corpus index", path)
    return texts


def score_document_frequency(
    terms: set[str], config: Config, *, genre: str = "chemistry"
) -> dict[str, int]:
    """Document frequency of each term over the genre's full OCR/text corpus.

    Builds the case-folded doc-text index once (via :func:`_build_corpus_index`
    over the genre's corpus root -- ``config.archive_dir`` for
    ``genre="chemistry"`` (the 637-document msr-archive corpus, unchanged),
    or ``config.safety_dir`` (the safety cache) for ``genre="safety"``, chunk
    11 / ingest-iaea-safety D3 task 3.1); for each document, generates that
    document's own set of normalized n-gram terms via :func:`_terms_in_text`
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

    If the genre's corpus root is missing or has no `.txt` sidecars, logs a
    warning and returns ``{term: 0 for term in terms}`` rather than raising.
    """
    if not terms:
        return {}

    corpus_dir = config.safety_dir if genre == "safety" else config.archive_dir
    if not corpus_dir.exists():
        logger.warning(
            "corpus dir %s does not exist; document-frequency scoring returns 0 for all terms",
            corpus_dir,
        )
        return {term: 0 for term in terms}

    corpus_texts = _build_corpus_index(corpus_dir)
    if not corpus_texts:
        logger.warning(
            "corpus dir %s has no .txt sidecars; document-frequency scoring returns 0 for all terms",
            corpus_dir,
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
    config: Config,
    reader: GraphReader,
    reports: list[str] = CURATED_REPORTS,
    *,
    nlp: Any = None,
    genre: str = "chemistry",
) -> list[Candidate]:
    """Enumerate, exclude, cost-bound, and retain novelty candidates (the umbrella entry point).

    Pipeline (refine-mine-salience D1-D3; ``genre`` per chunk 11 /
    ingest-iaea-safety D3, task 3.1):

    1. **Enumerate.** If `nlp` is injected, use it directly; otherwise try
       :func:`load_spacy_pipeline`. When a pipeline is available, enumerate
       via the spaCy noun-chunk pass (:func:`enumerate_spacy_terms`);
       otherwise log the fallback and use the prior lexical n-gram pass
       (:func:`enumerate_lexical_terms`, design D5). Either way, also read
       the unchanged chunk-6 salt-formula misses
       (:func:`read_miss_candidates`). ``genre`` is threaded to
       :func:`enumerate_spacy_terms`/:func:`enumerate_lexical_terms` so
       ``genre="safety"`` reads segments from the safety cache
       (``config.safety_segments_path``) and relaxes the noun-chunk window
       to ``config.safety_max_chunk_tokens`` while preserving the
       noun-chunk head phrase (prepositions intact) -- ``genre="chemistry"``
       (the default) is byte-identical to before this parameter existed.
    2. **Harden-exclude.** Drop any candidate whose term is `in`
       :func:`build_exclusion_set`'s :class:`ExclusionIndex` (normalization/
       token-sequence aware, design D2) -- unchanged for both genres.
    3. **Cost-bound, not rank.** Score the survivors' document frequency
       (:func:`score_document_frequency`) over the genre's corpus --
       ``config.archive_dir`` for chemistry (unchanged), ``config.safety_dir``
       for safety; drop anything below the ``config.salience_threshold``
       floor. If more than ``config.mine_max_candidates`` remain, keep only
       the top-N by document frequency with a deterministic
       ``(-doc_frequency, term)`` tie-break (a pure runaway guard on triage
       fan-out -- explicitly NOT a novelty ranking; no keyness/weirdness/
       TF-IDF is computed anywhere in this module). The floor/ceiling
       VALUES themselves are unchanged for both genres.
    4. **Attach evidence.** Lexical/spaCy-sourced candidates carry the
       evidence collected during enumeration (plus, for spaCy candidates,
       the chunk's original `surface_form`); miss candidates keep the
       evidence/`surface_form` they were built with.

    Returns the retained candidates sorted by ``term`` for determinism, and
    emits exactly one summary log line: candidates enumerated / excluded /
    below-floor / cut-by-ceiling (never a silent truncation, design 5.2).
    """
    if nlp is None:
        nlp = load_spacy_pipeline(config)

    surface_forms: dict[str, str] = {}
    if nlp is not None:
        spacy_hits = enumerate_spacy_terms(reports, config, nlp, genre=genre)
        lexical_evidence: dict[str, tuple[Evidence, ...]] = {
            term: hit.evidence for term, hit in spacy_hits.items()
        }
        surface_forms = {term: hit.surface_form for term, hit in spacy_hits.items()}
    else:
        logger.error(
            "mine: spaCy pipeline unavailable; falling back to n-gram candidate enumeration"
        )
        # NOTE: `genre` is passed only when non-default so that a caller who
        # has monkeypatched `enumerate_lexical_terms`/`score_document_frequency`
        # with a fixed 2-positional-arg test double (as the chemistry-genre
        # test suite does) keeps working unmodified -- the extra keyword is
        # never sent on the byte-identical `genre="chemistry"` default path.
        lexical_terms = (
            enumerate_lexical_terms(reports, config, genre=genre)
            if genre != "chemistry"
            else enumerate_lexical_terms(reports, config)
        )
        lexical_evidence = {
            term: tuple(evidence) for term, evidence in lexical_terms.items()
        }

    miss_candidates = read_miss_candidates(reports, config)
    exclusion = build_exclusion_set(reader, reports, config)

    enumerated_count = len(lexical_evidence) + len(miss_candidates)

    surviving_lexical = {
        term: evidence for term, evidence in lexical_evidence.items() if term not in exclusion
    }
    surviving_miss = [candidate for candidate in miss_candidates if candidate.term not in exclusion]
    excluded_count = enumerated_count - (len(surviving_lexical) + len(surviving_miss))

    all_terms = set(surviving_lexical) | {candidate.term for candidate in surviving_miss}
    # See the NOTE above `enumerate_lexical_terms`'s call site: `genre` is
    # passed only when non-default, for the identical monkeypatch-compat
    # reason.
    frequencies = (
        score_document_frequency(all_terms, config, genre=genre)
        if genre != "chemistry"
        else score_document_frequency(all_terms, config)
    )

    scored: list[Candidate] = []
    for term, evidence in surviving_lexical.items():
        doc_frequency = frequencies.get(term, 0)
        if doc_frequency >= config.salience_threshold:
            scored.append(
                Candidate(
                    term=term,
                    source="lexical",
                    evidence=evidence,
                    doc_frequency=doc_frequency,
                    surface_form=surface_forms.get(term, ""),
                )
            )
    for candidate in surviving_miss:
        doc_frequency = frequencies.get(candidate.term, 0)
        if doc_frequency >= config.salience_threshold:
            scored.append(
                Candidate(
                    term=candidate.term,
                    source=candidate.source,
                    evidence=candidate.evidence,
                    doc_frequency=doc_frequency,
                    surface_form=candidate.surface_form,
                )
            )
    below_floor_count = (len(surviving_lexical) + len(surviving_miss)) - len(scored)

    cut_by_ceiling_count = 0
    if len(scored) > config.mine_max_candidates:
        scored.sort(key=lambda candidate: (-candidate.doc_frequency, candidate.term))
        cut_by_ceiling_count = len(scored) - config.mine_max_candidates
        scored = scored[: config.mine_max_candidates]

    scored.sort(key=lambda candidate: candidate.term)

    logger.info(
        "mine: enumerated=%d excluded=%d below_floor=%d cut_by_ceiling=%d retained=%d",
        enumerated_count,
        excluded_count,
        below_floor_count,
        cut_by_ceiling_count,
        len(scored),
    )
    return scored
