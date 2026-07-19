"""Pattern-variant generation tests (task 10.2, design.md D2).

Table-driven pytest coverage of `generate_variants`:
specs/entity-ruler-seeding/spec.md's "Pattern-variant generation for expanded
exact matching" scenario (case + hyphen/spacing variants of `LiF-BeF2`),
single-token labels, determinism/dedupe/sort, and empty input.
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


def test_generate_variants_is_deterministic() -> None:
    label = "LiF-BeF2"
    first = generate_variants(label)
    second = generate_variants(label)
    assert first == second


def test_generate_variants_is_sorted_and_deduped() -> None:
    result = generate_variants("LiF-BeF2")
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
