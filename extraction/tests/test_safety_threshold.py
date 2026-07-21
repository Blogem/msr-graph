"""Requirement threshold extraction tests (openspec/changes/ingest-iaea-safety,
spec ``safety-property-linking``, "Requirement thresholds are soft, extracted
only when stated" requirement, task 8.6).

Exercises the same ``relations.validate_relation`` funnel as
``test_relations_safety.py``'s servedByProperty/addressesFunction tests.

RECONCILED (pass-2, merge with the real ``relations.py``): the pass-1
draft below assumed a standalone ``kind="requirement_threshold"`` payload,
mirroring how "measurement"/"role"/"reactor" each get their own kind. The
real ``validate_relation`` has no such branch -- confirmed against
``relations.py``: there is only ONE requirement-carrying kind,
``"addressesFunction"`` (``Requirement -> SafetyFunction``), and
``ValidatedAddressesFunction``/``AddressesFunctionEdge`` carry
``threshold_value``/``threshold_comparator``/``threshold_unit`` directly
as OPTIONAL fields on that same relation (task 4.5, design.md D5) rather
than as a separate relation kind. Every payload below is rewritten to
``kind="addressesFunction"`` with a ``safety_function`` field (closed-set
checked exactly like ``test_relations_safety.py``'s addressesFunction
tests), and every assertion now reads the threshold off the
``ValidatedAddressesFunction`` returned.

A second, genuine reconciliation (not just a naming fix): ``relations.
_to_threshold`` treats an invalid/missing ``threshold_comparator`` or a
missing ``threshold_value`` as "no threshold stated" -- it drops the
threshold triple to ``(None, None, None)`` and lets the addressesFunction
relation validate/write normally (a Requirement addressing a known,
approved SafetyFunction is a well-formed relation on its own; the
threshold is optional metadata on it, never a gate on the relation
itself). It does NOT reject the whole relation as malformed. This
matches the spec text exactly ("extracted... only where the source
states a numeric threshold" -- an unstated/malformed threshold means
"extract nothing", not "reject the edge"). The pass-1 tests asserting
outright rejection for an invalid comparator / missing value / no
threshold fields at all are corrected below to assert "written, with
threshold fields left None" instead -- softening a REJECT assertion to a
WRITTEN one only where the spec itself never called for a reject in the
first place; the two genuine acceptance scenarios ("stated threshold is
captured" / "not-yet-approved requirement is rejected") are unchanged in
substance, only in kind string.

``threshold_unit`` is captured as the stated surface-form string (e.g.
``"degC"``), NOT resolved through the QUDT ``UnitMapper``/allowlist the
way a property MEASUREMENT's unit is -- confirmed against
``ValidatedAddressesFunction``/``_to_threshold``: the unit is taken
verbatim from the raw payload with no unit-mapper call at all, matching
design.md D5's "extracted... when the source states them" with no
allowlist-validation clause.
"""

from __future__ import annotations

import json

from msr_extraction.relations import (
    KnownSets,
    SelectedSentence,
    extract_relations,
    validate_relation,
)

REPORT = "ORNL-TM-2006-12"
SAFETY_FUNCTION = "https://w3id.org/msr-kg/data#sf-heat-removal"
UNKNOWN_SAFETY_FUNCTION = "https://w3id.org/msr-kg/data#sf-not-yet-approved"
REQUIREMENT = "https://w3id.org/msr-kg/data#requirement-coolant-liquidus"
UNAPPROVED_REQUIREMENT = "https://w3id.org/msr-kg/data#requirement-not-yet-approved"

THRESHOLD = 0.5

# Short, attributed paraphrase of ORNL/TM-2006/12's coolant-selection
# preference (design.md D5, spike doc): "liquidus preferably lower than
# 500 C" for candidate coolant salts.
LIQUIDUS_SENTENCE = (
    "For coolant selection, a liquidus preferably lower than 500 C is desired."
)
QUALITATIVE_SENTENCE = (
    "The coolant salt must be chemically compatible with the structural alloy."
)


class StubCompleter:
    """Same shape as the project's other stub Completers: ``.complete(system,
    user) -> str``, never touches the network."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self.response


def _known() -> KnownSets:
    return KnownSets(
        molten_salts=set(),
        physical_properties=set(),
        salt_roles=set(),
        reactor_concepts=set(),
        safety_functions=frozenset({SAFETY_FUNCTION}),
        requirements=frozenset({REQUIREMENT}),
    )


def _sentence(text: str) -> SelectedSentence:
    return SelectedSentence(
        report=REPORT,
        seg_index=0,
        char_start=0,
        char_end=len(text),
        text=text,
        linked_mentions=[],
    )


# --- Stated threshold is captured (8.6 positive case) -----------------------


def test_stated_liquidus_threshold_is_captured_as_lt_500() -> None:
    """Scenario: "Stated threshold is captured" -- the liquidus-preference
    sentence yields thresholdValue 500, thresholdComparator lt, and a
    temperature thresholdUnit on the addressesFunction relation."""
    raw = {
        "kind": "addressesFunction",
        "requirement": REQUIREMENT,
        "safety_function": SAFETY_FUNCTION,
        "threshold_value": 500.0,
        "threshold_comparator": "lt",
        "threshold_unit": "degC",
        "confidence": 0.9,
        "rationale": "liquidus preferably lower than 500 C for coolant selection",
    }

    validated, record = validate_relation(raw, _sentence(LIQUIDUS_SENTENCE), _known(), None, THRESHOLD)

    assert validated is not None
    assert record.disposition == "written"
    assert validated.requirement_iri == REQUIREMENT
    assert validated.safety_function_iri == SAFETY_FUNCTION
    assert validated.threshold_value == 500.0
    assert validated.threshold_comparator == "lt"
    assert validated.threshold_unit  # a non-empty, stated temperature unit


def test_threshold_comparator_is_one_of_the_four_allowed_values() -> None:
    """design.md D5: thresholdComparator is one of lt/lte/gt/gte."""
    raw = {
        "kind": "addressesFunction",
        "requirement": REQUIREMENT,
        "safety_function": SAFETY_FUNCTION,
        "threshold_value": 500.0,
        "threshold_comparator": "lte",
        "threshold_unit": "degC",
        "confidence": 0.9,
        "rationale": "a liquidus at or below 500 C",
    }

    validated, record = validate_relation(raw, _sentence(LIQUIDUS_SENTENCE), _known(), None, THRESHOLD)

    assert validated is not None
    assert record.disposition == "written"
    assert validated.threshold_comparator == "lte"


def test_threshold_relation_targeting_an_unapproved_requirement_is_rejected() -> None:
    """Mirrors the addressesFunction two-phase closed-set contract (D4):
    a Requirement individual not yet approved into core cannot carry a
    written threshold either -- the whole relation is rejected."""
    raw = {
        "kind": "addressesFunction",
        "requirement": UNAPPROVED_REQUIREMENT,
        "safety_function": SAFETY_FUNCTION,
        "threshold_value": 500.0,
        "threshold_comparator": "lt",
        "threshold_unit": "degC",
        "confidence": 0.9,
        "rationale": "references a requirement not yet promoted to core",
    }

    validated, record = validate_relation(raw, _sentence(LIQUIDUS_SENTENCE), _known(), None, THRESHOLD)

    assert validated is None
    assert record.disposition == "rejected"


def test_threshold_relation_targeting_an_unapproved_safety_function_is_rejected() -> None:
    """Same two-phase gate, on the safety_function side of the edge."""
    raw = {
        "kind": "addressesFunction",
        "requirement": REQUIREMENT,
        "safety_function": UNKNOWN_SAFETY_FUNCTION,
        "threshold_value": 500.0,
        "threshold_comparator": "lt",
        "threshold_unit": "degC",
        "confidence": 0.9,
        "rationale": "references a safety function not yet promoted to core",
    }

    validated, record = validate_relation(raw, _sentence(LIQUIDUS_SENTENCE), _known(), None, THRESHOLD)

    assert validated is None
    assert record.disposition == "rejected"


def test_invalid_comparator_string_is_dropped_not_rejected() -> None:
    """An out-of-set comparator (neither lt/lte/gt/gte) is ambiguous, so
    ``_to_threshold`` drops the whole threshold triple to None -- but the
    addressesFunction relation itself (a well-formed Requirement->
    SafetyFunction edge) still validates/writes; the threshold is simply
    not asserted, mirroring "no threshold stated"."""
    raw = {
        "kind": "addressesFunction",
        "requirement": REQUIREMENT,
        "safety_function": SAFETY_FUNCTION,
        "threshold_value": 500.0,
        "threshold_comparator": "eq",
        "threshold_unit": "degC",
        "confidence": 0.9,
        "rationale": "an invalid comparator",
    }

    validated, record = validate_relation(raw, _sentence(LIQUIDUS_SENTENCE), _known(), None, THRESHOLD)

    assert validated is not None
    assert record.disposition == "written"
    assert validated.threshold_value is None
    assert validated.threshold_comparator is None
    assert validated.threshold_unit is None


def test_missing_threshold_value_yields_no_threshold_but_relation_still_written() -> None:
    """A comparator with no numeric value is equally ambiguous -- dropped,
    not rejected; the addressesFunction relation itself still writes."""
    raw = {
        "kind": "addressesFunction",
        "requirement": REQUIREMENT,
        "safety_function": SAFETY_FUNCTION,
        "threshold_comparator": "lt",
        "threshold_unit": "degC",
        "confidence": 0.9,
        "rationale": "no numeric value supplied",
    }

    validated, record = validate_relation(raw, _sentence(LIQUIDUS_SENTENCE), _known(), None, THRESHOLD)

    assert validated is not None
    assert record.disposition == "written"
    assert validated.threshold_value is None
    assert validated.threshold_comparator is None


# --- No threshold stated, none asserted (8.6 negative case) ----------------


def test_qualitative_requirement_yields_no_threshold_relation() -> None:
    """Scenario: "No threshold stated, none asserted" -- a qualitative
    requirement sentence (compatibility, not a numeric limit) is correctly
    met by a Flash reply proposing NO relation at all (mirroring
    test_relations_safety.py's co-mention-no-edge pattern, exercised
    against the already-landed, genre-agnostic ``extract_relations``): the
    stub Completer stands in for a real model correctly declining to
    invent a threshold that the text never states, so nothing reaches
    ``validate_relation`` for this sentence and no threshold properties
    are asserted."""
    stub = StubCompleter(json.dumps({"relations": []}))

    relations, ok = extract_relations(_sentence(QUALITATIVE_SENTENCE), "cached-kg-schema-prefix", stub)

    assert ok is True
    assert relations == []


def test_qualitative_requirement_raw_payload_never_carries_threshold_fields() -> None:
    """Companion structural check: an addressesFunction relation proposed
    for a qualitative sentence (e.g. a plain "requirement addresses
    function" link with no threshold claim) validates/writes normally,
    and ``validate_relation`` never fabricates threshold_value/comparator/
    unit that the raw payload didn't state -- they stay None."""
    raw = {
        "kind": "addressesFunction",
        "requirement": REQUIREMENT,
        "safety_function": SAFETY_FUNCTION,
        # no threshold_value/comparator/unit at all -- the qualitative case
        "confidence": 0.9,
        "rationale": "the coolant-selection requirement addresses heat removal",
    }

    validated, record = validate_relation(raw, _sentence(QUALITATIVE_SENTENCE), _known(), None, THRESHOLD)

    assert validated is not None
    assert record.disposition == "written"
    assert validated.threshold_value is None
    assert validated.threshold_comparator is None
    assert validated.threshold_unit is None
