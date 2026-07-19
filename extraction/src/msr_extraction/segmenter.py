"""Sentence segmentation of normalized document text.

Splits ``normalized.txt`` into sentences with absolute character offsets
(design.md D5) so downstream chunks can mint deterministic mention IRIs
directly against the same artifact they read.
"""

from __future__ import annotations

from dataclasses import dataclass

from msr_extraction.config import Config


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
    raise NotImplementedError("task 6.1")


def run_normalize(report_number: str, config: Config, ocr_path: str) -> None:
    """Normalize, write, and segment one curated report's OCR text.

    Reads the OCR sidecar at ``ocr_path``, runs it through
    :func:`msr_extraction.normalizer.normalize_text`, writes the result to
    ``config.report_dir(report_number) / "normalized.txt"`` (creating the
    report directory if needed), segments the normalized text with
    :func:`segment`, and writes one JSON object per sentence to
    ``config.report_dir(report_number) / "segments.jsonl"``.
    """
    raise NotImplementedError("tasks 6.1-6.2")
