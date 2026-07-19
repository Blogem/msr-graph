"""Layered linker tests (task 10.3, design.md D2/D4/D5/D7).

Hermetic: builds a real spaCy-backed matcher (`seeding.build_matcher`) from a
small in-memory `KnownEntity` set, exercises the formula-normalizer layer
(layer 3) and the bounded `rapidfuzz` fallback (layer 4) directly and
through `link_segment`, and stubs the Flash disambiguator (layer 5) as a
plain callable -- never a live model.
"""

from __future__ import annotations

import json

from msr_extraction.config import Config
from msr_extraction.graph_reader import KnownEntity
from msr_extraction.linker import (
    MentionRecord,
    Segment,
    fuzzy_link,
    link_segment,
    write_mentions_jsonl,
)
from msr_extraction.seeding import build_matcher

VISCOSITY_IRI = "https://w3id.org/msr-kg/vocab#viscosity"
MSRE_IRI = "https://w3id.org/msr-kg/vocab#msre-reactor"
SALT_IRI = "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"

_MENTIONS_JSONL_KEYS = {
    "report",
    "seg_index",
    "char_start",
    "char_end",
    "surface_form",
    "status",
    "target_iri",
    "target_kind",
    "layer",
    "score",
}


FLIBE_CONCEPT_IRI = "https://w3id.org/msr-kg/vocab#flibe"


def _known_entities() -> list[KnownEntity]:
    return [
        KnownEntity(target_iri=VISCOSITY_IRI, labels=("viscosity",), kind="concept"),
        KnownEntity(
            target_iri=MSRE_IRI,
            labels=("MSRE", "molten salt reactor experiment"),
            kind="concept",
        ),
        # Deliberately NOT registering a bare "LiF-BeF2"/"BeF2-LiF" exact
        # label on any concept here: these fixtures only need layer 3 (the
        # formula normalizer) to resolve the composed-mention spans, without
        # also exercising the salt-supersedes-concept overlap precedence --
        # that precedence (a real requirement: the actual vocab registers
        # `voc:flibe` with altLabel "LiF-BeF2") is covered on its own below
        # by TestComposedSaltSupersedesOverlappingConcept.
        KnownEntity(target_iri=SALT_IRI, labels=("BeF2-LiF (34.0-66.0 mol%)",), kind="salt"),
    ]


def _known_entities_with_flibe_altlabel() -> list[KnownEntity]:
    """Mirrors the real seed data: `voc:flibe` carries the bare formula
    "LiF-BeF2" as a `skos:altLabel`, alongside the loaded salt individual."""
    return [
        KnownEntity(
            target_iri=FLIBE_CONCEPT_IRI,
            labels=("FLiBe", "LiF-BeF2"),
            kind="concept",
        ),
        KnownEntity(target_iri=SALT_IRI, labels=("BeF2-LiF (34.0-66.0 mol%)",), kind="salt"),
    ]


def _segment(report: str, text: str, *, index: int = 0) -> Segment:
    return Segment(report=report, index=index, text=text, char_start=0, char_end=len(text))


def _link_with(known: list[KnownEntity], text: str, *, disambiguator=None) -> list[MentionRecord]:
    known_iris = {e.target_iri for e in known}
    matcher = build_matcher(known)
    seg = _segment("ORNL-TM-2316", text)
    return link_segment(
        seg, matcher, known, known_iris, Config(), disambiguator=disambiguator
    )


def _link(text: str, *, disambiguator=None) -> list[MentionRecord]:
    return _link_with(_known_entities(), text, disambiguator=disambiguator)


class TestAnchorSpans:
    def test_viscosity_links_to_concept_via_exact_match(self) -> None:
        records = _link("The viscosity of the melt was measured at high temperature.")

        viscosity = next(r for r in records if r.target_iri == VISCOSITY_IRI)
        assert viscosity.status == "linked"
        assert viscosity.target_kind == "concept"
        assert viscosity.layer == 2
        assert viscosity.surface_form.lower() == "viscosity"

    def test_msre_links_to_concept_via_exact_match(self) -> None:
        records = _link("MSRE operated at Oak Ridge National Laboratory.")

        msre = next(r for r in records if r.target_iri == MSRE_IRI)
        assert msre.status == "linked"
        assert msre.target_kind == "concept"
        assert msre.layer == 2
        assert msre.surface_form == "MSRE"

    def test_composed_salt_mention_links_via_formula_layer(self) -> None:
        records = _link("The mixture LiF-BeF2 (66-34 mol%) was heated to fuel temperature.")

        salt = next(r for r in records if r.target_iri == SALT_IRI)
        assert salt.status == "linked"
        assert salt.target_kind == "salt"
        assert salt.layer == 3
        assert salt.score is None


class TestOrderUnification:
    def test_bef2_lif_and_lif_bef2_with_composition_unify_to_same_salt_iri(self) -> None:
        records_a = _link("The salt BeF2-LiF (34-66 mol%) was analyzed by the group.")
        records_b = _link("The salt LiF-BeF2 (66-34 mol%) was analyzed by the group.")

        salt_a = next(r for r in records_a if r.layer == 3)
        salt_b = next(r for r in records_b if r.layer == 3)

        assert salt_a.target_iri == SALT_IRI
        assert salt_b.target_iri == SALT_IRI
        assert salt_a.target_iri == salt_b.target_iri


class TestComposedSaltSupersedesOverlappingConcept:
    """Pins design.md D3's "Salt mention resolves to the loaded individual"
    scenario against a realistic overlap: `voc:flibe` carries a bare
    "LiF-BeF2" altLabel (as the real seed vocab does), so layer 2's exact
    matcher finds that sub-span inside a *composed* mention too. Layer 3's
    successful, more-specific salt match must supersede it -- while a truly
    bare mention (no composition anywhere) still resolves to the concept.
    """

    def test_composed_mention_resolves_to_the_salt_individual_not_the_concept(self) -> None:
        known = _known_entities_with_flibe_altlabel()
        records = _link_with(
            known, "The LiF-BeF2 (66-34 mol%) coolant was circulated through the primary loop."
        )

        salt = next(r for r in records if r.target_iri == SALT_IRI)
        assert salt.status == "linked"
        assert salt.target_kind == "salt"
        assert salt.layer == 3

        # The concept must not also appear linked for the superseded span.
        assert not any(r.target_iri == FLIBE_CONCEPT_IRI for r in records)

    def test_bare_mention_with_no_composition_still_resolves_to_the_concept(self) -> None:
        known = _known_entities_with_flibe_altlabel()
        records = _link_with(known, "FLiBe (i.e. LiF-BeF2) was used as the primary coolant.")

        concept_matches = [r for r in records if r.target_iri == FLIBE_CONCEPT_IRI]
        assert len(concept_matches) >= 1
        for match in concept_matches:
            assert match.status == "linked"
            assert match.target_kind == "concept"
            assert match.layer == 2

        # No salt individual should appear -- there is no composition anywhere.
        assert not any(r.target_iri == SALT_IRI for r in records)


class TestBoundedFuzzyFallback:
    def test_above_threshold_ocr_variant_links_to_known_label(self) -> None:
        known_labels = [("viscosity", VISCOSITY_IRI, "concept")]

        result = fuzzy_link("viscosityy", known_labels, threshold=90.0, min_token_length=4)

        assert result is not None
        target_iri, kind, score = result
        assert target_iri == VISCOSITY_IRI
        assert kind == "concept"
        assert score >= 90.0

    def test_below_threshold_surface_is_not_force_linked(self) -> None:
        known_labels = [("viscosity", VISCOSITY_IRI, "concept")]

        result = fuzzy_link("banana", known_labels, threshold=90.0, min_token_length=4)

        assert result is None

    def test_no_known_labels_returns_none(self) -> None:
        assert fuzzy_link("viscosity", [], threshold=90.0, min_token_length=4) is None


class TestNovelPath:
    def test_unresolved_formula_span_is_novel_without_a_disambiguator(self) -> None:
        # NaCl-KCl is structurally a valid formula+composition candidate
        # (formula.normalize_salt_span will happily canonicalize it), but
        # its salt IRI was never loaded into known_iris here -- so layer 3
        # rejects the link, layer 4 has no similar known label to fuzzy-hit,
        # and with no disambiguator, layer 5 records it as novel.
        records = _link("The mixture NaCl-KCl (50-50 mol%) was untested in this report.")

        novel = [r for r in records if r.status == "novel"]
        assert len(novel) == 1
        record = novel[0]
        assert record.layer == 5
        assert record.target_iri is None
        assert record.target_kind is None

    def test_disambiguator_linking_to_a_known_iri_is_recorded_at_layer_5(self) -> None:
        def stub_disambiguator(surface: str, sentence: str) -> tuple[str, str | None]:
            return ("linked", VISCOSITY_IRI)

        records = _link(
            "The mixture NaCl-KCl (50-50 mol%) was untested in this report.",
            disambiguator=stub_disambiguator,
        )

        linked = [r for r in records if r.layer == 5]
        assert len(linked) == 1
        assert linked[0].status == "linked"
        assert linked[0].target_iri == VISCOSITY_IRI
        assert linked[0].target_kind == "concept"

    def test_disambiguator_declaring_novel_is_recorded_as_novel(self) -> None:
        def stub_disambiguator(surface: str, sentence: str) -> tuple[str, str | None]:
            return ("novel", None)

        records = _link(
            "The mixture NaCl-KCl (50-50 mol%) was untested in this report.",
            disambiguator=stub_disambiguator,
        )

        novel = [r for r in records if r.status == "novel"]
        assert len(novel) == 1
        assert novel[0].layer == 5


class TestMentionsJsonlSchemaAndDeterminism:
    def test_write_mentions_jsonl_is_deterministic_and_has_the_required_keys(self, tmp_path) -> None:
        config = Config(corpus_dir=tmp_path)
        records = [
            MentionRecord(
                report="ORNL-TM-2316",
                seg_index=0,
                char_start=4,
                char_end=13,
                surface_form="viscosity",
                status="linked",
                target_iri=VISCOSITY_IRI,
                target_kind="concept",
                layer=2,
                score=None,
            ),
            MentionRecord(
                report="ORNL-TM-2316",
                seg_index=0,
                char_start=20,
                char_end=40,
                surface_form="NaCl-KCl (50-50 mol%)",
                status="novel",
                target_iri=None,
                target_kind=None,
                layer=5,
                score=None,
            ),
        ]

        write_mentions_jsonl("ORNL-TM-2316", records, config)
        first = config.mentions_path("ORNL-TM-2316").read_text(encoding="utf-8")

        write_mentions_jsonl("ORNL-TM-2316", records, config)
        second = config.mentions_path("ORNL-TM-2316").read_text(encoding="utf-8")

        assert first == second

        lines = [line for line in first.splitlines() if line]
        assert len(lines) == 2
        for line in lines:
            obj = json.loads(line)
            assert set(obj.keys()) == _MENTIONS_JSONL_KEYS

    def test_write_mentions_jsonl_records_linked_and_novel_status(self, tmp_path) -> None:
        config = Config(corpus_dir=tmp_path)
        records = [
            MentionRecord(
                report="ORNL-TM-2316",
                seg_index=0,
                char_start=0,
                char_end=9,
                surface_form="viscosity",
                status="linked",
                target_iri=VISCOSITY_IRI,
                target_kind="concept",
                layer=2,
                score=None,
            ),
            MentionRecord(
                report="ORNL-TM-2316",
                seg_index=1,
                char_start=0,
                char_end=10,
                surface_form="gibberish",
                status="novel",
                target_iri=None,
                target_kind=None,
                layer=5,
                score=None,
            ),
        ]

        write_mentions_jsonl("ORNL-TM-2316", records, config)
        lines = [
            json.loads(line)
            for line in config.mentions_path("ORNL-TM-2316").read_text(encoding="utf-8").splitlines()
            if line
        ]

        statuses = {obj["status"] for obj in lines}
        assert statuses == {"linked", "novel"}
