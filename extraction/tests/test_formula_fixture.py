"""Shared fixture drift-guard tests (task 10.1, design.md D3).

Loads the chunk-2-authored ``testdata/salt-canonicalization.json`` fixture
(the Go/Python canonicalization drift guard) and asserts the Python
``msr_extraction.formula`` normalizer reproduces every case's canonical
string, ordered components, mole-percent/range fields, and loader-minted
salt IRI exactly.

Also pins the bare-vs-composed rule (design.md D3 / specs
salt-formula-normalization): a mention with an explicit composition maps to
the composed salt individual IRI; a bare formula with no composition in
context resolves to ``None`` (the concept/compound family), never a guessed
composed IRI.

This test MUST NOT modify the fixture, and must not hardcode its case
count -- it parametrizes over whatever cases are present in the file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from msr_extraction.formula import canonicalize, normalize_salt_span

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "testdata" / "salt-canonicalization.json"


def _load_cases() -> list[dict]:
    with FIXTURE_PATH.open(encoding="utf-8") as fh:
        payload = json.load(fh)
    return payload["cases"]


CASES = _load_cases()


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_fixture_case_canonicalizes_exactly(case: dict) -> None:
    salt = canonicalize(case["raw_salt"], case["raw_composition"], case["form_code"])

    assert salt.canonical == case["canonical"]
    assert salt.components == case["components"]
    assert salt.iri == case["salt_iri"]
    assert salt.is_range == case["is_range"]

    if case["is_range"]:
        assert salt.vary_component == case["vary_component"]
        assert salt.vary_min == case["vary_min"]
        assert salt.vary_max == case["vary_max"]
    else:
        assert salt.mole_percent == case["mole_percent"]


def test_fixture_has_both_point_and_range_cases() -> None:
    # Sanity check on the fixture itself (not pinned to a count): the
    # drift guard is only meaningful if it actually exercises both shapes.
    is_range_values = {case["is_range"] for case in CASES}
    assert True in is_range_values
    assert False in is_range_values


class TestBareVsComposedRule:
    """design.md D3: composition present -> composed individual IRI;
    bare formula, no composition -> None (concept-level, never guessed)."""

    def test_composed_mention_resolves_to_loaded_individual_surface_form(self) -> None:
        result = normalize_salt_span("LiF-BeF2 (66-34 mol%)", None)
        assert result == "msrd:salt-BeF2-LiF-34.0-66.0"

    def test_composed_mention_resolves_to_loaded_individual_split_form(self) -> None:
        result = normalize_salt_span("LiF-BeF2", "66-34")
        assert result == "msrd:salt-BeF2-LiF-34.0-66.0"

    def test_bare_formula_with_no_composition_resolves_to_none(self) -> None:
        result = normalize_salt_span("LiF-BeF2", None)
        assert result is None
