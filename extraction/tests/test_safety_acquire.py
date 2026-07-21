"""Safety-source pypdf extraction + section-scoping tests (openspec/changes/
ingest-iaea-safety, spec ``safety-source-acquisition``, tasks 8.1/8.2).

Hermetic and fully offline: builds a small text-layer PDF fixture on the
fly via ``tests/fixtures/pdf_builder.build_text_pdf`` (a committed,
dependency-free helper -- see that module's docstring for why a hand-built
PDF rather than a binary blob or a ``reportlab`` dependency) and drives the
pinned ``msr_extraction.safety_acquire`` module against it. No network
call, no live GraphDB, no LLM.

ASSUMPTION (pass-1, flagged in the tester handoff report for
reconciliation at merge): ``safety_manifest.py``/``safety_acquire.py`` do
not exist yet on this isolated pass-1 branch -- every test below is
written against the pinned module-interface contract handed to the
tester (design.md D1/D8, tasks 1.2-1.4), not against any implementation,
and is expected to fail with a collection error until the coder's modules
land. Two shape assumptions are baked into the fixtures, flagged again
below: (1) ``SafetySource.page_ranges`` is ``list[tuple[int, int]] | None``
of 1-indexed, inclusive page numbers (``None``/empty = whole document,
matching the GIF/ORNL "whole" scope vs. SRS-123's three disjoint
section-derived ranges); (2) ``extract_pdf_text``/``normalize_and_segment``
return :class:`pathlib.Path` values equal to the corresponding
``config.safety_*`` path helpers already landed in ``config.py`` (chunk 11
Wave-1 plumbing) -- ``safety_text_path``, ``safety_normalized_path``,
``safety_segments_path``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))
from pdf_builder import build_text_pdf  # noqa: E402

from msr_extraction.config import Config  # noqa: E402
from msr_extraction.safety_acquire import (  # noqa: E402
    extract_pdf_text,
    normalize_and_segment,
)
from msr_extraction.safety_manifest import SafetySource  # noqa: E402

SOURCE_ID = "TEST-SAFETY-SOURCE"

# A short, attributed paraphrase-length quote -- IAEA SRS-123's three
# fundamental safety functions (design.md context, spike doc) -- kept
# short per D5/IAEA (C).
CONFINEMENT_TEXT = (
    "Confinement of radioactive material is a fundamental safety function."
)
HEAT_REMOVAL_TEXT = "Removal of residual heat keeps the core cool."
INTRO_TEXT = "Page one introductory boilerplate not in scope."
APPENDIX_TEXT = "Page four appendix boilerplate not in scope."


def _whole_doc_source(pdf_filename: str) -> SafetySource:
    return SafetySource(
        id=SOURCE_ID,
        title="Test Safety Source",
        publisher="IAEA",
        rights="(c) IAEA. Short excerpt used for testing under fair use.",
        url="https://www-pub.iaea.org/example/test-safety-source",
        date="2027",
        pdf_filename=pdf_filename,
        page_ranges=None,
        sections=[],
    )


def _scoped_source(pdf_filename: str) -> SafetySource:
    return SafetySource(
        id=SOURCE_ID,
        title="Test Safety Source (Scoped)",
        publisher="IAEA",
        rights="(c) IAEA. Short excerpt used for testing under fair use.",
        url="https://www-pub.iaea.org/example/test-safety-source",
        date="2027",
        pdf_filename=pdf_filename,
        page_ranges=[(2, 3)],  # 1-indexed inclusive: only pages 2 and 3
        sections=["Test Section"],
    )


def _write_pdf(config: Config, pdf_filename: str, pages: list[str]) -> None:
    config.safety_dir.mkdir(parents=True, exist_ok=True)
    pdf_bytes = build_text_pdf(pages)
    (config.safety_dir / pdf_filename).write_bytes(pdf_bytes)


# --- 8.1: pypdf extractor, offline ------------------------------------------


def test_extract_pdf_text_returns_the_known_single_page_text(tmp_path) -> None:
    """Scenario basis: a tiny, committed text-layer PDF fixture extracts to
    its known text with no network access."""
    config = Config(corpus_dir=tmp_path)
    _write_pdf(config, "single-page.pdf", [CONFINEMENT_TEXT])
    source = _whole_doc_source("single-page.pdf")

    result_path = extract_pdf_text(source, config)

    assert result_path == config.safety_text_path(source.id)
    extracted = result_path.read_text(encoding="utf-8")
    assert "Confinement of radioactive material" in extracted


def test_extract_pdf_text_whole_document_includes_every_page(tmp_path) -> None:
    """No ``page_ranges`` scope (the GIF/ORNL "whole document" case,
    design.md D1) extracts every page's text."""
    config = Config(corpus_dir=tmp_path)
    pages = [INTRO_TEXT, CONFINEMENT_TEXT, HEAT_REMOVAL_TEXT, APPENDIX_TEXT]
    _write_pdf(config, "whole-doc.pdf", pages)
    source = _whole_doc_source("whole-doc.pdf")

    extracted = extract_pdf_text(source, config).read_text(encoding="utf-8")

    for page_text in pages:
        assert page_text in extracted


# --- 8.2: section-scoping ----------------------------------------------------


def test_extract_pdf_text_scoped_source_includes_only_scoped_pages(tmp_path) -> None:
    """Scenario: "Only scoped sections are extracted" -- a source with a
    declared ``page_ranges`` (SRS-123-shaped: a subset of a larger PDF)
    extracts only the scoped pages' text; out-of-scope pages are excluded."""
    config = Config(corpus_dir=tmp_path)
    pages = [INTRO_TEXT, CONFINEMENT_TEXT, HEAT_REMOVAL_TEXT, APPENDIX_TEXT]
    _write_pdf(config, "scoped-doc.pdf", pages)
    source = _scoped_source("scoped-doc.pdf")  # pages 2-3 (1-indexed)

    extracted = extract_pdf_text(source, config).read_text(encoding="utf-8")

    assert CONFINEMENT_TEXT in extracted
    assert HEAT_REMOVAL_TEXT in extracted
    assert INTRO_TEXT not in extracted
    assert APPENDIX_TEXT not in extracted


# --- 8.2: normalize + segment reuse the chunk-5 pipeline format -------------


def test_normalize_and_segment_produces_normalized_text_and_segments(tmp_path) -> None:
    """Scenario: "Normalized artifacts match the pipeline input format" --
    after extraction, running the (reused, not forked) chunk-5
    normalizer/segmenter over a safety source's raw text produces
    ``normalized.txt`` + ``segments.jsonl`` at the safety-genre paths, with
    the same offset-into-normalized-text schema the NER stages already
    consume (mirrors ``segmenter.segment``'s
    ``normalized_text[char_start:char_end] == text`` contract)."""
    config = Config(corpus_dir=tmp_path)
    _write_pdf(config, "single-page.pdf", [CONFINEMENT_TEXT])
    source = _whole_doc_source("single-page.pdf")
    extract_pdf_text(source, config)

    normalized_path, segments_path = normalize_and_segment(source, config)

    assert normalized_path == config.safety_normalized_path(source.id)
    assert segments_path == config.safety_segments_path(source.id)
    assert normalized_path.exists()
    assert segments_path.exists()

    normalized_text = normalized_path.read_text(encoding="utf-8")
    assert "Confinement of radioactive material" in normalized_text

    lines = [
        line for line in segments_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(lines) >= 1
    for line in lines:
        record = json.loads(line)
        assert "text" in record
        assert "char_start" in record
        assert "char_end" in record
        start, end = record["char_start"], record["char_end"]
        assert normalized_text[start:end] == record["text"]
