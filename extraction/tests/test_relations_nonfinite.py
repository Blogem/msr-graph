"""Non-finite ``confidence``/coefficient guard tests (chunk 7 review fix,
CRITICAL).

Pins the fix that ``validate_relation`` must coerce a non-finite
``confidence`` (``float("inf")``/``float("nan")``) to ``0.0`` *before*
comparing it against the run's confidence threshold. Without the guard,
``float("inf") < threshold`` is ``False`` (an infinite confidence would
sail past the below-threshold gate) and ``float("nan") < threshold`` is
*also* always ``False`` (NaN compares false against everything) -- either
way a non-finite confidence would bypass the precision gate and could be
written, which the fix must prevent categorically.

Also pins that a non-finite value inside a proposed ``coefficients`` list
is rejected as an equation-parse failure (``_to_float``/``_to_float_list``
must treat a non-finite float as unusable, same as a non-numeric string),
never silently coerced into a written measurement with a NaN/Inf
coefficient.

DeepSeek's JSON output mode can hand back the non-standard ``Infinity``/
``NaN``/``-Infinity`` tokens that Python's ``json.loads`` accepts by
default (unlike strict JSON) -- this is *why* the guard is needed at the
validation boundary rather than trusted to "the model would never do
that." One test below documents that fact directly.

Written against the pinned reason-string constants in
``msr_extraction.relations`` (``REASON_BELOW_THRESHOLD ==
"below-threshold"``, ``REASON_EQUATION_PARSE == "equation-parse"``) and
mirrors ``test_relations_validate.py``'s fixtures (``KnownSets``,
``UnitMapper.from_path``, ``SelectedSentence``) -- see that file for the
``SelectedSentence`` field-naming assumption.

Pass-1 note: this file exercises the *fixed* ``validate_relation``
behavior, applied by a sibling coder concurrently in ``relations.py``/
``measurements.py``/``edges.py``. As merged into this worktree at
pass-1 time, ``validate_relation`` does not yet guard non-finite
confidence/coefficients, so the inf/nan tests below are expected to FAIL
(not error) until that fix merges -- do not weaken them to pass early.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from msr_extraction.relations import (
    KnownSets,
    SelectedSentence,
    ValidatedMeasurement,
    validate_relation,
)
from msr_extraction.units import UnitMapper

SALT = "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"
VISC = "https://w3id.org/msr-kg/ontology#viscosity"
COOLANT = "https://w3id.org/msr-kg/ontology#CoolantSalt"
MSRE = "https://w3id.org/msr-kg/vocab#msre-reactor"

QUDT_UNITS_PATH = Path(__file__).resolve().parents[2] / "ontology" / "qudt-units.json"

THRESHOLD = 0.5


def _known() -> KnownSets:
    return KnownSets(
        molten_salts={SALT},
        physical_properties={VISC},
        salt_roles={COOLANT},
        reactor_concepts={MSRE},
    )


def _mapper() -> UnitMapper:
    return UnitMapper.from_path(QUDT_UNITS_PATH)


def _sentence() -> SelectedSentence:
    """See test_relations_validate.py's factory for the field-naming
    assumption this makes (flagged for pass-2 reconciliation)."""
    return SelectedSentence(
        report="ORNL-TM-2316",
        seg_index=0,
        text="The FLiBe coolant salt exhibits a viscosity described by an Arrhenius fit.",
        char_start=0,
        char_end=75,
        linked_mentions=[],
    )


def _measurement_raw(confidence: object) -> dict:
    return {
        "kind": "measurement",
        "salt": SALT,
        "property": VISC,
        "unit": "cP",
        "form_hint": "DiscretePoint",
        "value": 2.28,
        "temperature": 600,
        "confidence": confidence,
        "rationale": "A single viscosity value reported at 600 C.",
    }


def test_infinite_confidence_is_not_written_but_skipped_below_threshold() -> None:
    """An infinite confidence must never bypass the precision gate: it is
    coerced to 0.0 and skipped as below-threshold, never written."""
    raw = _measurement_raw(float("inf"))

    validated, record = validate_relation(raw, _sentence(), _known(), _mapper(), THRESHOLD)

    assert validated is None
    assert record.disposition == "skipped"
    assert "below-threshold" in record.reason


def test_negative_infinite_confidence_is_also_skipped_below_threshold() -> None:
    raw = _measurement_raw(float("-inf"))

    validated, record = validate_relation(raw, _sentence(), _known(), _mapper(), THRESHOLD)

    assert validated is None
    assert record.disposition == "skipped"
    assert "below-threshold" in record.reason


def test_nan_confidence_is_not_written_but_skipped_below_threshold() -> None:
    """NaN compares false against everything (including the threshold), so
    an un-guarded ``confidence < threshold`` check would never trigger for
    NaN either -- the fix must coerce NaN to 0.0 before comparing."""
    raw = _measurement_raw(float("nan"))

    validated, record = validate_relation(raw, _sentence(), _known(), _mapper(), THRESHOLD)

    assert validated is None
    assert record.disposition == "skipped"
    assert "below-threshold" in record.reason


def test_non_finite_coefficient_rejects_as_equation_parse_failure() -> None:
    """A NaN inside ``coefficients`` must not silently become a written
    measurement carrying a NaN coefficient -- ``_to_float``/
    ``_to_float_list`` must treat it as unusable, same as a non-numeric
    string, so the Arrhenius parse fails and the relation is rejected."""
    raw = {
        "kind": "measurement",
        "salt": SALT,
        "property": VISC,
        "unit": "cP",
        "form_hint": "Arrhenius",
        "coefficients": [0.084, float("nan")],
        "confidence": 0.95,
        "rationale": "Table 3 gives the Arrhenius viscosity fit.",
    }

    validated, record = validate_relation(raw, _sentence(), _known(), _mapper(), THRESHOLD)

    assert validated is None
    assert record.disposition == "rejected"
    assert "equation" in record.reason


def test_infinite_coefficient_rejects_as_equation_parse_failure() -> None:
    raw = {
        "kind": "measurement",
        "salt": SALT,
        "property": VISC,
        "unit": "cP",
        "form_hint": "Arrhenius",
        "coefficients": [0.084, float("inf")],
        "confidence": 0.95,
        "rationale": "Table 3 gives the Arrhenius viscosity fit.",
    }

    validated, record = validate_relation(raw, _sentence(), _known(), _mapper(), THRESHOLD)

    assert validated is None
    assert record.disposition == "rejected"
    assert "equation" in record.reason


def test_json_loads_accepts_the_non_standard_infinity_token() -> None:
    """Documents *why* the guard is load-bearing: Python's ``json.loads``
    (unlike strict JSON) happily parses the non-standard ``Infinity``
    token DeepSeek's JSON-output mode could hand back, yielding a real
    ``float("inf")`` -- there is no parse-time error to catch it at."""
    parsed = json.loads('{"confidence": Infinity}')

    assert parsed["confidence"] == float("inf")
    assert math.isinf(parsed["confidence"])


def test_relation_built_from_a_parsed_infinity_confidence_is_skipped_not_written() -> None:
    parsed = json.loads(
        '{"kind": "measurement", "salt": "%s", "property": "%s", '
        '"unit": "cP", "form_hint": "DiscretePoint", "value": 2.28, '
        '"temperature": 600, "confidence": Infinity, '
        '"rationale": "A single viscosity value reported at 600 C."}' % (SALT, VISC)
    )

    validated, record = validate_relation(parsed, _sentence(), _known(), _mapper(), THRESHOLD)

    assert validated is None
    assert record.disposition == "skipped"
    assert "below-threshold" in record.reason


def test_sanity_normal_finite_confidence_measurement_still_written() -> None:
    """Guard against an over-broad fix that treats all confidences as
    suspect -- an ordinary finite, above-threshold confidence must still
    validate normally."""
    raw = _measurement_raw(0.9)

    validated, record = validate_relation(raw, _sentence(), _known(), _mapper(), THRESHOLD)

    assert isinstance(validated, ValidatedMeasurement)
    assert record.disposition == "written"
