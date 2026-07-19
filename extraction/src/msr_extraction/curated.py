"""The curated document set and evolution-target detection.

The curated set is a committed list of report numbers (design.md D2): the
DATA_SCOPE anchors plus a handful of chemistry/corrosion additions selected
so the self-evolving-ontology demo's target statements are demonstrably
present in the processed (not merely corpus-wide) text.
"""

from __future__ import annotations

import re

# The 7 confirmed DATA_SCOPE anchors (docs/DATA_SCOPE.md, "POC core document
# set"). The 3-4 chemistry/corrosion additions (INOR-8/Hastelloy-N cluster)
# are appended by the finalization step (task 4.1) once the real manifest is
# available -- these report-number strings follow docs/DATA_SCOPE.md but are
# NOT yet verified against the actual msr-archive checkout/manifest.
CURATED_REPORTS: list[str] = [
    "ORNL-TM-2316",
    "ORNL-TM-0728",
    "ORNL-CF-63-9-20",
    "ORNL-2150",
    "NSRDS-NBS-61-4",
    "ORNL-TM-3884",
    "ORNL-TM-0078",
]

# A solubility statement carrying a numeric value + unit. Matches the word
# "solubility"/"solubilities" within a small window of a number immediately
# followed (or preceded) by a physical-unit-like token. The window is
# intentionally short (<=80 chars) and the unit set intentionally narrow so
# that prose mentioning "solubility" with no attached number+unit does not
# match.
_UNIT_TOKEN = (
    r"(?:mole\s?%|wt\s?%|mol\s?%|atoms?\s?%|ppm|g/|mg/|moles?/|mol/|"
    r"×?10\s*-?\d|x\s?10)"
)
_NUMBER_TOKEN = r"\d[\d.,]*"
SOLUBILITY_RE = re.compile(
    rf"solubilit\w*.{{0,80}}?{_NUMBER_TOKEN}\s*{_UNIT_TOKEN}"
    rf"|{_NUMBER_TOKEN}\s*{_UNIT_TOKEN}.{{0,80}}?solubilit\w*",
    re.IGNORECASE | re.DOTALL,
)

# Graphite-as-moderator prose: "graphite" and a form of "moderate" within a
# short window of each other, in either order ("graphite moderator",
# "graphite as the moderator", "moderated by graphite", ...).
GRAPHITE_MODERATOR_RE = re.compile(
    r"graphite.{0,60}?moderat(?:or|ing|es|e)\w*"
    r"|moderat(?:or|ing|es|e)\w*.{0,60}?graphite",
    re.IGNORECASE | re.DOTALL,
)


def detect_evolution_targets(text: str) -> dict[str, bool]:
    """Scan curated OCR text for the evolution-demo target patterns.

    Returns a dict with two boolean keys:

    - ``"solubility"`` — True if the text contains a solubility statement
      with an associated numeric value and unit.
    - ``"graphite_moderator"`` — True if the text contains
      graphite-as-moderator prose.
    """
    return {
        "solubility": SOLUBILITY_RE.search(text) is not None,
        "graphite_moderator": GRAPHITE_MODERATOR_RE.search(text) is not None,
    }
