"""In-run dedup-by-target-locator tests (chunk 7 review fix, MAJOR).

Pins the fix that ``extract_report`` must dedup validated relations
*within a single report run* when two different sentences both validate
to a relation naming the same target locator:

- two measurements for the same ``(report, property_name, salt_iri)``
  key -- e.g. one sentence gives a viscosity value in a table, another
  restates it in prose -- must collapse to exactly one
  ``ValidatedMeasurement`` (the higher-confidence one), not two
  conflicting rows for the same property on the same salt.
- two reactor relations grounding the same ``(report, salt_iri,
  reactor_concept_iri)`` locator similarly collapse to one
  ``ValidatedReactor``.

The dropped duplicate is never silently discarded: its ``RelationRecord``
in ``result.records`` (and so the ``relations.jsonl`` trace) is rewritten
from ``disposition="written"`` to ``disposition="skipped"``,
``reason="duplicate-locator"`` -- so the trace still shows every proposed
relation the model made, and why the lower-confidence one didn't end up
written.

Dedup must not over-collapse: two *distinct* measurements in one report
(different property, same salt) are both kept.

Mirrors ``test_relations_select.py``'s ``Config(corpus_dir=tmp_path)`` +
``segments.jsonl``/``mentions.jsonl`` on-disk corpus setup, and
``test_relations_extract.py``'s stub-``Completer`` shape (extended here to
return a different canned Flash reply per sentence, keyed by call order --
``extract_report`` processes ``select_sentences``'s output in
ascending-``seg_index`` order, which this file's corpus relies on).

Pass-1 note: as merged into this worktree at pass-1 time,
``extract_report`` performs no cross-sentence dedup at all, so every test
below asserting a collapse to one kept relation is expected to FAIL until
the sibling coder's fix (applied concurrently to ``relations.py``) merges
-- do not weaken these assertions to pass early.
"""

from __future__ import annotations

import json
from pathlib import Path

from msr_extraction.config import Config
from msr_extraction.relations import (
    KnownSets,
    ValidatedMeasurement,
    ValidatedReactor,
    extract_report,
)
from msr_extraction.units import UnitMapper

REPORT = "ORNL-TM-2316"

SALT_IRI = "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"
VISC = "https://w3id.org/msr-kg/ontology#viscosity"
DENSITY = "https://w3id.org/msr-kg/ontology#density"
MSRE = "https://w3id.org/msr-kg/vocab#msre-reactor"

QUDT_UNITS_PATH = Path(__file__).resolve().parents[2] / "ontology" / "qudt-units.json"


def _known() -> KnownSets:
    return KnownSets(
        molten_salts={SALT_IRI},
        physical_properties={VISC, DENSITY},
        salt_roles=set(),
        reactor_concepts={MSRE},
    )


def _mapper() -> UnitMapper:
    return UnitMapper.from_path(QUDT_UNITS_PATH)


def _write_jsonl(path: Path, objs: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for obj in objs:
            fh.write(json.dumps(obj))
            fh.write("\n")


def _measurement_relation(property_iri: str, unit: str, confidence: float) -> dict:
    return {
        "kind": "measurement",
        "salt": SALT_IRI,
        "property": property_iri,
        "unit": unit,
        "form_hint": "DiscretePoint",
        "value": 2.28,
        "temperature": 600,
        "confidence": confidence,
        "rationale": "A reported value.",
    }


def _reactor_relation(confidence: float) -> dict:
    return {
        "kind": "reactor",
        "salt": SALT_IRI,
        "reactor": MSRE,
        "confidence": confidence,
        "rationale": "The salt is used in the MSRE.",
    }


class SequencedCompleter:
    """Same ``.complete(system, user) -> str`` shape as
    ``test_relations_extract.py``'s ``StubCompleter``, but returns a
    different canned reply per call, in order -- one entry per sentence,
    matching ``select_sentences``'s ascending-``seg_index`` ordering."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self._responses[len(self.calls) - 1]


def _segment(index: int, text: str, offset: int) -> dict:
    return {
        "report": REPORT,
        "index": index,
        "text": text,
        "char_start": offset,
        "char_end": offset + len(text),
    }


def _salt_mention(seg_index: int) -> dict:
    return {
        "report": REPORT,
        "seg_index": seg_index,
        "char_start": 0,
        "char_end": 5,
        "surface_form": "FLiBe",
        "status": "linked",
        "target_iri": SALT_IRI,
        "target_kind": "salt",
        "layer": 2,
        "score": None,
    }


def _reactor_mention(seg_index: int) -> dict:
    return {
        "report": REPORT,
        "seg_index": seg_index,
        "char_start": 20,
        "char_end": 24,
        "surface_form": "MSRE",
        "status": "linked",
        "target_iri": MSRE,
        "target_kind": "concept",
        "layer": 2,
        "score": None,
    }


def _build_corpus(tmp_path: Path) -> Config:
    config = Config(corpus_dir=tmp_path)

    texts = [
        "FLiBe has a viscosity of 2.28 cP near 600 C, per the table.",  # 0: dup measurement, low conf
        "FLiBe's viscosity is again reported as 2.28 cP near 600 C.",  # 1: dup measurement, high conf
        "FLiBe has a density of 2.28 g/cm3 near 600 C.",  # 2: distinct property
        "FLiBe is used in the MSRE reactor circuit.",  # 3: dup reactor, low conf
        "FLiBe is again described as used in the MSRE reactor.",  # 4: dup reactor, high conf
    ]

    segments = []
    mentions = []
    offset = 0
    for i, text in enumerate(texts):
        segments.append(_segment(i, text, offset))
        offset += len(text) + 1
        if i in (0, 1, 2):
            mentions.append(_salt_mention(i))
        else:
            mentions.append(_salt_mention(i))
            mentions.append(_reactor_mention(i))

    _write_jsonl(config.segments_path(REPORT), segments)
    _write_jsonl(config.mentions_path(REPORT), mentions)
    return config


def _run(tmp_path: Path):
    config = _build_corpus(tmp_path)
    responses = [
        json.dumps({"relations": [_measurement_relation(VISC, "cP", 0.70)]}),
        json.dumps({"relations": [_measurement_relation(VISC, "cP", 0.95)]}),
        json.dumps({"relations": [_measurement_relation(DENSITY, "g/cm3", 0.99)]}),
        json.dumps({"relations": [_reactor_relation(0.60)]}),
        json.dumps({"relations": [_reactor_relation(0.90)]}),
    ]
    client = SequencedCompleter(responses)
    result = extract_report(
        REPORT, config, "cached-kg-schema-prefix", client, _known(), _mapper()
    )
    return result


def test_duplicate_measurement_locator_keeps_only_the_higher_confidence_one(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path)

    viscosity_measurements = [
        m for m in result.measurements if m.property_iri == VISC
    ]
    assert len(viscosity_measurements) == 1
    assert viscosity_measurements[0].confidence == 0.95


def test_duplicate_measurement_locator_dropped_record_is_skipped_duplicate_locator(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path)

    visc_records = [r for r in result.records if r.property_iri == VISC]
    assert len(visc_records) == 2

    written = [r for r in visc_records if r.disposition == "written"]
    skipped = [r for r in visc_records if r.disposition == "skipped"]
    assert len(written) == 1
    assert written[0].confidence == 0.95

    assert len(skipped) == 1
    assert skipped[0].confidence == 0.70
    assert skipped[0].reason == "duplicate-locator"


def test_distinct_property_measurement_in_same_report_is_not_collapsed(
    tmp_path: Path,
) -> None:
    """Dedup must key on (report, property_name, salt_iri) -- a
    *different* property on the same salt is a distinct measurement and
    must survive alongside the deduped viscosity one."""
    result = _run(tmp_path)

    assert len(result.measurements) == 2
    property_iris = {m.property_iri for m in result.measurements}
    assert property_iris == {VISC, DENSITY}

    density_measurements = [m for m in result.measurements if m.property_iri == DENSITY]
    assert len(density_measurements) == 1
    assert density_measurements[0].confidence == 0.99


def test_duplicate_reactor_locator_keeps_only_the_higher_confidence_one(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path)

    assert len(result.reactors) == 1
    assert isinstance(result.reactors[0], ValidatedReactor)
    assert result.reactors[0].confidence == 0.90


def test_duplicate_reactor_locator_dropped_record_is_skipped_duplicate_locator(
    tmp_path: Path,
) -> None:
    result = _run(tmp_path)

    reactor_records = [r for r in result.records if r.relation_kind == "reactor"]
    assert len(reactor_records) == 2

    written = [r for r in reactor_records if r.disposition == "written"]
    skipped = [r for r in reactor_records if r.disposition == "skipped"]
    assert len(written) == 1
    assert written[0].confidence == 0.90

    assert len(skipped) == 1
    assert skipped[0].confidence == 0.60
    assert skipped[0].reason == "duplicate-locator"


def test_relations_jsonl_trace_reflects_the_rewritten_duplicate_disposition(
    tmp_path: Path,
) -> None:
    """The on-disk trace must match ``result.records`` exactly -- the
    duplicate's disposition rewrite is not just an in-memory detail."""
    config = _build_corpus(tmp_path)
    responses = [
        json.dumps({"relations": [_measurement_relation(VISC, "cP", 0.70)]}),
        json.dumps({"relations": [_measurement_relation(VISC, "cP", 0.95)]}),
        json.dumps({"relations": [_measurement_relation(DENSITY, "g/cm3", 0.99)]}),
        json.dumps({"relations": [_reactor_relation(0.60)]}),
        json.dumps({"relations": [_reactor_relation(0.90)]}),
    ]
    client = SequencedCompleter(responses)
    extract_report(REPORT, config, "cached-kg-schema-prefix", client, _known(), _mapper())

    lines = config.relations_path(REPORT).read_text(encoding="utf-8").splitlines()
    parsed = [json.loads(line) for line in lines if line.strip()]

    duplicate_locator_lines = [p for p in parsed if p.get("reason") == "duplicate-locator"]
    assert len(duplicate_locator_lines) == 2
    for line in duplicate_locator_lines:
        assert line["disposition"] == "skipped"
