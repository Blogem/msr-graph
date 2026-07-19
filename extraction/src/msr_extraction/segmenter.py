"""Sentence segmentation of normalized document text.

Splits ``normalized.txt`` into sentences with absolute character offsets
(design.md D5) so downstream chunks can mint deterministic mention IRIs
directly against the same artifact they read.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from msr_extraction.config import Config

# Matches a run of two or more consecutive newlines, used to split
# `normalized_text` into paragraphs while preserving the ability to
# recompute each paragraph's absolute starting offset in the source text.
_PARAGRAPH_BREAK_RE = re.compile(r"\n{2,}")

# pysbd's built-in English abbreviation table (pysbd/lang/common/standard.py)
# is tuned for general prose (titles, addresses, states) and misses common
# scientific-report abbreviations. "approx." is the one this pipeline's
# corpus regularly hits (e.g. "approx. 900 K"), so it is added to the
# abbreviation list once, in place, before segmenting.
_EXTRA_ABBREVIATIONS = ("approx",)


def _ensure_extra_abbreviations() -> None:
    """Extend pysbd's English abbreviation table with domain-specific terms.

    Idempotent: safe to call on every :func:`segment` invocation.
    """
    from pysbd.lang.english import English

    for abbr in _EXTRA_ABBREVIATIONS:
        if abbr not in English.Abbreviation.ABBREVIATIONS:
            English.Abbreviation.ABBREVIATIONS.append(abbr)


@dataclass(frozen=True)
class Segment:
    """One sentence-level span within a report's normalized text."""

    report: str
    index: int
    text: str
    char_start: int
    char_end: int


def segment(normalized_text: str, report: str) -> list[Segment]:
    """Split normalized text into sentence :class:`Segment` records.

    Splits per paragraph using ``pysbd`` (Python Sentence Boundary
    Disambiguation) while keeping GLOBAL absolute character offsets into
    ``normalized_text`` (not paragraph-relative). For every returned
    segment, ``normalized_text[char_start:char_end] == text`` must hold.

    # deferred import: `import pysbd` belongs inside this function body —
    # pysbd is added to pyproject by a parallel build-wiring change and is
    # not available at module import time in this branch.
    """
    import pysbd

    _ensure_extra_abbreviations()
    splitter = pysbd.Segmenter(language="en", clean=False)

    segments: list[Segment] = []
    index = 0
    paragraph_start = 0

    for match in [*_PARAGRAPH_BREAK_RE.finditer(normalized_text), None]:
        paragraph_end = match.start() if match is not None else len(normalized_text)
        paragraph = normalized_text[paragraph_start:paragraph_end]

        # Cursor into `normalized_text` (absolute), used to locate each
        # sentence pysbd returns so we never trust its string byte-for-byte —
        # we re-find it in the source to guarantee the offset round trip.
        cursor = paragraph_start
        for sentence in splitter.segment(paragraph):
            stripped = sentence.strip()
            if not stripped:
                continue
            found = normalized_text.find(stripped, cursor)
            if found == -1:
                # Fallback: search from the paragraph start in case cursor
                # advanced past this sentence due to overlapping whitespace.
                found = normalized_text.find(stripped, paragraph_start)
            if found == -1:
                continue
            start = found
            end = found + len(stripped)
            segments.append(
                Segment(
                    report=report,
                    index=index,
                    text=normalized_text[start:end],
                    char_start=start,
                    char_end=end,
                )
            )
            index += 1
            cursor = end

        if match is None:
            break
        paragraph_start = match.end()

    return segments


def run_normalize(report_number: str, config: Config, ocr_path: str) -> None:
    """Normalize, write, and segment one curated report's OCR text.

    Reads the OCR sidecar at ``ocr_path``, runs it through
    :func:`msr_extraction.normalizer.normalize_text`, writes the result to
    ``config.report_dir(report_number) / "normalized.txt"`` (creating the
    report directory if needed), segments the normalized text with
    :func:`segment`, and writes one JSON object per sentence to
    ``config.report_dir(report_number) / "segments.jsonl"``.
    """
    from msr_extraction.normalizer import normalize_text

    raw_path = config.archive_dir / ocr_path
    raw_text = raw_path.read_text(encoding="utf-8", errors="replace")
    normalized = normalize_text(raw_text)

    report_dir = config.report_dir(report_number)
    report_dir.mkdir(parents=True, exist_ok=True)

    (report_dir / "normalized.txt").write_text(normalized, encoding="utf-8")

    segments = segment(normalized, report_number)
    with (report_dir / "segments.jsonl").open("w", encoding="utf-8") as fh:
        for seg in segments:
            record = {
                "report": seg.report,
                "index": seg.index,
                "text": seg.text,
                "char_start": seg.char_start,
                "char_end": seg.char_end,
            }
            fh.write(json.dumps(record, ensure_ascii=False))
            fh.write("\n")
