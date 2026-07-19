"""msr-archive manifest parsing.

The msr-archive checkout's ``README.md`` is the only catalog of documents:
a markdown table of the shape
``| [Title](pdf) | Report-Number | Date | [txt](ocr/<id>.txt) |``.
This module turns that table into structured :class:`ManifestRecord` rows,
offline and dependency-free (task 3.1, design.md D3).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ManifestRecord:
    """One parsed row of the msr-archive README manifest table."""

    report_number: str
    title: str
    date: str
    ocr_path: str


def parse_manifest(readme_text: str) -> list[ManifestRecord]:
    """Parse the msr-archive README markdown table into manifest records.

    Expects rows of the shape
    ``| [Title](pdf) | Report-Number | Date | [txt](ocr/<id>.txt) |``.
    Header rows, separator rows (``---``), and any row that does not match
    the expected 4-column shape are skipped with a logged warning rather
    than raising — the README is a loosely-maintained hand-written table.
    Pure and offline: operates only on the given text, no filesystem or
    network access.
    """
    raise NotImplementedError("task 3.1")


def resolve_ocr_path(records: list[ManifestRecord], report_number: str) -> str:
    """Return the OCR sidecar path for a curated report number.

    Raises ``KeyError`` if ``report_number`` is not present in ``records``.
    """
    raise NotImplementedError("task 2.2")
