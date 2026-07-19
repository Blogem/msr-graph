"""Normalizer tests (task 9.2, design.md D4).

Table-driven pytest coverage of every fixture-pinned normalizer case listed
in tasks.md 9.2 and specs/corpus-normalization/spec.md:

- line-break de-hyphenation (join lowercase-lowercase; keep hyphen for a
  capitalized/numeric neighbor)
- the ``THERMAL-STRE SS`` intra-word-split rejoin
- subscript mapping (``BeF₂`` -> ``BeF2``)
- superscript in-place mapping, both an exponent (``cm⁻³`` ->
  ``cm-3``) and an isotope mass number (``²³⁵U`` -> ``235U``,
  never caret-wrapped)
- an OCR-confusion (ligature) substitution
- an equation-survives-intact case
"""

from __future__ import annotations

import pytest

from msr_extraction.normalizer import normalize_text

# Cases where the normalizer's output is pinned exactly.
EXACT_CASES = [
    pytest.param("prop-\nerties", "properties", id="dehyphenate-join-lowercase"),
    pytest.param("BeF₂", "BeF2", id="subscript-mapping"),
    pytest.param("cm⁻³", "cm-3", id="superscript-exponent-in-place"),
    pytest.param("ﬁle", "file", id="ocr-confusion-ligature-fi"),
    pytest.param(
        "η = 0.084·exp(4340/T)",
        "η = 0.084·exp(4340/T)",
        id="equation-survives-intact",
    ),
]


@pytest.mark.parametrize("raw, expected", EXACT_CASES)
def test_normalize_text_exact(raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


# Cases where surrounding whitespace handling is not pinned, only that the
# expected substring appears (unambiguously) in the output.
CONTAINS_CASES = [
    pytest.param("LiF-\nBeF2", "LiF-BeF2", id="keep-hyphen-compound-neighbor"),
    pytest.param("THERMAL-STRE SS", "THERMAL-STRESS", id="intra-word-split-rejoin"),
]


@pytest.mark.parametrize("raw, expected_substring", CONTAINS_CASES)
def test_normalize_text_contains(raw: str, expected_substring: str) -> None:
    assert expected_substring in normalize_text(raw)


def test_normalize_text_isotope_superscript_is_not_caret_wrapped() -> None:
    # ²³⁵U == superscript "235" + "U" (an isotope mass number).
    result = normalize_text("²³⁵U")
    assert "235U" in result
    assert "^" not in result


def test_normalize_text_keeps_hyphen_not_joined() -> None:
    # The compound-hyphen case must NOT be merged into "LiFBeF2".
    result = normalize_text("LiF-\nBeF2")
    assert "LiFBeF2" not in result
