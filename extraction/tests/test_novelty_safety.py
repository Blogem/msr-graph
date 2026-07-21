"""Safety-genre multi-word candidate mining tests (openspec/changes/
ingest-iaea-safety, spec ``safety-ontology-evolution``, task 8.3).

Hermetic: uses the REAL, installed ``en_core_web_sm`` pipeline (same
convention as ``test_novelty.py``'s ``_NLP``) injected via
``mine_candidates(..., nlp=_NLP, genre="safety")`` -- no live GraphDB, no
live model.

ASSUMPTION (pass-1, flagged in the tester handoff report for
reconciliation at merge): ``novelty.mine_candidates`` does not yet accept
a ``genre`` keyword on this isolated pass-1 branch (task 3.1: "relax the
1-3 content-token window ... for the safety genre", driven by the
``config.safety_max_chunk_tokens`` field the Wave-1 config plumbing
already added). Every test below is written against that pinned contract,
not against any implementation, and is expected to fail (either a
TypeError on the unrecognized ``genre=`` kwarg, or an assertion failure)
until the coder's change lands.

IMPORTANT FINDING (surfaced to the orchestrator in the tester handoff
report, not silently worked around): a dry run of the REAL
``en_core_web_sm`` pipeline against this file's own fixture sentences
(recorded below) shows ``doc.noun_chunks`` never spans a prepositional
attachment -- "confinement of radioactive material" tokenizes into TWO
separate noun chunks ("confinement" and "radioactive material"), never
one. Widening ``_MAX_CHUNK_TOKENS`` alone (design.md D3's literal
"relax the content-token window" wording) cannot make these two acceptance
scenarios pass: the fundamental-safety-function phrases "confinement of
radioactive material", "control of reactivity", and "removal of residual
heat" would need adjacent-chunk merging across a single preposition token,
not just a wider per-chunk window. Only "heat removal" (no intervening
preposition; 2 content tokens) is achievable with a pure window widen.
The tests below assert the literal acceptance-criteria outcome (the spec
text, not design.md's mechanism sketch) for all four phrases, so a
window-only implementation will pass the "heat removal" test but is
expected to fail the three PP-spanning ones -- a genuine BEHAVIOR_MISMATCH
gap for pass-2 to report, not a test bug to soften.
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

    normalized_text = " ".join(sentences)
    normalized_path = config.normalized_path(report)
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_path.write_text(normalized_text, encoding="utf-8")

    with config.segments_path(report).open("w", encoding="utf-8") as fh:
        for seg in segments:
            fh.write(json.dumps(seg))
            fh.write("\n")


def _write_mentions(config: Config, report: str, records: list[dict]) -> None:
    path = config.mentions_path(report)
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
