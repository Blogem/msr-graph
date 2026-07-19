"""OCR-tolerant formula-normalizer tests (task 5.2, design.md D3).

Covers `msr_extraction.formula.normalize_salt_span`'s new keyword-only
`known_compounds: frozenset[str] | None` parameter and the broadened
inline-composition tail (`mole %` / `mol %` / `mol.%` in addition to
`mol%`):

- specs/salt-formula-normalization/spec.md "Parse OCR salt-mention forms
  against the known catalog": a comma/period standing in for a subscript
  digit is only reconstructed against a known catalog compound, and an
  unresolved component leaves the whole span unresolved (never a partial or
  guessed salt).
- specs/salt-formula-normalization/spec.md "mole %/mol % compositions
  accepted".
- specs/salt-formula-normalization/spec.md "Canonicalization rule and
  shared fixture unchanged": `known_compounds=None` is fully backward
  compatible with the pre-existing behavior (this file does not touch
  `testdata/salt-canonicalization.json`; that drift guard lives in, and
  stays owned by, test_formula_fixture.py).

This is a Wave-1 pass-1 (write) suite: the OCR-tolerant behavior is not yet
implemented in this worktree, so most cases here are EXPECTED to fail/error
until the coder's `formula.py` changes land and are merged. Collection must
still succeed.
"""

from __future__ import annotations

import pytest

from msr_extraction.formula import normalize_salt_span

FLIBE_IRI = "msrd:salt-BeF2-LiF-34.0-66.0"

# Comma-subscript OCR forms observed verbatim in the ORNL-TM-2316 corpus
# (design.md Context): "LiF-BeF2" rendered as "LiF-BeF,".
KNOWN_FLIBE_COMPOUNDS = frozenset({"LiF", "BeF2"})


class TestCommaSubscriptResolvesAgainstKnownCatalog:
    """spec.md "Comma-subscript composed mention maps to the loaded
    individual": the OCR form resolves to the SAME IRI as the clean form,
    only when every stripped root is in `known_compounds`."""

    def test_comma_subscript_composed_mention_resolves_to_flibe_iri(self) -> None:
        result = normalize_salt_span(
            "LiF-BeF, (66-34 mole %)", known_compounds=KNOWN_FLIBE_COMPOUNDS
        )
        assert result == FLIBE_IRI

    def test_period_subscript_composed_mention_resolves_to_flibe_iri(self) -> None:
        # design.md D1/D2/D3 treat comma and period as equivalent subscript
        # placeholders ("BeF," / "BeF." both stand in for "BeF2").
        result = normalize_salt_span(
            "LiF-BeF. (66-34 mole %)", known_compounds=KNOWN_FLIBE_COMPOUNDS
        )
        assert result == FLIBE_IRI

    def test_comma_subscript_matches_clean_form_result_exactly(self) -> None:
        clean = normalize_salt_span("LiF-BeF2 (66-34 mole %)", known_compounds=KNOWN_FLIBE_COMPOUNDS)
        ocr = normalize_salt_span("LiF-BeF, (66-34 mole %)", known_compounds=KNOWN_FLIBE_COMPOUNDS)
        assert clean == ocr == FLIBE_IRI


class TestMolePercentTailVariants:
    """spec.md "mole %/mol % compositions accepted": mole %, mol %, and
    mol.% must all canonicalize identically to the pre-existing mol% form."""

    TAIL_SURFACES = {
        "mol-percent-no-space": "LiF-BeF, (66-34 mol%)",
        "mole-percent-spaced": "LiF-BeF, (66-34 mole %)",
        "mol-percent-spaced": "LiF-BeF, (66-34 mol %)",
        "mol-dot-percent": "LiF-BeF, (66-34 mol.%)",
    }

    TAIL_CASES = [
        pytest.param(surface, id=case_id) for case_id, surface in TAIL_SURFACES.items()
    ]

    @pytest.mark.parametrize("surface", TAIL_CASES)
    def test_tail_variant_resolves_to_flibe_iri(self, surface: str) -> None:
        result = normalize_salt_span(surface, known_compounds=KNOWN_FLIBE_COMPOUNDS)
        assert result == FLIBE_IRI

    def test_all_tail_variants_agree(self) -> None:
        results = {
            normalize_salt_span(surface, known_compounds=KNOWN_FLIBE_COMPOUNDS)
            for surface in self.TAIL_SURFACES.values()
        }
        assert results == {FLIBE_IRI}

    def test_unparenthesized_mole_percent_tail_resolves(self) -> None:
        # _extract_inline_composition already accepts an unparenthesized
        # tail for the clean "mol%" form; mole %/mol % must work the same
        # way, not just inside parentheses.
        result = normalize_salt_span(
            "LiF-BeF, 66-34 mole %", known_compounds=KNOWN_FLIBE_COMPOUNDS
        )
        assert result == FLIBE_IRI


class TestUnknownComponentLeavesSpanUnresolved:
    """spec.md "Unresolved component yields no link": a comma/period token
    whose stripped root is NOT in `known_compounds` must not be
    reconstructed, and the whole span (not just that component) resolves to
    None -- never a partial or guessed salt IRI."""

    def test_unknown_component_returns_none(self) -> None:
        # BeF2 is deliberately absent from known_compounds here: the
        # catalog "hasn't loaded" it, so "BeF," must stay unresolved.
        result = normalize_salt_span(
            "LiF-BeF, (66-34 mol %)", known_compounds=frozenset({"LiF"})
        )
        assert result is None

    def test_empty_known_compounds_returns_none(self) -> None:
        result = normalize_salt_span(
            "LiF-BeF, (66-34 mol %)", known_compounds=frozenset()
        )
        assert result is None

    def test_unknown_component_never_yields_a_partial_or_guessed_iri(self) -> None:
        result = normalize_salt_span(
            "LiF-BeF,-ThF, (72-16-12 mol %)", known_compounds=frozenset({"LiF", "BeF2"})
        )
        # ThF4 is not in known_compounds -- the whole ternary span must be
        # unresolved, not a two-component guess.
        assert result is None


class TestKnownCompoundsBackwardCompatibility:
    """spec.md "Canonicalization rule and shared fixture unchanged":
    `known_compounds=None` (the default) must behave exactly as before --
    no OCR reconstruction, plain mol% parsing only."""

    def test_default_known_compounds_is_none_and_matches_prior_behavior(self) -> None:
        with_default = normalize_salt_span("LiF-BeF2 (66-34 mol%)")
        explicit_none = normalize_salt_span("LiF-BeF2 (66-34 mol%)", known_compounds=None)
        assert with_default == explicit_none == FLIBE_IRI

    def test_bare_formula_with_known_compounds_but_no_composition_returns_none(self) -> None:
        # A composition-free mention must still resolve to None (design.md
        # D3 / the bare-vs-composed rule) even when known_compounds is
        # supplied -- OCR reconstruction never fabricates a composition.
        result = normalize_salt_span("LiF-BeF2", known_compounds=KNOWN_FLIBE_COMPOUNDS)
        assert result is None

    def test_comma_subscript_form_without_known_compounds_does_not_resolve(self) -> None:
        # Without a known_compounds set, the OCR comma form is NOT
        # reconstructed (there is no catalog to resolve "BeF," against), so
        # this must not silently resolve to the FLiBe IRI by accident.
        result = normalize_salt_span("LiF-BeF, (66-34 mole %)")
        assert result != FLIBE_IRI
