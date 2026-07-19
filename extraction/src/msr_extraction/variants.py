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


def generate_variants(label: str) -> list[str]:
    """Deterministic surface variants of `label` for expanded exact matching.

    Pure function (same input -> same output), stdlib only.

    Applies, then dedupes, then returns sorted for determinism:

    - Always includes the original label (whitespace-collapsed).
    - Separator variants: for `-`, `·`, `•`, produces forms with the
      separator replaced by a hyphen, a single space, or removed entirely
      (e.g. `LiF-BeF2` -> `LiF-BeF2`, `LiF BeF2`, `LiFBeF2`).
    - Case: every variant above also contributes its `.lower()` form (feeds
      spaCy `attr="LOWER"` patterns).

    Empty or whitespace-only input yields `[]`.
    """
    base = _collapse_whitespace(label)
    if not base:
        return []

    variants: set[str] = set()
    for variant in _separator_variants(base):
        variants.add(variant)
        variants.add(variant.lower())

    return sorted(variants)
