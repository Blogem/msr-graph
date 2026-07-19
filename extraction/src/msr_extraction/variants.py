"""Pattern-variant generation for expanded exact matching.

Pure, deterministic expansion of a vocab/salt label into surface variants
(hyphen/no-hyphen, spacing, case) so common OCR-surface variation is matched
by cheap exact spaCy patterns (`PhraseMatcher`/`EntityRuler`, `attr="LOWER"`)
rather than requiring fuzzy matching (design.md D2, layer 2).

Stdlib only -- no third-party imports -- so seeding can depend on this module
without pulling spaCy into its own test surface.
"""

from __future__ import annotations

import re

# Separators that get expanded into hyphen / space / no-separator forms.
# Matches design.md D3's salt-mention separators: ASCII hyphen and the
# middle-dot / bullet characters OCR sometimes produces for it.
_SEPARATORS = ("-", "·", "•")  # -, ·, •

_SEPARATOR_RE = re.compile("[" + "".join(re.escape(sep) for sep in _SEPARATORS) + "]")

_WHITESPACE_RUN_RE = re.compile(r"\s+")

# Structural formula-shape check: an "element-fluoride formula unit" is an
# uppercase letter, an optional lowercase letter, and optional trailing
# digits (e.g. `Li`, `Be`, `F2`, `Th`, `F4`). A label is formula-shaped only
# when it is entirely made up of such units back-to-back, optionally joined
# by the existing separators / whitespace (e.g. `BeF2`, `LiF-BeF2`,
# `LiF BeF2`). Free text (`viscosity`, `molten salts`) never matches this
# shape, so it never triggers OCR-subscript variant generation below.
_FORMULA_LABEL_RE = re.compile(
    r"^(?:[A-Z][a-z]?\d*|[" + "".join(re.escape(sep) for sep in _SEPARATORS) + r"\s])+$"
)

# A subscript digit run: one or more digits immediately preceded by a letter,
# e.g. the `2` in `BeF2` or the `4` in `ThF4`/`UF4`/`ZrF4`. This is the
# substring the corpus OCR sometimes renders as a comma or a period instead
# of a subscript digit.
_SUBSCRIPT_RUN_RE = re.compile(r"(?<=[A-Za-z])\d+")


def _collapse_whitespace(label: str) -> str:
    """Collapse runs of whitespace to a single space and strip ends."""
    return _WHITESPACE_RUN_RE.sub(" ", label).strip()


def _separator_variants(label: str) -> list[str]:
    """Expand each separator occurrence into hyphen/space/empty forms."""
    if not _SEPARATOR_RE.search(label):
        return [label]
    return [
        _collapse_whitespace(_SEPARATOR_RE.sub(replacement, label))
        for replacement in ("-", " ", "")
    ]


def _is_formula_label(label: str) -> bool:
    """True when `label` is structurally formula-shaped (see `_FORMULA_LABEL_RE`)."""
    return bool(_FORMULA_LABEL_RE.fullmatch(label))


def _ocr_subscript_variants(label: str) -> list[str]:
    """OCR-subscript surface variants of a formula-shaped `label`.

    For every subscript-digit run in `label` (a digit run immediately
    following a letter), produce a variant with that run replaced by a
    comma and another with it replaced by a period, e.g. `BeF2` ->
    `BeF,`, `BeF.`; `LiF-BeF2` -> `LiF-BeF,`, `LiF-BeF.` (only the
    component carrying the subscript is transformed; the rest of the label
    is left untouched, including its original separators/spacing, so the
    caller's separator-variant expansion still applies to the result).

    Returns `[]` when `label` carries no subscript digit (e.g. `LiF`).
    """
    ocr_variants = []
    for match in _SUBSCRIPT_RUN_RE.finditer(label):
        start, end = match.span()
        ocr_variants.append(label[:start] + "," + label[end:])
        ocr_variants.append(label[:start] + "." + label[end:])
    return ocr_variants


def generate_variants(label: str) -> list[str]:
    """Deterministic surface variants of `label` for expanded exact matching.

    Pure function (same input -> same output), stdlib only.

    Applies, then dedupes, then returns sorted for determinism:

    - Always includes the original label (whitespace-collapsed).
    - Separator variants: for `-`, `·`, `•`, produces forms with the
      separator replaced by a hyphen, a single space, or removed entirely
      (e.g. `LiF-BeF2` -> `LiF-BeF2`, `LiF BeF2`, `LiFBeF2`).
    - OCR-subscript variants: when `label` is structurally formula-shaped
      (see `_is_formula_label`) and carries a subscript digit, also
      produces forms with that digit replaced by a comma or a period (the
      corpus OCR artifact for a rendered subscript), e.g. `BeF2` ->
      `BeF,`, `BeF.`. These compose with the separator variants above
      (e.g. `LiF-BeF2` also yields `LiF-BeF,`, `LiF BeF,`, `LiFBeF,`, and
      the `.`-substituted equivalents). Non-formula labels (`viscosity`)
      and formula labels with no subscript digit (`LiF`) yield none.
    - Case: every variant above also contributes its `.lower()` form (feeds
      spaCy `attr="LOWER"` patterns).

    Empty or whitespace-only input yields `[]`.
    """
    base = _collapse_whitespace(label)
    if not base:
        return []

    bases = [base]
    if _is_formula_label(base):
        bases.extend(_ocr_subscript_variants(base))

    variants: set[str] = set()
    for candidate in bases:
        for variant in _separator_variants(candidate):
            variants.add(variant)
            variants.add(variant.lower())

    return sorted(variants)
