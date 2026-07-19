"""The curated document set and evolution-target detection.

The curated set is a committed list of report numbers (design.md D2): the
DATA_SCOPE anchors plus a handful of chemistry/corrosion additions selected
so the self-evolving-ontology demo's target statements are demonstrably
present in the processed (not merely corpus-wide) text.
"""

from __future__ import annotations

import re

# FINALIZED (2026-07-19, design.md D2 / docs/DATA_SCOPE.md, "POC core
# document set" + "Finalized curated set"): the 7 confirmed DATA_SCOPE
# anchors plus 4 chemistry/corrosion additions from the INOR-8/Hastelloy-N
# cluster, selected so the evolution-demo targets (solubility-with-unit,
# graphite-as-moderator) are demonstrably present in the curated OCR, not
# merely corpus-wide. All 11 report numbers are verified against the real
# openmsr/msr-archive README manifest (resolve_ocr_path succeeds for each)
# AND against the actual OCR sidecar files on disk.
#
# One substitution from the original DATA_SCOPE anchor list: `ORNL-CF-63-9-20`
# ("A Literature Survey of Thermal and Physical Properties of Molten Fluoride
# and Chloride Salt Mixtures") has a manifest row and a resolvable
# `ocr/ORNL-CF-63-9-20.txt` link target, but that OCR sidecar file does not
# actually exist in the openmsr/msr-archive git tree (confirmed via `git
# ls-tree -r HEAD` on the real clone -- a genuinely broken upstream link, not
# an LFS/smudge artifact, since only `*.pdf` is LFS-tracked). It is replaced
# by `ORNL-3293` ("Thermodynamic Properties of Molten-Salt Solutions", 1962),
# which fills the same "properties survey" role and has real, present OCR
# text.
CURATED_REPORTS: list[str] = [
    # -- 7 DATA_SCOPE anchors (one substituted; see note above) --
    "ORNL-TM-2316",
    "ORNL-TM-0728",
    "ORNL-3293",  # substitute for ORNL-CF-63-9-20 (missing OCR sidecar upstream)
    "ORNL-2150",
    "NSRDS-NBS-61-p4",
    "ORNL-TM-3884",
    "ORNL-TM-0078",
    # -- 4 chemistry/corrosion additions (task 4.3) --
    "ORNL-TM-2256",  # Chemical Feasibility of Fueling Molten-Salt Reactors with PuF3 -- PuF3 solubility-in-LiF-BeF2 evidence
    "ORNL-4658",  # Chemical Aspects of MSRE Operations
    "ORNL-4829",  # Intergranular Cracking of INOR-8 in the MSRE
    "ORNL-3124",  # INOR-8-Graphite-Fused Salt Compatibility Test
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
