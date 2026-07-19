"""Pattern-variant generation tests (task 10.2, design.md D2; task 5.1 /
design.md D2 OCR-subscript extension).

Table-driven pytest coverage of `generate_variants`:
specs/entity-ruler-seeding/spec.md's "Pattern-variant generation for expanded
exact matching" scenario (case + hyphen/spacing variants of `LiF-BeF2`),
single-token labels, determinism/dedupe/sort, empty input, and (OCR-robust-
salt-linking change) specs/entity-ruler-seeding/spec.md's "OCR-subscript
surface variants for known formulas": a comma or period standing in for a
subscript digit on a known formula token, derived ONLY from formula-shaped
labels that actually carry a subscript digit.
"""

from __future__ import annotations

import pytest

from msr_extraction.variants import generate_variants

# Cases where every listed variant must be present in the generated output.
CONTAINS_CASES = [
    pytest.param(
        "LiF-BeF2",
        ["LiF-BeF2", "LiF BeF2", "LiFBeF2", "lif-bef2", "lif bef2", "lifbef2"],
        id="hyphen-spacing-case-variants",
    ),
    pytest.param(
        "viscosity",
        ["viscosity", "viscosity".lower()],
        id="single-token-label",
    ),
]


@pytest.mark.parametrize("label, expected_variants", CONTAINS_CASES)
def test_generate_variants_contains(label: str, expected_variants: list[str]) -> None:
    result = generate_variants(label)
    for expected in expected_variants:
        assert expected in result


# OCR-robust-salt-linking (design.md D2): a comma or period standing in for
# a subscript digit on a known catalog formula token, e.g. "BeF2" -> "BeF,"
# / "BeF." Cases where every listed OCR-subscript variant must be present.
OCR_SUBSCRIPT_CONTAINS_CASES = [
    pytest.param(
        "BeF2",
        ["BeF,", "bef,", "BeF.", "bef."],
        id="single-formula-comma-and-period-subscript-variants",
    ),
    pytest.param(
        "LiF-BeF2",
        # The comma-subscript form of the multi-component salt formula, and
        # the pre-existing (non-OCR) clean form, must both be present.
        ["lif-bef,", "lif-bef2"],
        id="multi-component-formula-comma-subscript-variant",
    ),
]


@pytest.mark.parametrize("label, expected_variants", OCR_SUBSCRIPT_CONTAINS_CASES)
def test_generate_variants_ocr_subscript_variants(
    label: str, expected_variants: list[str]
) -> None:
    result = generate_variants(label)
    for expected in expected_variants:
        assert expected in result, f"{expected!r} missing from variants of {label!r}: {result}"


# Labels that must NOT produce any comma/period OCR-subscript variant:
# a non-formula label (nothing to derive a subscript digit from), and a
# formula label with no subscript digit at all (no digit to stand a comma
# or period in for).
NO_OCR_SUBSCRIPT_VARIANT_LABELS = [
    pytest.param("viscosity", id="non-formula-label-no-ocr-variant"),
    pytest.param("LiF", id="formula-without-subscript-digit-no-ocr-variant"),
]


@pytest.mark.parametrize("label", NO_OCR_SUBSCRIPT_VARIANT_LABELS)
def test_generate_variants_no_ocr_subscript_variant_without_subscript_digit(
    label: str,
) -> None:
    result = generate_variants(label)
    assert not any("," in variant or "." in variant for variant in result), (
        f"unexpected comma/period OCR-subscript-style variant among "
        f"{result} for {label!r}"
    )


@pytest.mark.parametrize("label", ["LiF-BeF2", "BeF2"])
def test_generate_variants_is_deterministic(label: str) -> None:
    first = generate_variants(label)
    second = generate_variants(label)
    assert first == second


@pytest.mark.parametrize("label", ["LiF-BeF2", "BeF2"])
def test_generate_variants_is_sorted_and_deduped(label: str) -> None:
    result = generate_variants(label)
    assert result == sorted(result)
    assert len(result) == len(set(result))


@pytest.mark.parametrize(
    "label",
    [
        pytest.param("", id="empty-string"),
        pytest.param("   ", id="whitespace-only"),
    ],
)
def test_generate_variants_empty_input_yields_empty_list(label: str) -> None:
    assert generate_variants(label) == []
