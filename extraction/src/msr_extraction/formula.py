"""Python chemical-formula normalizer for salt mentions (chunk 6, D3).

This is the deliberately-duplicated Python half of the salt canonicalization
rule whose Go original lives in ``internal/nist/canonical.go`` +
``internal/nist/iri.go``. It is pure string/structure work, so duplicating it
here (rather than shelling out to Go or adding a cross-language RPC) is the
cheaper, more robust choice per design.md D3. The shared
``testdata/salt-canonicalization.json`` fixture (owned by chunk 2, consumed
read-only here) is the drift guard both suites must pass.

Two responsibilities:

1. ``canonicalize`` mirrors Go's ``Canonicalize`` byte-for-byte: given a raw
   salt token, a composition string, and an equation-form code, produce the
   canonical form (components byte-sorted, composition values reordered in
   lockstep, one-decimal formatting) and mint the loader's
   ``msrd:salt-{formula}-{composition}`` CURIE via ``slugify``.
2. ``normalize_salt_span`` resolves a free-text salt mention (with its
   surface order/subscript/separator/spacing variants) plus an optional
   composition string to that same composed salt IRI -- or to ``None`` when
   no composition is present, so a bare formula never fabricates a specific
   composed individual (design.md D3 "Composition without an explicit mole %").
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MSRD_PREFIX = "msrd:"

# positional_sum_tolerance mirrors Go's `positionalSumTolerance` in
# internal/nist/canonical.go: the +/-2.0 mol% a positional composition's
# values may deviate from summing to 100.
positional_sum_tolerance = 2.0

# Isotherm/range equation-form codes, mirroring Go's `isIsothermCode` in
# internal/nist/equationform.go. Everything outside this set is a positional
# single-composition salt.
_ISOTHERM_CODES = frozenset({"I1", "I2", "I3", "I4"})

# slugify's substitution set, mirroring Go's internal/nist/iri.go slugify.
_SLUGIFY_CHARS = frozenset(" /#|=@")

# --- Surface-variant cleanup tables for normalize_salt_span -----------------

_SUBSCRIPT_DIGIT_MAP = str.maketrans(
    {
        "₀": "0",
        "₁": "1",
        "₂": "2",
        "₃": "3",
        "₄": "4",
        "₅": "5",
        "₆": "6",
        "₇": "7",
        "₈": "8",
        "₉": "9",
    }
)

_DOT_SEPARATOR_MAP = str.maketrans({"·": "-", "•": "-", "⋅": "-"})

_WHITESPACE_RUN_RE = re.compile(r"\s+")
_HYPHEN_SPACING_RE = re.compile(r"\s*-\s*")
_LEADING_COEFFICIENT_RE = re.compile(r"^\d+(?=[A-Za-z])")
# Unsigned only: composition percentages are never negative, and a signed
# pattern would wrongly swallow the "-" that separates values (e.g. "34-66"
# would parse as ["34", "-66"] instead of ["34", "66"]).
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

# A trailing inline composition group at the end of a mention: an optional
# '(', 2+ hyphen-separated numbers, "mol%" (case-insensitive, optional
# internal spacing), and an optional ')'. Matches both "(66-34 mol%)" and
# the unparenthesized "66-34 mol%".
_INLINE_COMPOSITION_RE = re.compile(
    r"\(?\s*(\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)+)\s*mol\s*%\s*\)?\s*$",
    re.IGNORECASE,
)


def slugify(s: str) -> str:
    """Identical to Go internal/nist/iri.go slugify.

    Replace each of ' ', '/', '#', '|', '=', '@' with '-', collapse repeated
    '-', trim leading/trailing '-'.
    """
    chars = ["-" if ch in _SLUGIFY_CHARS else ch for ch in s]
    slug = "".join(chars)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


@dataclass(frozen=True)
class Salt:
    """A canonical salt (point OR range composition).

    Mirrors Go's ``Salt`` in internal/nist/canonical.go, trimmed to the
    fields the Python linker needs (no ``Constituents``/``Label``).
    """

    canonical: str  # "BeF2-LiF | 34.0-66.0" (point) or "KF-ZrF4 | ZrF4 0.0-33.3" (range)
    iri: str  # "msrd:salt-" + slugify(canonical)
    components: list[str]  # byte-sorted formula tokens, e.g. ["BeF2", "LiF"]
    is_range: bool
    mole_percent: list[float] | None = None  # point only, sorted-component order
    vary_component: str | None = None  # range only
    vary_min: float | None = None  # range only
    vary_max: float | None = None  # range only


def _sorted_order(components: list[str]) -> list[int]:
    """The permutation of indices that puts components in byte-wise
    ascending order (plain Python string comparison mirrors Go's `<` on
    strings for the ASCII formula tokens used here)."""
    return sorted(range(len(components)), key=lambda i: components[i])


def canonicalize(salt_token: str, composition: str, form_code: str) -> Salt:
    """Mirror Go's Canonicalize.

    Form codes I1..I4 -> range isotherm; everything else -> positional
    point. Raises ValueError on malformed input (mirroring Go's errors).
    """
    components = salt_token.strip().split("-")
    if not components or components[0] == "":
        raise ValueError(f"nist: empty salt token {salt_token!r}")
    for c in components:
        if c.strip() == "":
            raise ValueError(f"nist: salt token {salt_token!r} has an empty component")

    if form_code in _ISOTHERM_CODES:
        return _canonicalize_range(components, composition)
    return _canonicalize_positional(components, composition)


def _canonicalize_positional(components: list[str], composition: str) -> Salt:
    raw_values = composition.strip().split("-")
    if len(raw_values) != len(components):
        raise ValueError(
            f"nist: composition {composition!r} has {len(raw_values)} value(s), "
            f"expected {len(components)} for salt {'-'.join(components)!r}"
        )

    values: list[float] = []
    total = 0.0
    for rv in raw_values:
        try:
            v = float(rv.strip())
        except ValueError as exc:
            raise ValueError(f"nist: invalid composition value {rv!r} in {composition!r}: {exc}") from exc
        values.append(v)
        total += v
    if abs(total - 100.0) > positional_sum_tolerance:
        raise ValueError(
            f"nist: composition {composition!r} sums to {total:.4g}, "
            f"outside +/-{positional_sum_tolerance:.1f} mol% of 100"
        )

    order = _sorted_order(components)
    sorted_components = [components[i] for i in order]
    sorted_values = [values[i] for i in order]

    formatted_values = [f"{v:.1f}" for v in sorted_values]

    formula = "-".join(sorted_components)
    composition_str = "-".join(formatted_values)
    canonical = f"{formula} | {composition_str}"

    salt_iri = MSRD_PREFIX + "salt-" + slugify(canonical)

    # Recompute from the formatted (one-decimal) values so mole_percent is
    # consistent with the canonical string, mirroring Go's re-parse of
    # formattedValues rather than reusing the unrounded input.
    mole_percent = [float(fv) for fv in formatted_values]

    return Salt(
        canonical=canonical,
        iri=salt_iri,
        components=sorted_components,
        is_range=False,
        mole_percent=mole_percent,
    )


def _canonicalize_range(components: list[str], composition: str) -> Salt:
    if len(components) != 2:
        raise ValueError(
            f"nist: isotherm range salts must have exactly 2 components, "
            f"got {len(components)} ({components})"
        )

    fields = composition.strip().split()
    if len(fields) != 2:
        raise ValueError(f'nist: isotherm composition {composition!r} must be "lo-hi COMPONENT"')
    range_part, vary_component = fields[0], fields[1]

    range_values = range_part.split("-")
    if len(range_values) != 2:
        raise ValueError(f'nist: isotherm composition range {range_part!r} must be "lo-hi"')
    try:
        lo = float(range_values[0].strip())
    except ValueError as exc:
        raise ValueError(f"nist: invalid isotherm range low value {range_values[0]!r}: {exc}") from exc
    try:
        hi = float(range_values[1].strip())
    except ValueError as exc:
        raise ValueError(f"nist: invalid isotherm range high value {range_values[1]!r}: {exc}") from exc

    if vary_component not in components:
        raise ValueError(
            f"nist: varying component {vary_component!r} not found among salt components {components}"
        )

    order = _sorted_order(components)
    sorted_components = [components[i] for i in order]

    formula = "-".join(sorted_components)
    lo_str = f"{lo:.1f}"
    hi_str = f"{hi:.1f}"
    canonical = f"{formula} | {vary_component} {lo_str}-{hi_str}"

    salt_iri = MSRD_PREFIX + "salt-" + slugify(canonical)

    return Salt(
        canonical=canonical,
        iri=salt_iri,
        components=sorted_components,
        is_range=True,
        vary_component=vary_component,
        vary_min=float(lo_str),
        vary_max=float(hi_str),
    )


def _clean_surface(surface: str) -> str:
    """Map subscript digits and dot-like separators to ASCII, collapse
    whitespace, and normalize hyphen spacing."""
    s = surface.translate(_SUBSCRIPT_DIGIT_MAP)
    s = s.translate(_DOT_SEPARATOR_MAP)
    s = _WHITESPACE_RUN_RE.sub(" ", s).strip()
    s = _HYPHEN_SPACING_RE.sub("-", s)
    return s


def _strip_leading_coefficient(token: str) -> str:
    """Strip a leading integer stoichiometric coefficient, e.g. '2LiF' -> 'LiF'."""
    return _LEADING_COEFFICIENT_RE.sub("", token)


def _extract_inline_composition(surface: str) -> tuple[str, str | None]:
    """Split a trailing inline composition group off the end of a mention.

    Recognizes both the parenthesized ``(a-b mol%)`` / ``(a-b-c mol%)`` form
    and the unparenthesized ``a-b mol%`` form. Returns
    ``(formula_part, "a-b[-c...]")`` when found, or ``(surface, None)`` when
    no inline composition group is present -- leaving `surface` untouched so
    a truly bare formula still falls through to None.
    """
    match = _INLINE_COMPOSITION_RE.search(surface)
    if not match:
        return surface, None
    formula_part = surface[: match.start()].strip()
    return formula_part, match.group(1)


def normalize_salt_span(surface: str, composition_text: str | None = None) -> str | None:
    """Resolve a text salt mention to the composed salt IRI, or None.

    Cleans surface-form variants (subscript digits, dot/bullet separators,
    spacing, leading stoichiometric coefficients), splits into formula
    components, and -- only when a composition is available and its parsed
    numbers line up one-to-one with the components -- canonicalizes as a
    point salt (form_code='P1') and returns its `.iri`. The composition may
    come from the explicit `composition_text` argument, or -- when that is
    None -- from an inline group embedded in `surface` itself, e.g.
    "LiF-BeF2 (66-34 mol%)" or "LiF-BeF2 66-34 mol%" (design.md D3 /
    salt-formula-normalization spec). With no composition anywhere, returns
    None: a bare formula must not fabricate a composed IRI (the linker
    resolves it to a concept via the exact-match layer instead).
    """
    working_surface = surface
    if composition_text is None:
        working_surface, composition_text = _extract_inline_composition(surface)

    cleaned = _clean_surface(working_surface)
    if not cleaned:
        return None

    raw_components = [tok for tok in cleaned.split("-") if tok]
    components = [_strip_leading_coefficient(tok) for tok in raw_components]
    components = [c for c in components if c]
    if not components:
        return None

    if composition_text is None:
        return None

    values = _NUMBER_RE.findall(composition_text)
    if len(values) != len(components):
        return None

    salt_token = "-".join(components)
    composition = "-".join(values)
    try:
        salt = canonicalize(salt_token, composition, "P1")
    except ValueError:
        return None
    return salt.iri
