"""White-box tests for the Python salt formula normalizer (extraction.formula).

These are independent, hand-authored cases distinct from the shared
`testdata/salt-canonicalization.json` drift-guard fixture (owned by chunk 2
and exercised exhaustively by the tester's own suite). This file only checks:
surface-variant unification in `normalize_salt_span`, `slugify` parity with
the Go original on real fixture canonicals, and a small independent set of
direct `canonicalize` point/range cases.
"""

from __future__ import annotations

import pytest

from msr_extraction.formula import Salt, canonicalize, normalize_salt_span, slugify


class TestNormalizeSaltSpanOrderUnify:
    def test_order_variants_unify_to_same_iri(self):
        # The FLiBe MSRE-coolant composition (design.md): 34 mol% BeF2,
        # 66 mol% LiF, matching the loader-minted individual
        # msrd:salt-BeF2-LiF-34.0-66.0. Written "BeF2-LiF" the composition
        # numbers read straight through (BeF2=34, LiF=66); written
        # "LiF-BeF2" the same physical salt reads LiF=66, BeF2=34 -- the
        # normalizer must reorder in lockstep so both land on one IRI.
        a = normalize_salt_span("BeF2-LiF", "34-66")
        b = normalize_salt_span("LiF-BeF2", "66-34")
        assert a == b == "msrd:salt-BeF2-LiF-34.0-66.0"

    def test_subscript_and_dot_separator_variants_unify(self):
        a = normalize_salt_span("LiF·BeF₂", "66-34")
        b = normalize_salt_span("LiF-BeF2", "66-34")
        assert a == b

    def test_bare_formula_without_composition_returns_none(self):
        assert normalize_salt_span("LiF-BeF2", None) is None

    def test_bare_formula_with_mismatched_composition_count_returns_none(self):
        # Three numbers can't line up one-to-one with two components -- no
        # fabricated guess, just None.
        assert normalize_salt_span("LiF-BeF2", "10-20-70") is None

    def test_inline_parenthesized_composition_resolves(self):
        result = normalize_salt_span("LiF-BeF2 (66-34 mol%)")
        assert result == "msrd:salt-BeF2-LiF-34.0-66.0"

    def test_inline_unparenthesized_composition_resolves(self):
        result = normalize_salt_span("LiF-BeF2 66-34 mol%")
        assert result == "msrd:salt-BeF2-LiF-34.0-66.0"

    def test_truly_bare_formula_with_no_inline_composition_returns_none(self):
        # No "mol%" group anywhere in the surface -- must not fabricate one.
        assert normalize_salt_span("LiF-BeF2") is None


class TestSlugifyMatchesGo:
    def test_point_canonical(self):
        assert slugify("BeF2-LiF | 34.0-66.0") == "BeF2-LiF-34.0-66.0"

    def test_range_canonical(self):
        assert slugify("KF-ZrF4 | ZrF4 0.0-33.3") == "KF-ZrF4-ZrF4-0.0-33.3"

    def test_collapses_repeated_hyphens_and_trims_ends(self):
        assert slugify(" a//b  c ") == "a-b-c"


class TestCanonicalizeDirect:
    def test_point_flibe_real_nist_row(self):
        salt = canonicalize("BeF2-LiF", "34.0-66.0", "P1")
        assert salt == Salt(
            canonical="BeF2-LiF | 34.0-66.0",
            iri="msrd:salt-BeF2-LiF-34.0-66.0",
            components=["BeF2", "LiF"],
            is_range=False,
            mole_percent=[34.0, 66.0],
        )

    def test_point_lockstep_reorder(self):
        salt = canonicalize("LiF-BeF2", "34.0-66.0", "P1")
        assert salt.canonical == "BeF2-LiF | 66.0-34.0"
        assert salt.iri == "msrd:salt-BeF2-LiF-66.0-34.0"
        assert salt.components == ["BeF2", "LiF"]
        assert salt.mole_percent == [66.0, 34.0]
        assert salt.is_range is False

    def test_range_isotherm_kf_zrf4(self):
        salt = canonicalize("KF-ZrF4", "0.0-33.3 ZrF4", "I3")
        assert salt == Salt(
            canonical="KF-ZrF4 | ZrF4 0.0-33.3",
            iri="msrd:salt-KF-ZrF4-ZrF4-0.0-33.3",
            components=["KF", "ZrF4"],
            is_range=True,
            vary_component="ZrF4",
            vary_min=0.0,
            vary_max=33.3,
        )

    def test_positional_sum_outside_tolerance_raises(self):
        with pytest.raises(ValueError):
            canonicalize("BeF2-LiF", "10.0-20.0", "P1")

    def test_empty_salt_token_raises(self):
        with pytest.raises(ValueError):
            canonicalize("", "100", "P1")

    def test_range_wrong_component_count_raises(self):
        with pytest.raises(ValueError):
            canonicalize("KF-LiF-NaF", "0.0-33.3 KF", "I1")
