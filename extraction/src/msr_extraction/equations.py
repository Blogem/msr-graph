"""Equation-form + coefficient parsing for extracted correlations (chunk 7, D5).

The relation extractor adapts a raw Flash-model correlation into the
normalized numeric shape this module accepts (an equation-form tag plus
either ordered coefficients, or a single value+temperature point). This
module is deliberately pure and Flash-schema-independent: it has no
dependency on any other new chunk-7 module, so it maps that normalized shape
onto one of the seed ontology's `msr:EquationForm` individuals (`msr.ttl`)
plus ordered coefficients `c0..c4`, per design.md D5 and the
`text-measurement-writing` spec's "Map the extracted correlation to an
EquationForm and coefficients" requirement.

Coefficients live **only** in SQLite; the graph carries just the equation
form local name this module returns. The coefficient count MUST match the
mapped form's arity -- a mismatch rejects the relation (returns ``None``)
rather than raising, so the caller can record the rejection and move on.
"""

from __future__ import annotations

from dataclasses import dataclass

# Arity (number of coefficients c0..) per supported msr:EquationForm local
# name. DiscretePoint is handled separately (derived from value+temperature,
# not from a `coefficients` list) but is included here for documentation.
_ARITY = {
    "Linear": 2,
    "Polynomial2": 3,
    "Polynomial3": 4,
    "Arrhenius": 2,
    "DiscretePoint": 2,
}

# Case-insensitive synonym map to the canonical msr:EquationForm local name.
_FORM_SYNONYMS = {
    "linear": "Linear",
    "polynomial2": "Polynomial2",
    "poly2": "Polynomial2",
    "polynomial3": "Polynomial3",
    "poly3": "Polynomial3",
    "arrhenius": "Arrhenius",
    "discretepoint": "DiscretePoint",
    "discrete": "DiscretePoint",
    "point": "DiscretePoint",
}


@dataclass(frozen=True)
class EquationParse:
    form: str  # msr:EquationForm LOCAL NAME: "Linear"|"Polynomial2"|"Polynomial3"|"Arrhenius"|"DiscretePoint"
    coeffs: list[float]  # ordered c0.. ; length == the form's arity
    t_min: float | None
    t_max: float | None


def _normalize_form_hint(form_hint: str | None) -> str | None:
    """Resolve a raw form hint to a canonical msr:EquationForm local name."""
    if form_hint is None:
        return None
    return _FORM_SYNONYMS.get(form_hint.strip().lower())


def _resolve_temp_range(
    t_min: float | None, t_max: float | None
) -> tuple[float | None, float | None]:
    """Apply the both-or-neither, ordered validity-range rule (D5).

    Both bounds present -> ordered (min, max). Only one present -> both
    dropped (a lone bound would fail the merged SHACL
    ValidTemperatureRangeShape). Neither present -> both None.
    """
    if t_min is not None and t_max is not None:
        lo, hi = float(t_min), float(t_max)
        return (lo, hi) if lo <= hi else (hi, lo)
    return None, None


def parse_correlation(
    *,
    form_hint: str | None,
    coefficients: list[float] | None = None,
    value: float | None = None,
    temperature: float | None = None,
    t_min: float | None = None,
    t_max: float | None = None,
) -> EquationParse | None:
    """Map a normalized extracted correlation to an EquationParse, or None.

    Never raises on bad input -- an unrecognized form, a missing
    value/temperature for DiscretePoint, or a coefficient-count/form
    mismatch all return None so the caller can record a rejection.
    """
    form = _normalize_form_hint(form_hint)
    if form is None:
        return None

    if form == "DiscretePoint":
        if value is None or temperature is None:
            return None
        temp = float(temperature)
        return EquationParse(
            form=form,
            coeffs=[float(value), temp],
            t_min=temp,
            t_max=temp,
        )

    if coefficients is None or len(coefficients) != _ARITY[form]:
        return None

    lo, hi = _resolve_temp_range(t_min, t_max)
    return EquationParse(
        form=form,
        coeffs=[float(c) for c in coefficients],
        t_min=lo,
        t_max=hi,
    )
