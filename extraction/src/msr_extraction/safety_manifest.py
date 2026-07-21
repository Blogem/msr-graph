"""Committed, attributed manifest of the safety-genre sources.

`ingest-iaea-safety` (chunk 11) design.md D1/D2, task 1.2. Mirrors the role
`manifest.py` plays for the msr-archive corpus, but for the four safety
sources `scripts/fetch-safety-sources.sh` caches into the gitignored
`data/safety/` directory: this module is the tracked, structured record of
*which* sources those are, their attribution (publisher/rights/URL/date),
and the section/page scope actually ingested from each cached PDF.

Unlike ``manifest.py`` there is nothing to parse — the safety corpus is a
small, fixed, hand-curated set of four sources (not a hundreds-of-rows
README table), so the manifest is declared directly as data rather than
derived from a document. Attribution is mandatory (design.md D2/D5): IAEA
SRS-123 is (c) all-rights-reserved, so every source carries a rights
statement and only short attributed quotes are ever extracted, never full
verbatim text (see ``safety_acquire.py``'s section scoping).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SafetySource:
    """One safety-genre source's attribution + ingested section scope.

    ``page_ranges`` is a tuple of 1-indexed, inclusive ``(start, end)`` page
    pairs into the cached PDF (``pypdf``'s own page indexing is 0-indexed;
    callers convert), or ``None`` when the whole document is in scope.
    ``sections`` is a human-readable note naming the corresponding
    section/page scope (not machine-parsed) so the manifest is
    self-documenting when read directly.
    """

    id: str
    title: str
    publisher: str
    rights: str
    url: str
    date: str
    pdf_filename: str
    page_ranges: tuple[tuple[int, int], ...] | None
    sections: str


# IAEA Safety Reports Series No. 123 (PUB2027) — "Applicability of IAEA
# Safety Standards to Non-Water Cooled Reactors and Small Modular Reactors"
# (Vienna, 2023). Section-scoped (design.md D1) to keep the safety genre
# focused on its MSR-relevant content rather than flooding the miner/agent
# with 292 pp of general standards-applicability text.
#
# Page ranges determined by locating each section's heading and the next
# section's heading in the cached PDF's extracted text (pypdf, 1-indexed
# page numbers; the PDF's own printed page numbers run ~10 pages behind the
# PDF page index because of the front-matter/TOC pages):
#   - Sec. 2.1.2.5 "Molten salt reactors" (printed p. 7) begins and ends on
#     PDF page 17 — bounded by 2.1.2.4 (top of PDF p. 17) and 2.1.2.6
#     (bottom of PDF p. 17 / top of p. 18) — a single-page subsection.
#   - Sec. 3.2 "Design" (printed pp. 40-78) spans PDF pages 50-88 — bounded
#     by the "3.2. DESIGN" heading (PDF p. 50) and the next top-level
#     heading "3.3. CONSTRUCTION" (PDF p. 89). This is also where the
#     report's own statement of the three fundamental safety functions
#     ("confinement of radioactive material ... control of reactivity and
#     heat removal", Sec. 3.2.1.3) lives (PDF p. 52).
#   - Sec. 5.1.8 "Moving-fuel reactors and continuous on-line refuelling"
#     (printed pp. 221-227), including its 5.1.8.2 "Liquid fuelled molten
#     salt reactors" subsection, spans PDF pages 231-237 — bounded by its
#     own heading (PDF p. 231) and the next subsection heading "5.1.9. Lack
#     of measurement technologies..." (PDF p. 238).
PUB2027_SRS_123 = SafetySource(
    id="PUB2027-SRS-123",
    title=(
        "Applicability of IAEA Safety Standards to Non-Water Cooled "
        "Reactors and Small Modular Reactors"
    ),
    publisher="IAEA",
    rights="© IAEA — all rights reserved",
    url="https://www-pub.iaea.org/MTCD/Publications/PDF/PUB2027_Web.pdf",
    date="2023-11",
    pdf_filename="PUB2027_SRS-123.pdf",
    page_ranges=((17, 17), (50, 88), (231, 237)),
    sections="§2.1.2.5 / §3.2 / §5.1.8",
)

# GIF (Holcomb) MSR safety analysis — the public stand-in for a not-yet-
# published GIF MSR-specific Safety Design Criteria report (design.md
# Risks). Ingested whole: only 32 pages, entirely MSR-specific.
GIF_HOLCOMB_MSR_SAFETY = SafetySource(
    id="GIF-Holcomb-MSR-safety",
    title="Molten Salt Reactor Safety Analysis - A U.S. Perspective",
    publisher="Generation IV International Forum",
    rights="public",
    url=(
        "https://www.gen-4.org/sites/default/files/2024-09/"
        "Dr.%20Dave%20Holcomb%2026%20AUG%202020_GIF.pdf"
    ),
    date="2020-08-26",
    pdf_filename="GIF_Holcomb_MSR-safety-analysis.pdf",
    page_ranges=None,
    sections="whole document",
)

# ORNL/TM-2006/12 — coolant-selection assessment organized by the exact
# thermophysical properties already in the seed T-Box (melting point,
# vapor pressure, viscosity, thermal conductivity, heat capacity).
# Ingested whole.
ORNL_TM_2006_12 = SafetySource(
    id="ORNL-TM-2006-12",
    title=(
        "Assessment of Candidate Molten Salt Coolants for the Advanced "
        "High-Temperature Reactor (AHTR)"
    ),
    publisher="Oak Ridge National Laboratory",
    rights="public",
    url="https://info.ornl.gov/sites/publications/Files/Pub57476.pdf",
    date="2006-03",
    pdf_filename="ORNL-TM-2006-12_coolant-assessment.pdf",
    page_ranges=None,
    sections="whole document",
)

# ORNL MSR technical & safety considerations (secondary requirement-layer
# context). Ingested whole.
ORNL_MSR_TECH_SAFETY = SafetySource(
    id="ORNL-MSR-tech-safety",
    title=(
        "Molten Salt Reactor Technical and Safety Considerations Outside "
        "of Guidance Documents"
    ),
    publisher="Oak Ridge National Laboratory",
    rights="public",
    url="https://info.ornl.gov/sites/publications/Files/Pub181692.pdf",
    date="2022-07",
    pdf_filename="ORNL_MSR-technical-safety-considerations.pdf",
    page_ranges=None,
    sections="whole document",
)

#: The four safety-genre sources (design.md D1/D2, tasks 1.2/2.1), in fetch
#: order (mirroring ``scripts/fetch-safety-sources.sh``).
SAFETY_SOURCES: tuple[SafetySource, ...] = (
    PUB2027_SRS_123,
    GIF_HOLCOMB_MSR_SAFETY,
    ORNL_TM_2006_12,
    ORNL_MSR_TECH_SAFETY,
)


def get_source(source_id: str) -> SafetySource:
    """Return the :class:`SafetySource` for ``source_id``.

    Raises ``KeyError`` if no source with that id is in :data:`SAFETY_SOURCES`
    (mirrors ``manifest.resolve_ocr_path``'s not-found behavior).
    """
    for source in SAFETY_SOURCES:
        if source.id == source_id:
            return source
    raise KeyError(source_id)
