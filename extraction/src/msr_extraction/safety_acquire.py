"""Safety-source PDF text extraction, normalization, and segmentation.

`ingest-iaea-safety` (chunk 11) design.md D1, tasks 1.3/1.4. The safety
sources are text-layer PDFs (not scanned OCR sidecars like the msr-archive
corpus), so a thin ``pypdf``-based extractor converts the cached PDF into
raw text, honoring the manifest's declared section/page scope
(:mod:`msr_extraction.safety_manifest`). Everything after that raw-text
step reuses the existing chunk-5 normalizer + segmenter UNCHANGED, so the
safety genre lands in the identical ``normalized.txt`` + ``segments.jsonl``
format the NER stages already consume.
"""

from __future__ import annotations

import json
from pathlib import Path

from msr_extraction.config import Config
from msr_extraction.safety_manifest import SafetySource


def extract_pdf_text(source: SafetySource, config: Config) -> Path:
    """Extract ``source``'s cached PDF text, honoring its page scope.

    Reads ``config.safety_dir / source.pdf_filename`` with ``pypdf``. The
    IAEA SRS-123 PDF is encrypted with an empty user password (a common
    IAEA-publication artifact, not real access control); if
    ``reader.is_encrypted``, it is decrypted with ``reader.decrypt("")``
    before any page is read.

    When ``source.page_ranges`` is ``None``, every page's text is extracted
    (whole-document sources). Otherwise, only the pages covered by the
    declared 1-indexed inclusive ``(start, end)`` ranges are extracted, in
    range order, each range's pages joined with a blank line so this
    ``.txt`` output stays a well-formed input to
    :func:`msr_extraction.normalizer.normalize_text` (which treats a blank
    line as a paragraph break) even though the underlying pages are
    non-contiguous in the source PDF.

    Writes the result to ``config.safety_text_path(source.id)`` (creating
    the safety cache directory if needed) and returns that path.
    """
    import pypdf

    pdf_path = config.safety_dir / source.pdf_filename
    reader = pypdf.PdfReader(pdf_path)
    if reader.is_encrypted:
        reader.decrypt("")

    total_pages = len(reader.pages)
    if source.page_ranges is None:
        page_indices: list[int] = list(range(total_pages))
    else:
        page_indices = []
        for start, end in source.page_ranges:
            page_indices.extend(range(start - 1, end))

    page_texts = [reader.pages[i].extract_text() or "" for i in page_indices]
    text = "\n\n".join(page_texts)

    out_path = config.safety_text_path(source.id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return out_path


def normalize_and_segment(source: SafetySource, config: Config) -> tuple[Path, Path]:
    """Normalize + segment ``source``'s extracted raw text.

    Reads ``config.safety_text_path(source.id)`` (written by
    :func:`extract_pdf_text`), runs it through
    :func:`msr_extraction.normalizer.normalize_text` and then
    :func:`msr_extraction.segmenter.segment` — REUSING those chunk-5
    functions unchanged, never forking them (design.md D1) — and writes:

    - ``config.safety_normalized_path(source.id)`` — the normalized text.
    - ``config.safety_segments_path(source.id)`` — one JSON object per
      line, matching the chunk-5 ``segments.jsonl`` schema exactly
      (``report``, ``index``, ``text``, ``char_start``, ``char_end``),
      with ``report`` set to ``source.id`` so downstream NER stages treat
      the safety source as just another report/corpus entry.

    Returns ``(normalized_path, segments_path)``.
    """
    from msr_extraction.normalizer import normalize_text
    from msr_extraction.segmenter import segment

    raw_path = config.safety_text_path(source.id)
    raw_text = raw_path.read_text(encoding="utf-8", errors="replace")
    normalized = normalize_text(raw_text)

    report_dir = config.safety_report_dir(source.id)
    report_dir.mkdir(parents=True, exist_ok=True)

    normalized_path = config.safety_normalized_path(source.id)
    normalized_path.write_text(normalized, encoding="utf-8")

    segments = segment(normalized, source.id)
    segments_path = config.safety_segments_path(source.id)
    with segments_path.open("w", encoding="utf-8") as fh:
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

    return normalized_path, segments_path
