"""Labelled-sample precision harness (task 10.8, design.md D9, specs/entity-linking).

A committed gold fixture (``fixtures/ornl_tm_2316_gold.json``) labels >= 50
representative ORNL-TM-2316 mentions: each entry is a
``{"sentence", "surface", "expected_target_iri"}`` triple, where
``expected_target_iri`` is either a full known-entity IRI (the pipeline
*should* link this surface to this target) or ``null`` (a no-link case: the
pipeline must *not* emit a linked record for this surface in this sentence).

For each gold mention this harness wraps its ``sentence`` as its own
single-sentence :class:`~msr_extraction.linker.Segment` and calls
:func:`~msr_extraction.linker.link_segment` with a matcher seeded from a
*fixture-scoped* known-entity set covering every non-null
``expected_target_iri`` in the gold data (real vocab prefLabels/altLabels
from ``ontology/vocab.ttl`` and the loaded FLiBe salt individual's
``rdfs:label``, per design.md's seeding contract) -- never the live graph,
so this suite never needs GraphDB. The disambiguation layer is stubbed out
entirely (``disambiguator=None``) for determinism (design.md D9: "the
harness MUST run with a stubbed disambiguation model for determinism").

Precision = correct links / total links emitted, gated at >= 0.90
(specs/entity-linking/spec.md "Linking precision is gated at >= 0.90").
Recall = correctly-linked gold mentions / gold mentions with a non-null
target, computed and printed but never gated (same spec, "Recall reported,
not gated").

Correctness is scored **per gold mention**, not by a single global
surface-form lookup: each mention's sentence is linked independently, and a
mention's own linked record(s) are compared against *that* mention's
``expected_target_iri``. This sidesteps ambiguity when two different gold
mentions happen to share the same ``surface`` text (e.g. multiple
``"corrosion"`` mentions) -- each is still checked against its own sentence's
output, never against another mention's.

Until the chunk-6 ``msr_extraction.linker`` module lands (Wave 4, authored in
parallel with this harness -- see the task contract), the import below fails
and the two tests below are skipped with a clear reason; the fixture-shape
test has no such dependency and always runs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from msr_extraction.config import Config
from msr_extraction.formula import canonicalize
from msr_extraction.graph_reader import KnownEntity
from msr_extraction.seeding import build_matcher

try:
    from msr_extraction.linker import Segment, link_segment

    _LINKER_IMPORT_ERROR: Exception | None = None
except ImportError as exc:  # pragma: no cover - gates on the Wave 4 linker merge
    Segment = None  # type: ignore[assignment,misc]
    link_segment = None  # type: ignore[assignment]
    _LINKER_IMPORT_ERROR = exc

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ornl_tm_2316_gold.json"

VOC = "https://w3id.org/msr-kg/vocab#"
MSRD = "https://w3id.org/msr-kg/data#"

PRECISION_GATE = 0.90
MIN_GOLD_MENTIONS = 50
MIN_NO_LINK_FRACTION = 0.15

# The fixture-scoped known-entity set: every non-null `expected_target_iri`
# in the gold fixture, with real labels/altLabels sourced from
# ontology/vocab.ttl (concepts) and the loaded FLiBe salt individual's
# rdfs:label (ontology/example-flibe.ttl / design.md's stated
# msrd:salt-BeF2-LiF-34.0-66.0). This mirrors what GraphReader.read_known_entities
# would return from the real graph, without touching GraphDB.
_KNOWN_ENTITIES: list[KnownEntity] = [
    KnownEntity(
        target_iri=f"{VOC}viscosity",
        labels=("viscosity", "dynamic viscosity"),
        kind="concept",
    ),
    KnownEntity(
        target_iri=f"{VOC}density",
        labels=("density", "mass density"),
        kind="concept",
    ),
    KnownEntity(
        target_iri=f"{VOC}surface-tension",
        labels=("surface tension", "interfacial tension"),
        kind="concept",
    ),
    KnownEntity(
        target_iri=f"{VOC}msre-reactor",
        labels=("MSRE reactor", "MSRE", "molten salt reactor experiment"),
        kind="concept",
    ),
    KnownEntity(
        target_iri=f"{VOC}molten-salts",
        labels=(
            "molten salts",
            "fused salts",
            "ionic liquids",
            "molten salt coolants",
        ),
        kind="concept",
    ),
    KnownEntity(
        target_iri=f"{VOC}molten-salt-reactors",
        labels=("molten salt reactors", "MSR"),
        kind="concept",
    ),
    KnownEntity(
        target_iri=f"{VOC}fuel-salt",
        labels=("fuel salt",),
        kind="concept",
    ),
    KnownEntity(
        target_iri=f"{VOC}coolant-salt",
        labels=("coolant salt",),
        kind="concept",
    ),
    KnownEntity(
        target_iri=f"{VOC}corrosion",
        labels=("corrosion",),
        kind="concept",
    ),
    KnownEntity(
        target_iri=f"{VOC}flibe",
        labels=("FLiBe", "LiF-BeF2", "LiF-BeF2 eutectic"),
        kind="concept",
    ),
    KnownEntity(
        target_iri=f"{MSRD}salt-BeF2-LiF-34.0-66.0",
        labels=("BeF2-LiF (34.0-66.0 mol%)",),
        kind="salt",
    ),
    # --- ocr-robust-salt-linking (task 5.5) additions --------------------
    #
    # Single-token, formula-shaped compound concepts (real-vocab-shaped
    # altLabels) -- the catalog the linker's `known_compounds`
    # reconstruction set derives from (design.md D1), so a comma/period
    # OCR-subscript component (`BeF,`, `ThF,`, `UF,`, `ZrF,`) resolves
    # against a *known* compound rather than being left unresolved.
    KnownEntity(
        target_iri=f"{VOC}lithium-fluorides",
        labels=("lithium fluorides", "LiF"),
        kind="concept",
    ),
    KnownEntity(
        target_iri=f"{VOC}beryllium-fluorides",
        labels=("beryllium fluorides", "BeF2"),
        kind="concept",
    ),
    KnownEntity(
        target_iri=f"{VOC}thorium-fluorides",
        labels=("thorium fluorides", "ThF4"),
        kind="concept",
    ),
    KnownEntity(
        target_iri=f"{VOC}uranium-fluorides",
        labels=("uranium fluorides", "UF4"),
        kind="concept",
    ),
    KnownEntity(
        target_iri=f"{VOC}zirconium-fluorides",
        labels=("zirconium fluorides", "ZrF4"),
        kind="concept",
    ),
    KnownEntity(
        target_iri=f"{VOC}sodium-fluorides",
        labels=("sodium fluorides", "NaF"),
        kind="concept",
    ),
]


def _salt_known_entity(salt_token: str, composition: str) -> KnownEntity:
    """Build a `KnownEntity` (kind="salt") for the composed real-OCR gold
    cases below, computing the IRI/label via `canonicalize` rather than
    hand-writing them (task contract: "Compute expected IRIs
    programmatically"). The `rdfs:label` mirrors the real loader's
    `"{formula} ({composition} mol%)"` convention, e.g.
    `"BeF2-LiF (34.0-66.0 mol%)"`."""
    salt = canonicalize(salt_token, composition, "P1")
    iri = MSRD + salt.iri[len("msrd:") :]
    label = salt.canonical.replace(" | ", " (") + " mol%)"
    return KnownEntity(target_iri=iri, labels=(label,), kind="salt")


# Real-OCR composed-salt cases (task 5.5), drawn from multiple curated docs'
# `mol %`/`mole %` + comma-subscript forms (design.md Context): the loader-
# minted individuals these must resolve to, over and above the existing
# MSRE-coolant FLiBe entry above.
_TERNARY_SALT = _salt_known_entity("LiF-BeF2-ThF4", "72-16-12")
_LIF_UF4_SALT = _salt_known_entity("LiF-UF4", "73-27")
_NAF_ZRF4_SALT = _salt_known_entity("NaF-ZrF4", "53-47")

_KNOWN_ENTITIES.extend([_TERNARY_SALT, _LIF_UF4_SALT, _NAF_ZRF4_SALT])


def _load_gold() -> tuple[str, list[dict]]:
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return data["report"], data["mentions"]


def _run_pipeline() -> tuple[list[dict], list[list]]:
    """Link every gold mention's sentence independently; return (mentions, per-mention records)."""
    report, mentions = _load_gold()
    matcher = build_matcher(_KNOWN_ENTITIES)
    known_iris = {e.target_iri for e in _KNOWN_ENTITIES}
    config = Config()

    per_mention_records = []
    for i, mention in enumerate(mentions):
        sentence = mention["sentence"]
        seg = Segment(
            report=report,
            index=i,
            text=sentence,
            char_start=0,
            char_end=len(sentence),
        )
        records = link_segment(
            seg,
            matcher,
            _KNOWN_ENTITIES,
            known_iris,
            config,
            disambiguator=None,
        )
        per_mention_records.append(records)
    return mentions, per_mention_records


def _score(mentions: list[dict], per_mention_records: list[list]) -> tuple[float, float, list[dict]]:
    """Compute (precision, recall, mislinks) per design.md D9.

    precision = correct links / total links emitted (over ALL mentions).
    recall = gold mentions (non-null target) for which a correct link was
    found / total gold mentions with a non-null target.
    """
    total_links = 0
    correct = 0
    mislinks: list[dict] = []
    correctly_linked_gold = 0
    gold_with_target = 0

    for mention, records in zip(mentions, per_mention_records):
        expected = mention["expected_target_iri"]
        if expected is not None:
            gold_with_target += 1

        linked = [r for r in records if r.status == "linked"]
        total_links += len(linked)

        found_correct = False
        for r in linked:
            is_correct = (
                expected is not None
                and r.surface_form == mention["surface"]
                and r.target_iri == expected
            )
            if is_correct:
                correct += 1
                found_correct = True
            else:
                mislinks.append(
                    {
                        "sentence": mention["sentence"],
                        "gold_surface": mention["surface"],
                        "gold_expected": expected,
                        "got_surface": r.surface_form,
                        "got_target": r.target_iri,
                    }
                )
        if found_correct:
            correctly_linked_gold += 1

    precision = correct / total_links if total_links else 0.0
    recall = correctly_linked_gold / gold_with_target if gold_with_target else 0.0
    return precision, recall, mislinks


def test_gold_fixture_has_at_least_50_labelled_mentions_with_no_link_cases() -> None:
    """Fixture-shape regression guard (task 10.8): always runs, no linker needed.

    Pins the fixture's own contract: >= 50 mentions, every ``surface`` is an
    exact substring of its ``sentence``, and a healthy (>= 15%) fraction of
    no-link (``expected_target_iri: null``) cases so precision is
    meaningfully exercised (design.md D9).
    """
    report, mentions = _load_gold()
    assert report == "ORNL-TM-2316"
    assert len(mentions) >= MIN_GOLD_MENTIONS, (
        f"gold fixture must have >= {MIN_GOLD_MENTIONS} mentions, found {len(mentions)}"
    )

    for m in mentions:
        assert {"sentence", "surface", "expected_target_iri"} <= set(m.keys())
        assert m["surface"] in m["sentence"], (
            f"surface {m['surface']!r} is not an exact substring of its sentence {m['sentence']!r}"
        )

    null_count = sum(1 for m in mentions if m["expected_target_iri"] is None)
    assert null_count > 0, "gold fixture must include at least one no-link (null) case"
    fraction = null_count / len(mentions)
    assert fraction >= MIN_NO_LINK_FRACTION, (
        f"no-link fraction {fraction:.2f} ({null_count}/{len(mentions)}) is too small "
        f"to meaningfully test precision (want >= {MIN_NO_LINK_FRACTION:.2f})"
    )


@pytest.mark.skipif(
    link_segment is None,
    reason=(
        "msr_extraction.linker not present yet -- gates on the Wave 4 linker "
        f"merge (import error: {_LINKER_IMPORT_ERROR!r})"
    ),
)
def test_precision_gate() -> None:
    """The gated acceptance criterion: linking precision >= 0.90 on the labelled sample.

    Pins specs/entity-linking/spec.md's "Precision below the gate fails the
    suite" scenario (from the passing side): precision = correct links /
    total links emitted must be >= 0.90, computed with a stubbed
    disambiguator for determinism (design.md D9).
    """
    mentions, per_mention_records = _run_pipeline()
    precision, _recall, mislinks = _score(mentions, per_mention_records)

    assert precision >= PRECISION_GATE, (
        f"linking precision {precision:.3f} is below the {PRECISION_GATE:.2f} gate; "
        f"mislinks: {mislinks!r}"
    )


@pytest.mark.skipif(
    link_segment is None,
    reason=(
        "msr_extraction.linker not present yet -- gates on the Wave 4 linker "
        f"merge (import error: {_LINKER_IMPORT_ERROR!r})"
    ),
)
def test_recall_reported() -> None:
    """Recall is computed and reported as an informational metric, never gated.

    Pins specs/entity-linking/spec.md's "Recall reported, not gated"
    scenario: recall must be a valid float in [0, 1], printed for visibility,
    with no assertion tying the suite's pass/fail to its value.
    """
    mentions, per_mention_records = _run_pipeline()
    _precision, recall, _mislinks = _score(mentions, per_mention_records)

    print(f"\n[precision harness] recall = {recall:.3f} (informational only, not gated)")

    assert isinstance(recall, float)
    assert 0.0 <= recall <= 1.0
