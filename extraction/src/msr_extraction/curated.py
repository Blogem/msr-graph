"""The curated document set and evolution-target detection.

The curated set is a committed list of report numbers (design.md D2): the
DATA_SCOPE anchors plus a handful of chemistry/corrosion additions selected
so the self-evolving-ontology demo's target statements are demonstrably
present in the processed (not merely corpus-wide) text.
"""

from __future__ import annotations

CURATED_REPORTS: list[str] = []  # populated by acquisition/finalization agents


def detect_evolution_targets(text: str) -> dict[str, bool]:
    """Scan curated OCR text for the evolution-demo target patterns.

    Returns a dict with two boolean keys:

    - ``"solubility"`` — True if the text contains a solubility statement
      with an associated numeric value and unit.
    - ``"graphite_moderator"`` — True if the text contains
      graphite-as-moderator prose.
    """
    raise NotImplementedError("task 4.2")
