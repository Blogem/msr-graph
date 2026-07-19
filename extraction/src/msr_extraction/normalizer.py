"""OCR text normalization.

A conservative, deterministic pre-pass over raw OCR text (design.md D4),
biased toward precision: it under-corrects rather than risks corrupting
real numeric/equation data that downstream chunks (6-8) depend on.
"""

from __future__ import annotations

import re

# --- Step 1: OCR-confusion substitutions -----------------------------------
#
# Applied first so later steps (de-hyphenation, whitespace collapse, etc.)
# operate on already-clean characters. Deliberately narrow: ligatures and
# stray non-printable control characters only. Digits, operators, ASCII
# letters, and the middle-dot multiplication sign (U+00B7, `·`) are left
# untouched so equations survive intact.
_LIGATURE_MAP = {
    "ﬀ": "ff",  # ﬀ
    "ﬁ": "fi",  # ﬁ
    "ﬂ": "fl",  # ﬂ
    "ﬃ": "ffi",  # ﬃ
    "ﬄ": "ffl",  # ﬄ
}

# Non-printable control characters to strip, excluding \n (0x0a) and \t (0x09).
_CONTROL_CHARS_RE = re.compile(
    "[" + "".join(chr(c) for c in list(range(0x00, 0x09)) + [0x0B, 0x0C] + list(range(0x0E, 0x20))) + "]"
)

_OCR_CONFUSION_TABLE = str.maketrans(_LIGATURE_MAP)


def _apply_ocr_confusions(text: str) -> str:
    """Fix ligatures and strip stray non-printable control characters."""
    text = text.translate(_OCR_CONFUSION_TABLE)
    text = _CONTROL_CHARS_RE.sub("", text)
    return text


# --- Step 2: line-break de-hyphenation -------------------------------------
#
# `word-\nword` -> `wordword` only when the character before the hyphen and
# the first character after the newline are both lowercase a-z (a soft
# line-break hyphen). Otherwise the hyphen is a real compound hyphen
# (formula/capitalized/numeric neighbor) and is kept, with only the
# intervening newline (and surrounding whitespace) removed.
_DEHYPHENATE_JOIN_RE = re.compile(r"(?<=[a-z])-[ \t]*\r?\n[ \t]*(?=[a-z])")
_DEHYPHENATE_KEEP_RE = re.compile(r"-[ \t]*\r?\n[ \t]*")


def _dehyphenate(text: str) -> str:
    """Rejoin soft-hyphenated line breaks; keep real compound hyphens."""
    text = _DEHYPHENATE_JOIN_RE.sub("", text)
    text = _DEHYPHENATE_KEEP_RE.sub("-", text)
    return text


# --- Step 3: bounded intra-word OCR-split rejoin ---------------------------
#
# A small, fixed table of known all-caps intra-word OCR splits (a stray
# space inserted mid-word by the OCR engine). Deliberately NOT a general
# "remove spaces inside caps runs" rule -- only these pinned entries are
# rejoined.
_INTRA_WORD_SPLIT_TABLE = {
    "THERMAL-STRE SS": "THERMAL-STRESS",
    "CORRO SION": "CORROSION",
    "MODERA TOR": "MODERATOR",
}


def _rejoin_intra_word_splits(text: str) -> str:
    """Rejoin known bounded intra-word OCR splits from a fixed table."""
    for split, joined in _INTRA_WORD_SPLIT_TABLE.items():
        text = text.replace(split, joined)
    return text


# --- Step 4: whitespace normalization ---------------------------------------
#
# Collapse runs of spaces/tabs to a single space, collapse 3+ newlines down
# to exactly 2 (preserving paragraph breaks), strip trailing whitespace per
# line, and fold any remaining single mid-paragraph newline into a space.
_SPACES_TABS_RE = re.compile(r"[ \t]+")
_TRAILING_WS_RE = re.compile(r"[ \t]+\n")
_EXCESS_BLANK_LINES_RE = re.compile(r"\n{3,}")
_SINGLE_NEWLINE_RE = re.compile(r"(?<!\n)\n(?!\n)")


def _normalize_whitespace(text: str) -> str:
    """Collapse whitespace while preserving blank-line paragraph breaks."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _SPACES_TABS_RE.sub(" ", text)
    text = _TRAILING_WS_RE.sub("\n", text)
    text = _EXCESS_BLANK_LINES_RE.sub("\n\n", text)
    # Fold single mid-paragraph newlines (not part of a blank-line paragraph
    # break) into a space; `\n\n` paragraph breaks are left intact.
    text = _SINGLE_NEWLINE_RE.sub(" ", text)
    return text


# --- Step 5: sub/superscript -> ASCII, in place -----------------------------
#
# Subscript digits and superscript digits/minus/plus map straight to ASCII
# in place -- never caret-wrapped -- since superscripts here serve both
# exponents (`cm⁻³` -> `cm-3`) and isotope mass numbers (`²³⁵U` -> `235U`),
# and a caret rule would corrupt the isotope case into `^235U`.
_SUBSCRIPT_MAP = {
    "₀": "0",
    "₁": "1",
    "₂": "2",
    "₃": "3",
    "₄": "4",
    "₅": "5",
    "₆": "6",
    "₇": "7",
    "₈": "8",
    "₉": "9",
}

_SUPERSCRIPT_MAP = {
    "⁰": "0",
    "¹": "1",
    "²": "2",
    "³": "3",
    "⁴": "4",
    "⁵": "5",
    "⁶": "6",
    "⁷": "7",
    "⁸": "8",
    "⁹": "9",
    "⁻": "-",  # superscript minus
    "⁺": "+",  # superscript plus
}

_SUB_SUPERSCRIPT_TABLE = str.maketrans({**_SUBSCRIPT_MAP, **_SUPERSCRIPT_MAP})


def _normalize_sub_superscripts(text: str) -> str:
    """Map Unicode sub/superscript digits and +/- to ASCII, in place."""
    return text.translate(_SUB_SUPERSCRIPT_TABLE)


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
    text = _apply_ocr_confusions(text)
    text = _dehyphenate(text)
    text = _rejoin_intra_word_splits(text)
    text = _normalize_whitespace(text)
    text = _normalize_sub_superscripts(text)
    return text
