"""Role/reactor edge validation tests (chunk 7, tasks 8.1/8.9).

Pins ``validate_relation``'s role and reactor paths: a role must resolve
against the closed ``msr:SaltRole`` set (``KnownSets.salt_roles``); a
reactor referent is the documented exception to closed-set validation --
it is admitted only when the sentence carries a chunk-6 linked mention to
the same reactor concept IRI (grounding the mint), per the
relation-extraction spec's "A reactor is admitted only when grounded on a
linked mention" scenario.

Written pass-1 against the pinned ``msr_extraction.relations`` API; the
module does not exist yet in this worktree (concurrent coder work), so
this file is expected to error at collection until pass 2 merges it.
"""

from __future__ import annotations

from pathlib import Path

from msr_extraction.relations import (
    KnownSets,
    LinkedMention,
    SelectedSentence,
    ValidatedReactor,
    ValidatedRole,
    validate_relation,
)
from msr_extraction.units import UnitMapper

SALT = "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"
VISC = "https://w3id.org/msr-kg/ontology#viscosity"
COOLANT = "https://w3id.org/msr-kg/ontology#CoolantSalt"
MSRE = "https://w3id.org/msr-kg/vocab#msre-reactor"

# Not one of the closed seed `msr:SaltRole` individuals.
UNKNOWN_ROLE = "https://w3id.org/msr-kg/ontology#UnknownRole"

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


def _sentence(linked_mentions: list[LinkedMention] | None = None) -> SelectedSentence:
    """See the equivalent factory in test_relations_validate.py for the
    field-naming assumption this makes (flagged for pass-2 reconciliation)."""
    return SelectedSentence(
        report="ORNL-TM-2316",
        seg_index=0,
        text="FLiBe served as the primary coolant salt and was used in the MSRE.",
        char_start=0,
        char_end=68,
        linked_mentions=linked_mentions or [],
    )


def test_valid_role_relation_is_written() -> None:
    raw = {
        "kind": "role",
        "salt": SALT,
        "role": COOLANT,
        "confidence": 0.8,
        "rationale": "Explicitly stated as the coolant salt.",
    }

    validated, record = validate_relation(raw, _sentence(), _known(), _mapper(), THRESHOLD)

    assert isinstance(validated, ValidatedRole)
    assert validated.role_iri == COOLANT
    assert record.disposition == "written"


def test_unknown_role_is_rejected() -> None:
    raw = {
        "kind": "role",
        "salt": SALT,
        "role": UNKNOWN_ROLE,
        "confidence": 0.8,
        "rationale": "Role term outside the closed seed set.",
    }

    validated, record = validate_relation(raw, _sentence(), _known(), _mapper(), THRESHOLD)

    assert validated is None
    assert record.disposition == "rejected"
    assert "role" in record.reason


def test_reactor_relation_with_grounded_linked_mention_is_written() -> None:
    sentence = _sentence(
        linked_mentions=[
            LinkedMention(surface_form="MSRE", target_iri=MSRE, target_kind="concept")
        ]
    )
    raw = {
        "kind": "reactor",
        "salt": SALT,
        "reactor": MSRE,
        "confidence": 0.9,
        "rationale": "Stated as used in the MSRE.",
    }

    validated, record = validate_relation(raw, sentence, _known(), _mapper(), THRESHOLD)

    assert isinstance(validated, ValidatedReactor)
    assert validated.reactor_concept_iri == MSRE
    assert validated.reactor_label == "MSRE"
    assert record.disposition == "written"


def test_reactor_relation_without_grounded_linked_mention_is_rejected() -> None:
    """No linked mention to MSRE in this sentence -- the reactor referent
    is not grounded, so nothing is minted and the relation is rejected
    (never validated against a closed set the way salt/property/role
    are, per the relation-extraction spec's documented exception)."""
    sentence = _sentence(linked_mentions=[])
    raw = {
        "kind": "reactor",
        "salt": SALT,
        "reactor": MSRE,
        "confidence": 0.9,
        "rationale": "Stated as used in the MSRE.",
    }

    validated, record = validate_relation(raw, sentence, _known(), _mapper(), THRESHOLD)

    assert validated is None
    assert record.disposition == "rejected"
    assert "reactor" in record.reason
