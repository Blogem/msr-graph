"""Safety-genre mining calibration tests (post-chunk-11 mine-calibration
fix, root-caused live: ``genre="safety"`` mining produced ZERO proposals
on the real 4-document safety corpus).

Two independent bugs, each covered here:

1. **Wrong floor.** ``novelty.mine_candidates`` compared every candidate's
   document frequency against ``config.salience_threshold`` (default 50,
   sized for the 637-document msr-archive chemistry corpus) for BOTH
   genres. The safety corpus has at most a handful of documents, so no
   candidate's document frequency could ever reach 50 -- every safety
   candidate fell below the floor. ``config.safety_salience_threshold``
   (default 1) now floors ``genre="safety"`` instead.
2. **Double-counted documents.** ``score_document_frequency``'s
   safety-genre corpus scan globbed ``config.safety_dir`` with
   ``rglob("*.txt")``, which matches BOTH a source's raw top-level
   ``{id}.txt`` (written by ``safety_acquire.extract_pdf_text``) and its
   per-source ``{id}/normalized.txt`` (written by
   ``safety_acquire.normalize_and_segment``) -- every real safety source
   was counted twice, roughly doubling every term's document frequency.
   ``score_document_frequency(..., genre="safety", reports=...)`` now
   reads exactly one text per source (``config.safety_normalized_path``).

Hermetic: uses the REAL, installed ``en_core_web_sm`` pipeline (same
convention as ``test_novelty.py``/``test_novelty_safety.py``'s ``_NLP``)
injected via ``mine_candidates(..., nlp=_NLP, genre="safety")`` -- no live
GraphDB, no live model.
"""

from __future__ import annotations

import json

import spacy

from msr_extraction.config import Config
from msr_extraction.graph_reader import GraphReader
from msr_extraction.novelty import mine_candidates, score_document_frequency

_NLP = spacy.load("en_core_web_sm")

HEAT_REMOVAL_SENTENCE = "Effective heat removal is essential for reactor safety."


def _empty_reader() -> GraphReader:
    return GraphReader("http://example/repositories/msr", select_fn=lambda query: [])


def _write_safety_segments(config: Config, report: str, sentences: list[str]) -> None:
    """Write a safety-genre ``segments.jsonl`` fixture for ``report``
    (mirrors ``test_novelty_safety.py``'s ``_write_curated_report``)."""
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


def _write_empty_mentions(config: Config, report: str) -> None:
    path = config.safety_mentions_path(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


# --- FIX 1: genre-aware salience floor --------------------------------------


def test_low_df_candidate_survives_safety_floor_but_would_be_cut_by_chemistry_floor(
    tmp_path,
) -> None:
    """A term that appears in only two safety documents clears the
    default `safety_salience_threshold` (1) but would be dropped by the
    default `salience_threshold` (50, the chemistry floor) -- proving
    `mine_candidates(genre="safety")` floors on the safety-specific field,
    not the chemistry one."""
    config = Config(corpus_dir=tmp_path)
    assert config.safety_salience_threshold == 1
    assert config.salience_threshold == 50

    reports = ["SAFETY-CAL-0001", "SAFETY-CAL-0002"]
    for report in reports:
        _write_safety_segments(config, report, [HEAT_REMOVAL_SENTENCE])
        _write_empty_mentions(config, report)
        # Per-source normalized text (FIX 2's DF-scan root) so this
        # candidate's document frequency is a real, non-zero count.
        normalized_path = config.safety_normalized_path(report)
        normalized_path.parent.mkdir(parents=True, exist_ok=True)
        normalized_path.write_text(HEAT_REMOVAL_SENTENCE, encoding="utf-8")

    candidates = mine_candidates(
        config, _empty_reader(), reports=reports, nlp=_NLP, genre="safety"
    )
    match = next(
        (c for c in candidates if "heat" in c.term and "removal" in c.term), None
    )
    assert match is not None, "expected candidate to survive the safety floor"

    # Below the chemistry floor (50)...
    assert 0 < match.doc_frequency < config.salience_threshold
    # ...but at/above the safety floor (1).
    assert match.doc_frequency >= config.safety_salience_threshold


def test_safety_salience_threshold_env_override(monkeypatch) -> None:
    """`MSR_SAFETY_SALIENCE_THRESHOLD` overrides the default via `from_env`,
    mirroring every other int-typed `Config` field's env-override test."""
    monkeypatch.setenv("MSR_SAFETY_SALIENCE_THRESHOLD", "3")
    config = Config.from_env(
        {"MSR_SAFETY_SALIENCE_THRESHOLD": "3"}
    )
    assert config.safety_salience_threshold == 3


# --- FIX 2: DF double-count --------------------------------------------------


def test_safety_df_counts_source_once_despite_raw_and_normalized_txt(tmp_path) -> None:
    """A safety source with BOTH its raw top-level `{id}.txt` (written by
    `safety_acquire.extract_pdf_text`) and its per-source
    `{id}/normalized.txt` (written by `safety_acquire.normalize_and_segment`)
    present under `safety_dir` must have its document frequency counted
    ONCE, not twice -- proving `score_document_frequency(genre="safety")`
    reads exactly one text per source rather than globbing the whole
    `safety_dir` tree."""
    config = Config(corpus_dir=tmp_path)
    report = "SAFETY-DEDUP-0001"
    text = "confinement of radioactive material"

    top_level_path = config.safety_text_path(report)
    top_level_path.parent.mkdir(parents=True, exist_ok=True)
    top_level_path.write_text(text, encoding="utf-8")

    normalized_path = config.safety_normalized_path(report)
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_path.write_text(text, encoding="utf-8")

    counts = score_document_frequency(
        {"confinement"}, config, genre="safety", reports=[report]
    )

    assert counts["confinement"] == 1


def test_safety_df_scan_ignores_reports_not_in_the_requested_list(tmp_path) -> None:
    """A safety source's normalized text is only scanned when its id is in
    the `reports` list passed to `score_document_frequency` -- the corpus
    is scoped to the requested sources, not every source ever cached under
    `safety_dir`."""
    config = Config(corpus_dir=tmp_path)
    included, excluded = "SAFETY-DEDUP-0002", "SAFETY-DEDUP-0003"
    for report in (included, excluded):
        normalized_path = config.safety_normalized_path(report)
        normalized_path.parent.mkdir(parents=True, exist_ok=True)
        normalized_path.write_text("residual heat removal", encoding="utf-8")

    counts = score_document_frequency(
        {"residual"}, config, genre="safety", reports=[included]
    )

    assert counts["residual"] == 1
