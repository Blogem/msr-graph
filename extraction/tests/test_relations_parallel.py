"""Parallel-fan-out determinism tests for ``extract_report`` (chunk 7,
``concurrency`` parameter).

Pins the sibling coder's fan-out contract for
``relations.extract_report(report, config, prompt_prefix, client, known,
unit_mapper, concurrency=1)``:

- ``concurrency=1`` -- sequential, unchanged (already covered by the other
  ``test_relations_*.py`` files).
- ``concurrency>1`` -- per-sentence ``extract_relations`` Flash calls run
  concurrently (e.g. via a ``ThreadPoolExecutor``), but the returned
  ``ReportExtraction`` (``.measurements``, ``.roles``, ``.reactors``,
  ``.records``) and the written ``relations.jsonl`` trace are
  byte-identical to the ``concurrency=1`` result for the same inputs --
  results are collected back in ``seg_index`` order and
  validation/dedup/trace-writing stay on the main thread.

Mirrors ``test_relations_dedup.py``/``test_relations_select.py``'s
``Config(corpus_dir=tmp_path)`` + on-disk ``segments.jsonl``/
``mentions.jsonl`` corpus setup, and ``test_relations_extract.py``'s
stub-``Completer`` shape (``.complete(system, user) -> str``).

Pass-1 note: as merged into this worktree at pass-1 time,
``extract_report`` takes no ``concurrency`` keyword at all, so every test
below is expected to FAIL (most likely with a ``TypeError`` on the unknown
keyword argument) until the sibling coder's fan-out change merges into
``relations.py`` -- do not weaken these assertions to pass early.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from msr_extraction.config import Config
from msr_extraction.relations import KnownSets, extract_report
from msr_extraction.units import UnitMapper

REPORT = "ORNL-TM-2316"

SALT_IRI = "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"
VISC = "https://w3id.org/msr-kg/ontology#viscosity"
DENSITY = "https://w3id.org/msr-kg/ontology#density"
COOLANT = "https://w3id.org/msr-kg/ontology#CoolantSalt"
MSRE = "https://w3id.org/msr-kg/vocab#msre-reactor"

QUDT_UNITS_PATH = Path(__file__).resolve().parents[2] / "ontology" / "qudt-units.json"

# The corpus: six mention-bearing sentences whose stub Flash replies yield a
# mix of dispositions -- written measurements, a written role, a written
# reactor, a rejected (below-threshold) relation, a malformed/raising
# completer call, and a duplicate-locator pair that collapses to one kept
# measurement (exercising dedup running downstream of the parallel fan-out).
_TEXTS = [
    "FLiBe has a viscosity of 2.28 cP near 600 C, per the table.",  # 0: measurement, written, low conf
    "FLiBe's viscosity is again reported as 2.28 cP near 600 C.",  # 1: measurement, written, high conf (dup of 0)
    "FLiBe has a density of 2.19 g/cm3 near 600 C.",  # 2: measurement, written, distinct property
    "FLiBe served as the primary coolant salt in the loop.",  # 3: role, written
    "FLiBe is used in the MSRE reactor circuit.",  # 4: reactor, written
    "FLiBe was mentioned only in passing, no clear fact here.",  # 5: completer raises -> malformed
]

_REJECTED_TEXT_EXTRA = "FLiBe has a barely-asserted viscosity, low confidence."


def _known() -> KnownSets:
    return KnownSets(
        molten_salts={SALT_IRI},
        physical_properties={VISC, DENSITY},
        salt_roles={COOLANT},
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


def _build_corpus(corpus_dir: Path) -> Config:
    """Build the fixed six-sentence corpus under ``corpus_dir``.

    Every text/mention pairing is identical across calls (same
    ``char_start``/``char_end`` offsets, same mentions per segment) so two
    separate corpora built from this helper are exact inputs for a
    determinism comparison.
    """
    config = Config(corpus_dir=corpus_dir)

    segments = []
    mentions = []
    offset = 0
    for i, text in enumerate(_TEXTS):
        segments.append(_segment(i, text, offset))
        offset += len(text) + 1
        mentions.append(_salt_mention(i))
        if i == 4:
            mentions.append(_reactor_mention(i))

    _write_jsonl(config.segments_path(REPORT), segments)
    _write_jsonl(config.mentions_path(REPORT), mentions)
    return config


def _measurement_relation(property_iri: str, unit: str, value: float, confidence: float) -> dict:
    return {
        "kind": "measurement",
        "salt": SALT_IRI,
        "property": property_iri,
        "unit": unit,
        "form_hint": "DiscretePoint",
        "value": value,
        "temperature": 600,
        "confidence": confidence,
        "rationale": "A reported value.",
    }


def _role_relation(confidence: float) -> dict:
    return {
        "kind": "role",
        "salt": SALT_IRI,
        "role": COOLANT,
        "confidence": confidence,
        "rationale": "Explicitly stated as the coolant salt.",
    }


def _reactor_relation(confidence: float) -> dict:
    return {
        "kind": "reactor",
        "salt": SALT_IRI,
        "reactor": MSRE,
        "confidence": confidence,
        "rationale": "The salt is used in the MSRE.",
    }


def _reply_for(text: str) -> str:
    """The canned Flash reply for a given sentence text.

    Keyed on sentence content (not call order), so the stub is safe to call
    concurrently and from any thread without confusing which sentence a
    call belongs to.
    """
    if text == _TEXTS[0]:
        return json.dumps({"relations": [_measurement_relation(VISC, "cP", 2.28, 0.70)]})
    if text == _TEXTS[1]:
        return json.dumps({"relations": [_measurement_relation(VISC, "cP", 2.28, 0.95)]})
    if text == _TEXTS[2]:
        return json.dumps({"relations": [_measurement_relation(DENSITY, "g/cm3", 2.19, 0.99)]})
    if text == _TEXTS[3]:
        return json.dumps({"relations": [_role_relation(0.88)]})
    if text == _TEXTS[4]:
        return json.dumps({"relations": [_reactor_relation(0.92)]})
    raise AssertionError(f"unexpected sentence text passed to stub: {text!r}")


class KeyedThreadSafeCompleter:
    """A stub ``Completer`` safe to call from multiple threads at once.

    Replies are looked up by the *content* of the user prompt (which embeds
    the sentence text), not by call order -- so concurrent, out-of-order
    calls from a ``ThreadPoolExecutor`` can never be confused about which
    sentence a call belongs to. A call whose sentence text is ``_TEXTS[5]``
    (the "raises" sentence) raises, to exercise the never-crashes path.
    Every call is counted under a ``threading.Lock`` for a thread-safe
    call count.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.call_count = 0
        self.calls: list[str] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        with self._lock:
            self.call_count += 1
            self.calls.append(user_prompt)

        if _TEXTS[5] in user_prompt:
            raise RuntimeError("simulated Flash failure for sentence 5")

        for text in _TEXTS[:5]:
            if text in user_prompt:
                return _reply_for(text)

        raise AssertionError(f"stub could not match any known sentence in prompt: {user_prompt!r}")


def _run(corpus_dir: Path, concurrency: int):
    config = _build_corpus(corpus_dir)
    client = KeyedThreadSafeCompleter()
    result = extract_report(
        REPORT,
        config,
        "cached-kg-schema-prefix",
        client,
        _known(),
        _mapper(),
        concurrency=concurrency,
    )
    return config, client, result


def test_concurrency_one_and_eight_produce_equal_report_extractions(tmp_path: Path) -> None:
    seq_dir = tmp_path / "sequential"
    par_dir = tmp_path / "parallel"

    _, seq_client, seq_result = _run(seq_dir, concurrency=1)
    _, par_client, par_result = _run(par_dir, concurrency=8)

    assert seq_result.measurements == par_result.measurements
    assert seq_result.roles == par_result.roles
    assert seq_result.reactors == par_result.reactors
    assert seq_result.records == par_result.records
    assert seq_result.sentences_seen == par_result.sentences_seen
    assert seq_result.malformed_calls == par_result.malformed_calls

    assert seq_client.call_count == 6
    assert par_client.call_count == 6


def test_concurrency_one_and_eight_write_byte_identical_relations_jsonl(tmp_path: Path) -> None:
    seq_dir = tmp_path / "sequential"
    par_dir = tmp_path / "parallel"

    seq_config, _, _ = _run(seq_dir, concurrency=1)
    par_config, _, _ = _run(par_dir, concurrency=8)

    seq_bytes = seq_config.relations_path(REPORT).read_bytes()
    par_bytes = par_config.relations_path(REPORT).read_bytes()

    assert seq_bytes == par_bytes


def test_every_mention_bearing_sentence_gets_exactly_one_complete_call(tmp_path: Path) -> None:
    """Task: assert the stub Completer received one .complete(...) call per
    mention-bearing sentence, using the thread-safe call counter -- under
    both concurrency=1 and concurrency=8."""
    for concurrency in (1, 8):
        corpus_dir = tmp_path / f"corpus-{concurrency}"
        _, client, _ = _run(corpus_dir, concurrency=concurrency)

        assert client.call_count == len(_TEXTS)
        assert len(client.calls) == len(_TEXTS)


def test_measurement_role_and_reactor_are_all_written_under_parallel_fanout(
    tmp_path: Path,
) -> None:
    """Sanity check on the mixed-disposition corpus: the parallel run
    (concurrency=8) actually produces a written measurement (deduped to
    the higher-confidence one), a written role, and a written reactor --
    not just equal-to-sequential by accident of both being empty."""
    _, _, result = _run(tmp_path, concurrency=8)

    assert len(result.measurements) == 2  # viscosity (deduped) + density
    viscosity = [m for m in result.measurements if m.property_iri == VISC]
    assert len(viscosity) == 1
    assert viscosity[0].confidence == 0.95

    assert len(result.roles) == 1
    assert len(result.reactors) == 1


def test_raising_completer_never_crashes_and_only_that_sentence_is_malformed(
    tmp_path: Path,
) -> None:
    """A stub whose .complete raises for one sentence -> that sentence
    contributes ([], False)-equivalent (malformed_calls increments; no
    crash), and the rest still process -- under both concurrency settings."""
    for concurrency in (1, 8):
        corpus_dir = tmp_path / f"raises-{concurrency}"
        _, client, result = _run(corpus_dir, concurrency=concurrency)

        assert result.malformed_calls == 1
        # The other five sentences still contributed records (measurement,
        # role, reactor relations all validated/traced despite the one
        # raising sentence).
        assert len(result.records) >= 5
        assert client.call_count == len(_TEXTS)
