"""Relation-validation tests (chunk 7, tasks 8.1 + 8.8).

Pins ``validate_relation``'s measurement path: Arrhenius/DiscretePoint
equation mapping, unknown-property rejection (deferred to chunk 8),
unit-mapper rejection (unmappable / out-of-allowlist / dimension
mismatch), the bare-concept salt skip (task 8.8 -- a mention resolving to
a vocab *concept* rather than a loaded ``msr:MoltenSalt`` individual must
never be treated as a valid salt referent), the below-threshold skip, and
the malformed-relation reject.

Written pass-1 against the extract-property-relations task-contract's
pinned ``msr_extraction.relations`` API. The module does not exist yet in
this worktree (it is being written concurrently by the coder in a
sibling worktree), so this file is expected to error at collection until
the coder's branch is merged (pass 2) -- see the tester agent's pass-1
contract. Do not stub the module to force a green run.
"""

from __future__ import annotations

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

# A concept IRI that names a salt informally (e.g. the vocab "flibe"
# concept) but is NOT one of the closed, loaded `msr:MoltenSalt`
# individuals -- task 8.8's bare-concept skip.
BARE_CONCEPT_SALT = "https://w3id.org/msr-kg/vocab#flibe"

# A property IRI that is not a seed `msr:PhysicalProperty` -- left for
# chunk 8's novelty triage, never validated/written here.
NOVEL_PROPERTY = "https://w3id.org/msr-kg/ontology#solubility"

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
    """A minimal SelectedSentence with no linked reactor mention.

    NOTE (pass-1 assumption, flagged for pass-2 reconciliation):
    ``SelectedSentence``'s exact field names are not pinned by the task
    contract beyond ``.linked_mentions``. This factory assumes
    ``report``/``seg_index``/``text``/``char_start``/``char_end``/
    ``linked_mentions`` -- the vocabulary already established by
    ``linker.Segment`` (``report``, ``text``, ``char_start``,
    ``char_end``) and ``linker.MentionRecord`` (``seg_index``). If the
    coder's actual dataclass differs, only this one factory needs
    updating.
    """
    return SelectedSentence(
        report="ORNL-TM-2316",
        seg_index=0,
        text="The FLiBe coolant salt exhibits a viscosity described by an Arrhenius fit.",
        char_start=0,
        char_end=75,
        linked_mentions=[],
    )


def test_valid_arrhenius_measurement_is_written() -> None:
    raw = {
        "kind": "measurement",
        "salt": SALT,
        "property": VISC,
        "unit": "cP",
        "form_hint": "Arrhenius",
        "coefficients": [0.084, 4340],
        "confidence": 0.92,
        "rationale": "Table 3 gives the Arrhenius viscosity fit.",
    }

    validated, record = validate_relation(raw, _sentence(), _known(), _mapper(), THRESHOLD)

    assert isinstance(validated, ValidatedMeasurement)
    assert validated.unit_curie == "unit:MilliPA-SEC"
    assert validated.equation.form == "Arrhenius"
    assert validated.equation.coeffs == [0.084, 4340]
    assert record.disposition == "written"


def test_valid_discrete_point_measurement_is_written() -> None:
    raw = {
        "kind": "measurement",
        "salt": SALT,
        "property": VISC,
        "unit": "cP",
        "form_hint": "DiscretePoint",
        "value": 2.28,
        "temperature": 600,
        "confidence": 0.9,
        "rationale": "A single viscosity value reported at 600 C.",
    }

    validated, record = validate_relation(raw, _sentence(), _known(), _mapper(), THRESHOLD)

    assert isinstance(validated, ValidatedMeasurement)
    assert validated.equation.form == "DiscretePoint"
    assert record.disposition == "written"


def test_unknown_property_is_rejected_and_left_for_chunk_8() -> None:
    raw = {
        "kind": "measurement",
        "salt": SALT,
        "property": NOVEL_PROPERTY,
        "unit": "cP",
        "form_hint": "DiscretePoint",
        "value": 1.0,
        "temperature": 500,
        "confidence": 0.9,
        "rationale": "A novel property term outside the seed set.",
    }

    validated, record = validate_relation(raw, _sentence(), _known(), _mapper(), THRESHOLD)

    assert validated is None
    assert record.disposition == "rejected"
    assert "property" in record.reason


def test_out_of_allowlist_or_unmappable_unit_is_rejected() -> None:
    raw = {
        "kind": "measurement",
        "salt": SALT,
        "property": VISC,
        "unit": "furlongs",
        "form_hint": "DiscretePoint",
        "value": 1.0,
        "temperature": 500,
        "confidence": 0.9,
        "rationale": "A bogus, unmappable unit surface form.",
    }

    validated, record = validate_relation(raw, _sentence(), _known(), _mapper(), THRESHOLD)

    assert validated is None
    assert record.disposition == "rejected"
    assert "unit" in record.reason


def test_dimensional_mismatch_unit_is_rejected() -> None:
    # A density unit given for a viscosity property -- dimensionally
    # inconsistent even though "g/cm3" is itself allowlisted.
    raw = {
        "kind": "measurement",
        "salt": SALT,
        "property": VISC,
        "unit": "g/cm³",
        "form_hint": "DiscretePoint",
        "value": 1.0,
        "temperature": 500,
        "confidence": 0.9,
        "rationale": "A density unit mistakenly given for a viscosity value.",
    }

    validated, record = validate_relation(raw, _sentence(), _known(), _mapper(), THRESHOLD)

    assert validated is None
    assert record.disposition == "rejected"
    assert "unit" in record.reason


def test_bare_concept_salt_referent_is_skipped_not_written() -> None:
    """Task 8.8: a mention resolving to a bare vocab *concept* (never a
    loaded `msr:MoltenSalt` individual) must not be treated as a valid
    salt referent -- skipped, and nothing written."""
    raw = {
        "kind": "measurement",
        "salt": BARE_CONCEPT_SALT,
        "property": VISC,
        "unit": "cP",
        "form_hint": "DiscretePoint",
        "value": 1.0,
        "temperature": 500,
        "confidence": 0.9,
        "rationale": "Salt referent is a bare concept, not a composed individual.",
    }

    validated, record = validate_relation(raw, _sentence(), _known(), _mapper(), THRESHOLD)

    assert validated is None
    assert record.disposition == "skipped"
    assert "salt" in record.reason


def test_below_threshold_measurement_is_skipped_not_written() -> None:
    raw = {
        "kind": "measurement",
        "salt": SALT,
        "property": VISC,
        "unit": "cP",
        "form_hint": "DiscretePoint",
        "value": 1.0,
        "temperature": 500,
        "confidence": 0.1,
        "rationale": "Low-confidence extraction.",
    }

    validated, record = validate_relation(raw, _sentence(), _known(), _mapper(), THRESHOLD)

    assert validated is None
    assert record.disposition == "skipped"
    assert "below-threshold" in record.reason


def test_malformed_relation_missing_kind_is_rejected() -> None:
    raw = {
        "salt": SALT,
        "property": VISC,
        "confidence": 0.9,
    }

    validated, record = validate_relation(raw, _sentence(), _known(), _mapper(), THRESHOLD)

    assert validated is None
    assert record.disposition == "rejected"
    assert record.relation_kind == "unknown"
