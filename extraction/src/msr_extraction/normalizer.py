"""OCR text normalization.

A conservative, deterministic pre-pass over raw OCR text (design.md D4),
biased toward precision: it under-corrects rather than risks corrupting
real numeric/equation data that downstream chunks (6-8) depend on.
"""

from __future__ import annotations


def normalize_text(text: str) -> str:
    """Deterministically normalize raw OCR text.

    Applies, in order:

    1. Line-break de-hyphenation — join ``word-\\nword`` into ``wordword``
       when both sides are lowercase alphabetic (a soft-hyphenated line
       break); keep the hyphen when a neighbor is capitalized or numeric
       (e.g. ``LiF-\\nBeF2`` stays hyphenated — a real compound hyphen).
    2. Whitespace normalization — collapse runs of spaces/newlines within a
       paragraph to single separators, and rejoin obvious bounded intra-word
       OCR splits in all-caps runs (e.g. ``THERMAL-STRE SS`` ->
       ``THERMAL-STRESS``) via a small fixture-driven table, not a general
       "remove all spaces" rule.
    3. Sub/superscript-to-ASCII mapping, applied in place — subscripts map
       inline (``BeF₂`` -> ``BeF2``); superscript digits/minus also map
       in place, not caret-wrapped (``cm⁻³`` -> ``cm-3``,
       ``²³⁵U`` -> ``235U``), since superscripts here serve
       both exponents and isotope mass numbers and a caret form would
       corrupt the isotope case.
    4. Common OCR-confusion substitutions — a small, documented table of
       conservative fixes (stray control characters, ligatures, etc).

    Equations (e.g. ``η = 0.084·exp(4340/T)``) must survive intact:
    no numeric or operator rewriting anywhere in this function.
    """
    raise NotImplementedError("tasks 5.1-5.3")
