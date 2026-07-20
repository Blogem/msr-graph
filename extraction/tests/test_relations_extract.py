"""Flash relation-extraction call tests (chunk 7, tasks 8.1 malformed + 8.9 multiple).

Pins ``extract_relations``'s contract against a stub ``Completer`` (same
shape as ``disambiguation.Completer``/``StubCompleter`` in
``test_disambiguation.py``): a well-formed ``{"relations": [...]}``
response yields the parsed list with ``ok=True``; an empty list is a
legitimate "nothing to extract" outcome; malformed/non-dict/missing-key
JSON, and a completer that raises, all drop to ``([], False)`` without
raising -- the extractor must never propagate a bad Flash response as an
exception, mirroring ``disambiguate``'s malformed-JSON-is-treated-as-novel
posture.

Also exercises task 8.9 (multiple relations per sentence): a sentence
asserting both a role and a reactor/measurement fact must not lose either
one -- each is validated independently.

Written pass-1 against the pinned ``msr_extraction.relations`` API; the
module does not exist yet in this worktree (concurrent coder work), so
this file is expected to error at collection until pass 2 merges it.
"""

from __future__ import annotations

import json
from pathlib import Path

from msr_extraction.relations import (
    KnownSets,
    SelectedSentence,
    ValidatedMeasurement,
    ValidatedRole,
    extract_relations,
    validate_relation,
)
from msr_extraction.units import UnitMapper

SALT = "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"
VISC = "https://w3id.org/msr-kg/ontology#viscosity"
COOLANT = "https://w3id.org/msr-kg/ontology#CoolantSalt"
MSRE = "https://w3id.org/msr-kg/vocab#msre-reactor"

QUDT_UNITS_PATH = Path(__file__).resolve().parents[2] / "ontology" / "qudt-units.json"

THRESHOLD = 0.5

MEASUREMENT = {
    "kind": "measurement",
    "salt": SALT,
    "property": VISC,
    "unit": "cP",
    "form_hint": "DiscretePoint",
    "value": 2.28,
    "temperature": 600,
    "confidence": 0.9,
    "rationale": "A single reported viscosity value.",
}

ROLE = {
    "kind": "role",
    "salt": SALT,
    "role": COOLANT,
    "confidence": 0.85,
    "rationale": "Explicitly stated as the coolant salt.",
}


class StubCompleter:
    """Same shape as ``disambiguation``'s stub: ``.complete(system, user) -> str``."""

    def __init__(self, response: str | None = None, raise_exc: Exception | None = None) -> None:
        self.response = response
        self.raise_exc = raise_exc
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        if self.raise_exc is not None:
            raise self.raise_exc
        assert self.response is not None
        return self.response


def _sentence() -> SelectedSentence:
    """See test_relations_validate.py's factory for the field-naming
    assumption this makes (flagged for pass-2 reconciliation)."""
    return SelectedSentence(
        report="ORNL-TM-2316",
        seg_index=0,
        text="FLiBe served as the primary coolant salt with a reported viscosity of 2.28 cP at 600 C.",
        char_start=0,
        char_end=88,
        linked_mentions=[],
    )


def _known() -> KnownSets:
    return KnownSets(
        molten_salts={SALT},
        physical_properties={VISC},
        salt_roles={COOLANT},
        reactor_concepts={MSRE},
    )


def _mapper() -> UnitMapper:
    return UnitMapper.from_path(QUDT_UNITS_PATH)


def test_two_relations_in_one_sentence_are_both_extracted_and_validated() -> None:
    """Task 8.9: a sentence packing two facts (a measurement and a role)
    loses neither -- extract_relations returns both, and each validates
    independently to a written payload of the expected kind."""
    stub = StubCompleter(json.dumps({"relations": [MEASUREMENT, ROLE]}))

    relations, ok = extract_relations(_sentence(), "cached-kg-schema-prefix", stub)

    assert ok is True
    assert len(relations) == 2

    known = _known()
    mapper = _mapper()
    sentence = _sentence()
    validated_kinds = []
    for raw in relations:
        validated, record = validate_relation(raw, sentence, known, mapper, THRESHOLD)
        assert record.disposition == "written"
        validated_kinds.append(type(validated))

    assert ValidatedMeasurement in validated_kinds
    assert ValidatedRole in validated_kinds


def test_empty_relations_list_is_ok_and_nothing_to_validate() -> None:
    stub = StubCompleter(json.dumps({"relations": []}))

    relations, ok = extract_relations(_sentence(), "cached-kg-schema-prefix", stub)

    assert relations == []
    assert ok is True


def test_malformed_json_drops_to_empty_list_not_ok() -> None:
    stub = StubCompleter("{not json at all")

    relations, ok = extract_relations(_sentence(), "cached-kg-schema-prefix", stub)

    assert relations == []
    assert ok is False


def test_json_missing_relations_key_drops_to_empty_list_not_ok() -> None:
    stub = StubCompleter(json.dumps({"unexpected": "shape"}))

    relations, ok = extract_relations(_sentence(), "cached-kg-schema-prefix", stub)

    assert relations == []
    assert ok is False


def test_non_dict_json_drops_to_empty_list_not_ok() -> None:
    stub = StubCompleter(json.dumps(["relations"]))

    relations, ok = extract_relations(_sentence(), "cached-kg-schema-prefix", stub)

    assert relations == []
    assert ok is False


def test_completer_raising_drops_to_empty_list_not_ok_no_propagation() -> None:
    stub = StubCompleter(raise_exc=RuntimeError("network error"))

    relations, ok = extract_relations(_sentence(), "cached-kg-schema-prefix", stub)

    assert relations == []
    assert ok is False
