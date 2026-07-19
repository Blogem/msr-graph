"""Manifest parser tests (task 9.3, design.md D3).

Parses a committed excerpt of a real msr-archive ``README.md`` table
(``fixtures/manifest_excerpt.md``) shaped like the real manifest: a header
row, a ``---`` separator row, two valid data rows (using the real
DATA_SCOPE anchors ORNL-TM-2316 / ORNL-TM-0728), and one malformed
(wrong-column-count) row.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from msr_extraction.manifest import ManifestRecord, parse_manifest, resolve_ocr_path

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "manifest_excerpt.md"

EXPECTED_RECORDS = [
    ManifestRecord(
        report_number="ORNL-TM-2316",
        title="Physical Properties of Molten-Salt Reactor Fuel, Coolant, and Flush Salts",
        date="1968-11-01",
        ocr_path="ocr/ORNL-TM-2316.txt",
    ),
    ManifestRecord(
        report_number="ORNL-TM-0728",
        title="MSRE Design and Operations Report Part I: Reactor Design",
        date="1965-01-01",
        ocr_path="ocr/ORNL-TM-0728.txt",
    ),
]


def _readme_text() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


def test_parse_manifest_yields_exactly_the_valid_records() -> None:
    records = parse_manifest(_readme_text())
    assert records == EXPECTED_RECORDS


def test_parse_manifest_skips_header_separator_and_malformed_rows() -> None:
    records = parse_manifest(_readme_text())
    # Only the two conforming data rows should survive.
    assert len(records) == 2
    report_numbers = {r.report_number for r in records}
    assert "Report Number" not in report_numbers  # header row
    assert "---" not in report_numbers  # separator row
    assert "only-two-columns" not in report_numbers  # malformed row


def test_resolve_ocr_path_returns_sidecar_for_known_report() -> None:
    records = parse_manifest(_readme_text())
    assert resolve_ocr_path(records, "ORNL-TM-2316") == "ocr/ORNL-TM-2316.txt"
    assert resolve_ocr_path(records, "ORNL-TM-0728") == "ocr/ORNL-TM-0728.txt"


def test_resolve_ocr_path_raises_keyerror_for_unknown_report() -> None:
    records = parse_manifest(_readme_text())
    with pytest.raises(KeyError):
        resolve_ocr_path(records, "ORNL-DOES-NOT-EXIST")
