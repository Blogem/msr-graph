"""msr-archive manifest parsing.

The msr-archive checkout's ``README.md`` is the only catalog of documents:
a markdown table of the shape
``| [Title](pdf) | Report-Number | Date | [txt](ocr/<id>.txt) |``.
This module turns that table into structured :class:`ManifestRecord` rows,
offline and dependency-free (task 3.1, design.md D3).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# A markdown link: `[text](target)`. Used to pull the visible text out of the
# title/report cells and the link target out of the OCR cell.
_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")

# A data row's OCR cell must contain a link whose target is an `ocr/...txt`
# sidecar path. This is the positive signal that distinguishes a real data
# row from the header row (whose OCR cell has no link at all, e.g. "OCR").
_OCR_LINK_RE = re.compile(r"\[[^\]]*\]\((?P<target>ocr/[^)]+\.txt)\)", re.IGNORECASE)

# A table separator cell looks like `---`, `:---`, `---:`, or `:---:`.
_SEPARATOR_CELL_RE = re.compile(r"^:?-{2,}:?$")


@dataclass(frozen=True)
class ManifestRecord:
    """One parsed row of the msr-archive README manifest table."""

    report_number: str
    title: str
    date: str
    ocr_path: str


def _link_text_or_raw(cell: str) -> str:
    """Return a markdown link's visible text, or the trimmed cell as-is."""
    match = _LINK_RE.search(cell)
    if match is not None:
        return match.group(1).strip()
    return cell.strip()


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
    records: list[ManifestRecord] = []

    for line in readme_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue

        cells = [cell.strip() for cell in stripped.split("|")]
        # A well-formed row starts and ends with `|`, which produces an
        # empty leading/trailing cell from the split; drop those only.
        while cells and cells[0] == "":
            cells.pop(0)
        while cells and cells[-1] == "":
            cells.pop()

        if len(cells) != 4:
            logger.warning(
                "Skipping manifest row with unexpected cell count (%d): %r",
                len(cells),
                line,
            )
            continue

        if all(_SEPARATOR_CELL_RE.match(cell) for cell in cells):
            logger.warning("Skipping manifest separator row: %r", line)
            continue

        ocr_match = _OCR_LINK_RE.search(cells[3])
        if ocr_match is None:
            logger.warning(
                "Skipping manifest row without a resolvable OCR sidecar "
                "link (likely a header or malformed row): %r",
                line,
            )
            continue

        report_number = _link_text_or_raw(cells[1])
        if not report_number:
            logger.warning(
                "Skipping manifest row with an empty report number: %r", line
            )
            continue

        title = _link_text_or_raw(cells[0])
        date = cells[2]

        records.append(
            ManifestRecord(
                report_number=report_number,
                title=title,
                date=date,
                ocr_path=ocr_match.group("target"),
            )
        )

    return records


def resolve_ocr_path(records: list[ManifestRecord], report_number: str) -> str:
    """Return the OCR sidecar path for a curated report number.

    Raises ``KeyError`` if ``report_number`` is not present in ``records``.
    """
    for record in records:
        if record.report_number == report_number:
            return record.ocr_path
    raise KeyError(report_number)
