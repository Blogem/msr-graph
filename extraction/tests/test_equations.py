"""Equation-form / coefficient parsing tests (task 8.4, tasks.md 5.1).

Pins ``parse_correlation(...) -> EquationParse | None``: each seed
``msr:EquationForm`` (Arrhenius, DiscretePoint, Linear, Polynomial2,
Polynomial3) maps its extracted coefficients/value correctly, a
coefficient-count/form mismatch returns ``None`` (rejected, no partial
write), and the ``t_min``/``t_max`` temperature-range handling is
both-bounds-or-neither, ordered ``min <= max`` (tasks.md 5.1 / the merged
SHACL ``ValidTemperatureRangeShape``).

Hermetic: pure function, no I/O.
"""

from __future__ import annotations

from msr_extraction.equations import EquationParse, parse_correlation


def test_arrhenius_form_carries_c0_c1_coefficients() -> None:
    result = parse_correlation(form_hint="Arrhenius", coefficients=[0.084, 4340])
    assert isinstance(result, EquationParse)
    assert result.form == "Arrhenius"
    assert result.coeffs == [0.084, 4340]


def test_discrete_point_form_derives_coeffs_and_both_temp_bounds() -> None:
    result = parse_correlation(form_hint="DiscretePoint", value=2.28, temperature=600)
    assert result is not None
    assert result.form == "DiscretePoint"
    assert result.coeffs == [2.28, 600.0]
    assert result.t_min == 600.0
    assert result.t_max == 600.0


def test_linear_form_accepts_exactly_two_coefficients() -> None:
    result = parse_correlation(form_hint="Linear", coefficients=[1, 2])
    assert result is not None
    assert result.form == "Linear"
    assert result.coeffs == [1, 2]


def test_linear_form_rejects_three_coefficients() -> None:
    result = parse_correlation(form_hint="Linear", coefficients=[1, 2, 3])
    assert result is None


def test_polynomial2_form_accepts_exactly_three_coefficients() -> None:
    result = parse_correlation(form_hint="Polynomial2", coefficients=[1, 2, 3])
    assert result is not None
    assert result.form == "Polynomial2"
    assert result.coeffs == [1, 2, 3]


def test_polynomial2_form_rejects_wrong_coefficient_count() -> None:
    assert parse_correlation(form_hint="Polynomial2", coefficients=[1, 2]) is None
    assert parse_correlation(form_hint="Polynomial2", coefficients=[1, 2, 3, 4]) is None


def test_polynomial3_form_accepts_exactly_four_coefficients() -> None:
    result = parse_correlation(form_hint="Polynomial3", coefficients=[1, 2, 3, 4])
    assert result is not None
    assert result.form == "Polynomial3"
    assert result.coeffs == [1, 2, 3, 4]


def test_polynomial3_form_rejects_wrong_coefficient_count() -> None:
    assert parse_correlation(form_hint="Polynomial3", coefficients=[1, 2, 3]) is None
    assert parse_correlation(form_hint="Polynomial3", coefficients=[1, 2, 3, 4, 5]) is None


def test_temp_range_both_bounds_are_ordered_min_le_max() -> None:
    """A form's stated t_min/t_max come out ordered even when supplied
    reversed (a lone-bound author error upstream should not silently
    invert the range)."""
    result = parse_correlation(
        form_hint="Linear", coefficients=[1, 2], t_min=900, t_max=500
    )
    assert result is not None
    assert result.t_min == 500.0
    assert result.t_max == 900.0


def test_temp_range_lone_bound_is_dropped() -> None:
    """A lone stated bound (no matching other bound) is dropped entirely --
    both-or-neither, per tasks.md 5.1 / the SHACL ValidTemperatureRangeShape."""
    result = parse_correlation(form_hint="Linear", coefficients=[1, 2], t_min=500)
    assert result is not None
    assert result.t_min is None
    assert result.t_max is None
