"""Segmenter tests (task 9.4, design.md D5).

Covers the offset round-trip guarantee (``normalized_text[char_start:
char_end] == text`` for every emitted segment) and the "scientific text is
not over-split" requirement (decimals/abbreviations must not trigger a
false sentence boundary).

The final test, ``test_run_normalize_writes_expected_artifacts``, exercises
the full ``run_normalize`` pipeline (normalize + segment + write) against a
temporary ``Config``/corpus dir. It depends on the merged normalizer and
segmenter implementations to pass — that is expected in pass 1.
"""

from __future__ import annotations

import json

from msr_extraction.config import Config
from msr_extraction.segmenter import Segment, run_normalize, segment

# Multi-sentence, multi-paragraph normalized text including a decimal
# (0.084) and an abbreviation (approx.) inside the same sentence.
NORMALIZED_SAMPLE = (
    "The measured decay constant was 0.084 per second, approx. matching "
    "the reference value. The sample was then annealed for two hours in "
    "argon.\n\n"
    "A second paragraph begins here. It reports a second, unrelated "
    "measurement."
)


def test_segment_offsets_round_trip() -> None:
    segments = segment(NORMALIZED_SAMPLE, "ORNL-TM-0000")
    assert segments, "segment() must return at least one Segment"
    for seg in segments:
        assert isinstance(seg, Segment)
        assert NORMALIZED_SAMPLE[seg.char_start : seg.char_end] == seg.text


def test_segment_does_not_over_split_decimals_and_abbreviations() -> None:
    segments = segment(NORMALIZED_SAMPLE, "ORNL-TM-0000")
    matching = [s for s in segments if "0.084" in s.text]
    assert len(matching) == 1, "the decimal must not cause a spurious split"
    sentence = matching[0].text
    # The abbreviation "approx." must stay inside the same segment as the
    # decimal, i.e. the sentence isn't split at either internal period.
    assert "approx." in sentence
    assert "reference value" in sentence


def test_segment_indices_are_sequential_per_report() -> None:
    segments = segment(NORMALIZED_SAMPLE, "ORNL-TM-0000")
    indices = [s.index for s in segments]
    assert indices == sorted(indices)
    assert all(s.report == "ORNL-TM-0000" for s in segments)


def test_run_normalize_writes_expected_artifacts(tmp_path) -> None:
    config = Config(corpus_dir=tmp_path)
    report_number = "ORNL-TM-0001"
    ocr_relative_path = "ocr/ORNL-TM-0001.txt"

    # Fake OCR sidecar staged under the (fake) msr-archive checkout dir,
    # mirroring the layout acquisition (D1) produces.
    ocr_file = config.archive_dir / ocr_relative_path
    ocr_file.parent.mkdir(parents=True, exist_ok=True)
    ocr_file.write_text(
        "The measured decay constant was 0.084 per second, approx. "
        "matching the reference value.\n",
        encoding="utf-8",
    )

    run_normalize(report_number, config, ocr_relative_path)

    report_dir = config.report_dir(report_number)
    normalized_path = report_dir / "normalized.txt"
    segments_path = report_dir / "segments.jsonl"

    assert normalized_path.exists()
    assert segments_path.exists()

    normalized_text = normalized_path.read_text(encoding="utf-8")
    lines = [line for line in segments_path.read_text(encoding="utf-8").splitlines() if line]
    assert lines, "segments.jsonl must contain at least one record"

    for line in lines:
        record = json.loads(line)
        assert set(record.keys()) == {"report", "index", "text", "char_start", "char_end"}
        assert (
            normalized_text[record["char_start"] : record["char_end"]] == record["text"]
        )
