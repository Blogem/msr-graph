"""Requirement threshold extraction tests (openspec/changes/ingest-iaea-safety,
spec ``safety-property-linking``, "Requirement thresholds are soft, extracted
only when stated" requirement, task 8.6).

Exercises the same ``relations.validate_relation`` funnel as
``test_relations_safety.py``'s servedByProperty/addressesFunction tests,
with a new ``kind="requirement_threshold"`` payload -- mirroring how
"measurement"/"role"/"reactor" already share one dispatcher function
keyed by ``raw["kind"]``.

ASSUMPTION (pass-1, flagged for reconciliation at merge): a
``requirement_threshold`` kind branch does not exist yet in
``validate_relation`` on this isolated pass-1 branch -- expected to fall
through to the "unknown kind" rejection until the coder's change lands.
Two shape assumptions, flagged again below: (1) the raw payload carries
``requirement``/``threshold_value``/``threshold_comparator``/
``threshold_unit`` fields (mirroring the "role" kind's
``salt``/``role`` pairing convention); (2) ``threshold_unit`` is captured
as the stated surface-form string (e.g. ``"degC"``), NOT resolved through
the QUDT ``UnitMapper``/allowlist the way a property MEASUREMENT's unit
is -- design.md D5 requires only "extracted... when the source states
them", with no allowlist-validation clause, and the vendored
``ontology/qudt-units.json`` currently has no temperature property/unit
entries at all (verified: ``density``/``viscosity``/``surfaceTension``/
``electricalConductivity`` only), so requiring QUDT resolution here would
make this task depend on an unscoped ontology-file change outside this
tester's allowed paths. If the coder's implementation instead maps
``threshold_unit`` through the allowlist, this needs reconciling at merge
-- not silently adjusting the test to match, since D5 does not call for
that gate.
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
        safety_functions=frozenset(),
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
    temperature thresholdUnit on the Requirement."""
    raw = {
        "kind": "requirement_threshold",
        "requirement": REQUIREMENT,
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
    assert validated.threshold_value == 500.0
    assert validated.threshold_comparator == "lt"
    assert validated.threshold_unit  # a non-empty, stated temperature unit


def test_threshold_comparator_is_one_of_the_four_allowed_values() -> None:
    """design.md D5: thresholdComparator is one of lt/lte/gt/gte."""
    raw = {
        "kind": "requirement_threshold",
        "requirement": REQUIREMENT,
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
    written threshold either."""
    raw = {
        "kind": "requirement_threshold",
        "requirement": UNAPPROVED_REQUIREMENT,
        "threshold_value": 500.0,
        "threshold_comparator": "lt",
        "threshold_unit": "degC",
        "confidence": 0.9,
        "rationale": "references a requirement not yet promoted to core",
    }

    validated, record = validate_relation(raw, _sentence(LIQUIDUS_SENTENCE), _known(), None, THRESHOLD)

    assert validated is None
    assert record.disposition == "rejected"


def test_invalid_comparator_string_is_rejected_as_malformed() -> None:
    """An out-of-set comparator (neither lt/lte/gt/gte) is a malformed
    relation, never silently coerced."""
    raw = {
        "kind": "requirement_threshold",
        "requirement": REQUIREMENT,
        "threshold_value": 500.0,
        "threshold_comparator": "eq",
        "threshold_unit": "degC",
        "confidence": 0.9,
        "rationale": "an invalid comparator",
    }

    validated, record = validate_relation(raw, _sentence(LIQUIDUS_SENTENCE), _known(), None, THRESHOLD)

    assert validated is None
    assert record.disposition == "rejected"


def test_missing_threshold_value_is_rejected_as_malformed() -> None:
    raw = {
        "kind": "requirement_threshold",
        "requirement": REQUIREMENT,
        "threshold_comparator": "lt",
        "threshold_unit": "degC",
        "confidence": 0.9,
        "rationale": "no numeric value supplied",
    }

    validated, record = validate_relation(raw, _sentence(LIQUIDUS_SENTENCE), _known(), None, THRESHOLD)

    assert validated is None
    assert record.disposition == "rejected"


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
    """Companion structural check: even if a well-formed relation IS
    proposed for a qualitative sentence (e.g. a plain addressesFunction
    link with no threshold claim), validate_relation never fabricates
    threshold_value/comparator/unit that the raw payload didn't state --
    a "requirement_threshold" kind is a distinct, separately-proposed
    relation, never inferred from another kind's payload."""
    raw = {
        "kind": "requirement_threshold",
        "requirement": REQUIREMENT,
        # no threshold_value/comparator/unit at all -- the qualitative case
        "confidence": 0.9,
        "rationale": "no numeric threshold is stated in this sentence",
    }

    validated, record = validate_relation(raw, _sentence(QUALITATIVE_SENTENCE), _known(), None, THRESHOLD)

    assert validated is None
    assert record.disposition == "rejected"
