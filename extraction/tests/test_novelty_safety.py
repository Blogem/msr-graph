"""Safety-genre multi-word candidate mining tests (openspec/changes/
ingest-iaea-safety, spec ``safety-ontology-evolution``, task 8.3).

Hermetic: uses the REAL, installed ``en_core_web_sm`` pipeline (same
convention as ``test_novelty.py``'s ``_NLP``) injected via
``mine_candidates(..., nlp=_NLP, genre="safety")`` -- no live GraphDB, no
live model.

RECONCILED (pass-2, merge with the real ``novelty.py``): the coder's
landed implementation resolved the pass-1 "IMPORTANT FINDING" below in
full -- ``_merge_prepositional_chunks`` bridges adjacent ``doc.noun_chunks``
across a single intervening ``ADP`` (preposition) token, and
``_survivor_span_tokens`` preserves that preposition in the emitted term,
so all four phrases (including the three PP-spanning ones) genuinely
surface as candidates under ``genre="safety"``, exactly as this file's
assertions expect. No BEHAVIOR_MISMATCH here.

The only reconciliation needed was this file's own fixture-writer helper:
it wrote ``segments.jsonl``/``mentions.jsonl``/``normalized.txt`` to the
chemistry-genre paths (``config.segments_path``/``config.mentions_path``/
``config.normalized_path``), but ``mine_candidates(..., genre="safety")``
reads segments via ``config.safety_segments_path`` and scores document
frequency over ``config.safety_dir`` (confirmed in ``novelty.
enumerate_spacy_terms``/``score_document_frequency``). The helper below
now writes to ``config.safety_segments_path`` instead. It also no longer
writes a ``normalized.txt`` sidecar: unlike the chemistry genre (where
``archive_dir`` -- the document-frequency scan root -- is a sibling of,
not the same tree as, each report's own artifact dir), the safety genre's
DF scan root (``config.safety_dir``) IS the same tree that
``config.safety_report_dir`` nests each source's artifacts under, so a
``normalized.txt`` written there would leak into the report's own
document-frequency corpus scan (``_build_corpus_index`` globs every
``*.txt`` under ``safety_dir`` recursively) -- ``mine_candidates`` never
reads ``normalized_path`` itself, so dropping that write changes nothing
these tests assert while keeping the DF-floor test (salience_threshold=1)
honest.
"""

from __future__ import annotations

import json

import spacy

from msr_extraction.config import Config
from msr_extraction.graph_reader import MSRD, GraphReader
from msr_extraction.novelty import mine_candidates

REPORT = "SAFETY-FIX-0001"

_NLP = spacy.load("en_core_web_sm")

# Dry-run-confirmed (real en_core_web_sm) noun-chunk shapes for these
# sentences, recorded here so a reader can verify the "IMPORTANT FINDING"
# above independently:
#   "The reactor design ensures confinement of radioactive material at all
#    times." -> chunks: "The reactor design", "confinement",
#    "radioactive material", "all times" (TWO chunks for the PP, never one)
#   "The system provides removal of residual heat from the core under all
#    conditions." -> chunks: "The system", "removal", "residual heat",
#    "the core", "all conditions"
#   "Adequate control of reactivity is maintained throughout normal
#    operation." -> chunks: "Adequate control", "reactivity",
#    "normal operation"
#   "Effective heat removal is essential for reactor safety." -> chunks:
#    "Effective heat removal" (ONE 3-token chunk; survives even the
#    default window=3), "reactor safety"

CONFINEMENT_SENTENCE = (
    "The reactor design ensures confinement of radioactive material at all times."
)
HEAT_REMOVAL_SOURCE_SENTENCE = (
    "The system provides removal of residual heat from the core under all conditions."
)
CONTROL_SENTENCE = (
    "Adequate control of reactivity is maintained throughout normal operation."
)
HEAT_REMOVAL_SHORT_SENTENCE = "Effective heat removal is essential for reactor safety."

NOISE_SENTENCE = "The system was checked."


def _write_curated_report(config: Config, report: str, sentences: list[str]) -> None:
    """Write the safety-genre ``segments.jsonl`` fixture for ``report``.

    Deliberately does NOT write a ``normalized.txt`` sidecar (see the
    module docstring's reconciliation note): ``mine_candidates`` never
    reads ``safety_normalized_path``, and writing one would leak into
    ``score_document_frequency``'s ``config.safety_dir`` corpus scan for
    ``genre="safety"``.
    """
    segments = []
    offset = 0
    for index, sentence in enumerate(sentences):
        if index > 0:
            offset += 1  # single-space separator
        start = offset
        end = start + len(sentence)
        segments.append(
            {
                "report": report,
                "index": index,
                "text": sentence,
                "char_start": start,
                "char_end": end,
            }
        )
        offset = end

    segments_path = config.safety_segments_path(report)
    segments_path.parent.mkdir(parents=True, exist_ok=True)
    with segments_path.open("w", encoding="utf-8") as fh:
        for seg in segments:
            fh.write(json.dumps(seg))
            fh.write("\n")


def _write_mentions(config: Config, report: str, records: list[dict]) -> None:
    path = config.safety_mentions_path(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record))
            fh.write("\n")


def _empty_reader() -> GraphReader:
    return GraphReader("http://example/repositories/msr", select_fn=lambda query: [])


# --- Achievable today with pure window-widening (positive control) ---------


def test_heat_removal_two_token_compound_survives_intact(tmp_path) -> None:
    """Scenario: "Fundamental safety functions surface as proposals" --
    "heat removal" has no intervening preposition, so it already fits a
    3-token noun chunk and must keep surviving under genre="safety"."""
    config = Config(corpus_dir=tmp_path, salience_threshold=0)
    _write_curated_report(config, REPORT, [HEAT_REMOVAL_SHORT_SENTENCE])
    _write_mentions(config, REPORT, [])

    candidates = mine_candidates(
        config, _empty_reader(), reports=[REPORT], nlp=_NLP, genre="safety"
    )
    terms = [c.term for c in candidates]

    assert any("heat" in term and "removal" in term for term in terms)


def test_heat_removal_candidate_carries_document_frequency_evidence(tmp_path) -> None:
    """Scenario: "A prepositional safety concept survives the token window"
    -- companion assertion that the surviving candidate carries evidence
    (msr:citedIn a safety Document via the report's document IRI), not just
    a bare term."""
    config = Config(corpus_dir=tmp_path, salience_threshold=0)
    _write_curated_report(config, REPORT, [HEAT_REMOVAL_SHORT_SENTENCE])
    _write_mentions(config, REPORT, [])

    candidates = mine_candidates(
        config, _empty_reader(), reports=[REPORT], nlp=_NLP, genre="safety"
    )
    match = next(
        (c for c in candidates if "heat" in c.term and "removal" in c.term), None
    )
    assert match is not None
    assert len(match.evidence) >= 1
    assert match.evidence[0].document_iri == f"{MSRD}{REPORT}"


# --- PP-spanning phrases (flagged finding: may require chunk-merging, not
# just a wider window -- see module docstring) ------------------------------


def test_confinement_of_radioactive_material_surfaces_as_one_candidate(
    tmp_path,
) -> None:
    """Scenario: "A prepositional safety concept survives the token window"
    -- the miner emits the noun-phrase candidate "confinement of
    radioactive material" (not only its constituent unigrams/chunks)."""
    config = Config(corpus_dir=tmp_path, salience_threshold=0)
    _write_curated_report(config, REPORT, [CONFINEMENT_SENTENCE])
    _write_mentions(config, REPORT, [])

    candidates = mine_candidates(
        config, _empty_reader(), reports=[REPORT], nlp=_NLP, genre="safety"
    )
    terms = [c.term for c in candidates]

    assert any(
        "confinement" in term and "radioactive" in term and "material" in term
        for term in terms
    )


def test_removal_of_residual_heat_surfaces_as_one_candidate(tmp_path) -> None:
    """Scenario: design.md D3's own worked example -- "removal of residual
    heat" survives as one candidate, not truncated to its last tokens."""
    config = Config(corpus_dir=tmp_path, salience_threshold=0)
    _write_curated_report(config, REPORT, [HEAT_REMOVAL_SOURCE_SENTENCE])
    _write_mentions(config, REPORT, [])

    candidates = mine_candidates(
        config, _empty_reader(), reports=[REPORT], nlp=_NLP, genre="safety"
    )
    terms = [c.term for c in candidates]

    assert any(
        "removal" in term and "residual" in term and "heat" in term for term in terms
    )


def test_control_of_reactivity_surfaces_as_one_candidate(tmp_path) -> None:
    """Scenario: "Fundamental safety functions surface as proposals" --
    "control of reactivity" (the third fundamental safety function)."""
    config = Config(corpus_dir=tmp_path, salience_threshold=0)
    _write_curated_report(config, REPORT, [CONTROL_SENTENCE])
    _write_mentions(config, REPORT, [])

    candidates = mine_candidates(
        config, _empty_reader(), reports=[REPORT], nlp=_NLP, genre="safety"
    )
    terms = [c.term for c in candidates]

    assert any("control" in term and "reactivity" in term for term in terms)


def test_all_three_fundamental_safety_functions_surface_together(tmp_path) -> None:
    """Scenario: "Fundamental safety functions surface as proposals" over
    the combined ingested-genre text -- all three named phrases are
    present as distinct candidates in the same mining run."""
    config = Config(corpus_dir=tmp_path, salience_threshold=0)
    _write_curated_report(
        config,
        REPORT,
        [CONFINEMENT_SENTENCE, CONTROL_SENTENCE, HEAT_REMOVAL_SHORT_SENTENCE],
    )
    _write_mentions(config, REPORT, [])

    candidates = mine_candidates(
        config, _empty_reader(), reports=[REPORT], nlp=_NLP, genre="safety"
    )
    terms = [c.term for c in candidates]

    assert any("confinement" in term and "radioactive" in term for term in terms)
    assert any("control" in term and "reactivity" in term for term in terms)
    assert any("heat" in term and "removal" in term for term in terms)


# --- Single-token noise is excluded -----------------------------------------


def test_single_token_noise_never_surfaces_as_its_own_candidate(tmp_path) -> None:
    """Scenario basis: single-token noise ("the", "system") is excluded --
    "the" is a stopword (dropped at the surviving-token filter, never
    enumerated at all); a bare, low-signal noun ("system") appearing in
    only one low-frequency sentence never clears the salience floor, so
    neither ever surfaces as its own single-word candidate alongside the
    genuine safety-genre concepts."""
    config = Config(corpus_dir=tmp_path, salience_threshold=1)
    _write_curated_report(config, REPORT, [NOISE_SENTENCE, CONFINEMENT_SENTENCE])
    _write_mentions(config, REPORT, [])

    candidates = mine_candidates(
        config, _empty_reader(), reports=[REPORT], nlp=_NLP, genre="safety"
    )
    terms = {c.term for c in candidates}

    assert "the" not in terms
    assert "system" not in terms


# --- Genre-threading regression (review fix): the safety-genre mentions ---
# path (`config.safety_mentions_path`), not the chemistry-genre one, must
# be what `build_exclusion_set`/`read_miss_candidates` actually read for
# genre="safety". Prior to this fix, both functions unconditionally called
# `config.mentions_path`, so a safety-genre `mentions.jsonl` written by
# `_write_mentions` above (which already targets
# `config.safety_mentions_path`, per this module's earlier reconciliation
# note) was silently never read: a `status:"linked"` span could never
# exclude anything, and a `status:"novel"` span could never surface as a
# miss candidate, under genre="safety".


def test_safety_linked_mention_excludes_matching_candidate(tmp_path) -> None:
    """A `status:"linked"` span in the safety `mentions.jsonl` must exclude
    its matching term from the safety candidate set -- proving
    `build_exclusion_set(..., genre="safety")` actually reads
    `config.safety_mentions_path`, not the (untouched, chemistry-genre)
    `config.mentions_path`."""
    config = Config(corpus_dir=tmp_path, salience_threshold=0)
    _write_curated_report(config, REPORT, [HEAT_REMOVAL_SHORT_SENTENCE])
    _write_mentions(
        config,
        REPORT,
        [
            {
                "status": "linked",
                "surface_form": "reactor safety",
                "char_start": 0,
                "char_end": 14,
            }
        ],
    )

    candidates = mine_candidates(
        config, _empty_reader(), reports=[REPORT], nlp=_NLP, genre="safety"
    )
    terms = [c.term for c in candidates]

    # "reactor safety" (the linked, already-known mention) is excluded...
    assert not any("reactor" in term and "safety" in term for term in terms)
    # ...but the sibling "effective heat removal" candidate from the same
    # sentence is untouched, proving the exclusion targeted only the
    # linked term rather than wiping the whole candidate set.
    assert any("heat" in term and "removal" in term for term in terms)


def test_safety_novel_mention_feeds_a_miss_candidate(tmp_path) -> None:
    """A `status:"novel"` span in the safety `mentions.jsonl` must surface
    as its own `source="miss"` candidate -- proving
    `read_miss_candidates(..., genre="safety")` actually reads
    `config.safety_mentions_path`, not the (untouched, chemistry-genre)
    `config.mentions_path`."""
    config = Config(corpus_dir=tmp_path, salience_threshold=0)
    _write_curated_report(config, REPORT, [NOISE_SENTENCE])
    _write_mentions(
        config,
        REPORT,
        [
            {
                "status": "novel",
                "surface_form": "xenon poisoning",
                "char_start": 5,
                "char_end": 20,
            }
        ],
    )

    candidates = mine_candidates(
        config, _empty_reader(), reports=[REPORT], nlp=_NLP, genre="safety"
    )
    by_term = {c.term: c for c in candidates}

    assert "xenon poisoning" in by_term
    match = by_term["xenon poisoning"]
    assert match.source == "miss"
    assert len(match.evidence) == 1
    assert match.evidence[0].document_iri == f"{MSRD}{REPORT}"
