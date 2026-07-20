"""Trace-artifact tests (chunk 7, task 8.10).

Pins ``write_relations_jsonl``: every proposed relation -- written,
skipped, or rejected -- gets exactly one line in
``config.relations_path(report)``, carrying ``confidence``, ``rationale``,
``disposition``, and (for the non-written dispositions) a ``reason``, per
the relation-extraction spec's "Each relation carries an extraction
confidence and rationale, recorded in a trace artifact" requirement.

Composes ``validate_relation`` (already exercised in
``test_relations_validate.py``/``test_relations_edges_validate.py``)
with ``write_relations_jsonl`` directly, rather than going through
``extract_report``/``extract_relations``, to keep this file's API surface
to the two functions this task is actually about -- see the "API
ambiguities" note in the tester's handoff report re: ``extract_report``'s
unpinned signature.

Written pass-1 against the pinned ``msr_extraction.relations`` API; the
module does not exist yet in this worktree (concurrent coder work), so
this file is expected to error at collection until pass 2 merges it.
"""

from __future__ import annotations

import json
from pathlib import Path

from msr_extraction.config import Config
from msr_extraction.relations import (
    KnownSets,
    RelationRecord,
    SelectedSentence,
    validate_relation,
    write_relations_jsonl,
)
from msr_extraction.units import UnitMapper

REPORT = "ORNL-TM-2316"

SALT = "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"
VISC = "https://w3id.org/msr-kg/ontology#viscosity"
NOVEL_PROPERTY = "https://w3id.org/msr-kg/ontology#solubility"

QUDT_UNITS_PATH = Path(__file__).resolve().parents[2] / "ontology" / "qudt-units.json"

THRESHOLD = 0.5

WRITTEN_RAW = {
    "kind": "measurement",
    "salt": SALT,
    "property": VISC,
    "unit": "cP",
    "form_hint": "DiscretePoint",
    "value": 2.28,
    "temperature": 600,
    "confidence": 0.9,
    "rationale": "A single reported viscosity value -- written case.",
}

SKIPPED_RAW = {
    "kind": "measurement",
    "salt": SALT,
    "property": VISC,
    "unit": "cP",
    "form_hint": "DiscretePoint",
    "value": 2.30,
    "temperature": 610,
    "confidence": 0.1,
    "rationale": "Low-confidence extraction -- skipped case.",
}

REJECTED_RAW = {
    "kind": "measurement",
    "salt": SALT,
    "property": NOVEL_PROPERTY,
    "unit": "cP",
    "form_hint": "DiscretePoint",
    "value": 1.0,
    "temperature": 500,
    "confidence": 0.9,
    "rationale": "Unknown property -- rejected case.",
}


def _known() -> KnownSets:
    return KnownSets(
        molten_salts={SALT},
        physical_properties={VISC},
        salt_roles=set(),
        reactor_concepts=set(),
    )


def _mapper() -> UnitMapper:
    return UnitMapper.from_path(QUDT_UNITS_PATH)


def _sentence() -> SelectedSentence:
    """See test_relations_validate.py's factory for the field-naming
    assumption this makes (flagged for pass-2 reconciliation)."""
    return SelectedSentence(
        report=REPORT,
        seg_index=0,
        text="FLiBe has a reported viscosity of about 2.3 cP near 600 C.",
        char_start=0,
        char_end=58,
        linked_mentions=[],
    )


def _records() -> list[RelationRecord]:
    known = _known()
    mapper = _mapper()
    sentence = _sentence()
    records: list[RelationRecord] = []
    for raw in (WRITTEN_RAW, SKIPPED_RAW, REJECTED_RAW):
        _validated, record = validate_relation(raw, sentence, known, mapper, THRESHOLD)
        records.append(record)
    return records


def test_relations_jsonl_has_exactly_one_line_per_proposed_relation(tmp_path: Path) -> None:
    config = Config(corpus_dir=tmp_path)

    write_relations_jsonl(REPORT, _records(), config)

    lines = [
        line
        for line in config.relations_path(REPORT).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 3


def test_each_line_carries_confidence_rationale_and_disposition(tmp_path: Path) -> None:
    config = Config(corpus_dir=tmp_path)

    write_relations_jsonl(REPORT, _records(), config)

    lines = config.relations_path(REPORT).read_text(encoding="utf-8").splitlines()
    parsed = [json.loads(line) for line in lines if line.strip()]

    for obj in parsed:
        assert "confidence" in obj
        assert "rationale" in obj
        assert "disposition" in obj


def test_dispositions_are_exactly_one_written_one_skipped_one_rejected(tmp_path: Path) -> None:
    config = Config(corpus_dir=tmp_path)

    write_relations_jsonl(REPORT, _records(), config)

    lines = config.relations_path(REPORT).read_text(encoding="utf-8").splitlines()
    dispositions = [json.loads(line)["disposition"] for line in lines if line.strip()]

    assert dispositions.count("written") == 1
    assert dispositions.count("skipped") == 1
    assert dispositions.count("rejected") == 1


def test_non_written_lines_carry_a_reason(tmp_path: Path) -> None:
    config = Config(corpus_dir=tmp_path)

    write_relations_jsonl(REPORT, _records(), config)

    lines = config.relations_path(REPORT).read_text(encoding="utf-8").splitlines()
    parsed = [json.loads(line) for line in lines if line.strip()]

    for obj in parsed:
        if obj["disposition"] != "written":
            assert obj.get("reason")
