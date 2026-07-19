"""Layered linker tests (task 10.3, design.md D2/D4/D5/D7).

Hermetic: builds a real spaCy-backed matcher (`seeding.build_matcher`) from a
small in-memory `KnownEntity` set, exercises the formula-normalizer layer
(layer 3) and the bounded `rapidfuzz` fallback (layer 4) directly and
through `link_segment`, and stubs the Flash disambiguator (layer 5) as a
plain callable -- never a live model.
"""

from __future__ import annotations

import json

from msr_extraction import linker
from msr_extraction.config import Config
from msr_extraction.formula import canonicalize
from msr_extraction.graph_reader import KnownEntity
from msr_extraction.linker import (
    MentionRecord,
    Segment,
    expand_curie,
    fuzzy_link,
    link_segment,
    write_mentions_jsonl,
)
from msr_extraction.seeding import build_matcher

VISCOSITY_IRI = "https://w3id.org/msr-kg/vocab#viscosity"
MSRE_IRI = "https://w3id.org/msr-kg/vocab#msre-reactor"
SALT_IRI = "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"

# --- OCR-robust-salt-linking (task 5.3/5.4) fixtures -------------------------
#
# Single-token formula-shaped compound concepts (the catalog compounds the
# linker's `known_compounds` reconstruction set is derived from, per
# design.md D1/D3 -- see `_compound_known_entities`).
LIF_CONCEPT_IRI = "https://w3id.org/msr-kg/vocab#lithium-fluorides"
BEF2_CONCEPT_IRI = "https://w3id.org/msr-kg/vocab#beryllium-fluorides"
THF4_CONCEPT_IRI = "https://w3id.org/msr-kg/vocab#thorium-fluorides"
UF4_CONCEPT_IRI = "https://w3id.org/msr-kg/vocab#uranium-fluorides"


def _compound_known_entities() -> list[KnownEntity]:
    """Compound concepts carrying single-token, formula-shaped altLabels
    (``LiF``, ``BeF2``, ``ThF4``, ``UF4``) -- what the linker's default
    ``known_compounds`` reconstruction set is derived from (design.md D1),
    so an OCR comma/period-subscript component (``BeF,``) can resolve
    against the catalog when composing a salt at layer 3."""
    return [
        KnownEntity(target_iri=LIF_CONCEPT_IRI, labels=("lithium fluorides", "LiF"), kind="concept"),
        KnownEntity(
            target_iri=BEF2_CONCEPT_IRI, labels=("beryllium fluorides", "BeF2"), kind="concept"
        ),
        KnownEntity(target_iri=THF4_CONCEPT_IRI, labels=("thorium fluorides", "ThF4"), kind="concept"),
        KnownEntity(target_iri=UF4_CONCEPT_IRI, labels=("uranium fluorides", "UF4"), kind="concept"),
    ]


def _salt_entity(salt_token: str, composition: str) -> tuple[KnownEntity, str]:
    """Canonicalize ``(salt_token, composition)`` and build the matching
    ``KnownEntity`` (kind="salt") plus its expanded full IRI.

    Computing the IRI/label via `canonicalize` -- rather than hand-writing
    them -- avoids getting the byte-sort/lockstep-composition-reorder rules
    wrong in the test fixtures themselves (task contract: "Compute expected
    IRIs programmatically")."""
    salt = canonicalize(salt_token, composition, "P1")
    iri = expand_curie(salt.iri)
    label = salt.canonical.replace(" | ", " (") + " mol%)"
    return KnownEntity(target_iri=iri, labels=(label,), kind="salt"), iri

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


class TestOCRCommaSubscriptCompoundLinksAtConceptLayer:
    """entity-linking spec "OCR salt-candidate detection ..." /
    entity-ruler-seeding spec "Comma and period subscript variants are
    generated": a comma/period-subscript OCR form of a known catalog
    compound (`BeF,` for `BeF2`) links to that compound's concept at
    layer 2, via the seeded OCR-subscript variant (design.md D2)."""

    def test_comma_subscript_bef2_links_to_beryllium_fluorides_concept(self) -> None:
        known = _compound_known_entities()
        records = _link_with(
            known, "The BeF, component was present in significant quantity in the melt."
        )

        match = next((r for r in records if r.target_iri == BEF2_CONCEPT_IRI), None)
        assert match is not None, f"expected a BeF, -> {BEF2_CONCEPT_IRI} link, got {records!r}"
        assert match.status == "linked"
        assert match.target_kind == "concept"
        assert match.layer == 2
        assert match.surface_form == "BeF,"

    def test_period_subscript_thf4_links_to_thorium_fluorides_concept(self) -> None:
        known = _compound_known_entities()
        records = _link_with(known, "Trace ThF. was detected in the post-run sample analysis.")

        match = next((r for r in records if r.target_iri == THF4_CONCEPT_IRI), None)
        assert match is not None, f"expected a ThF. -> {THF4_CONCEPT_IRI} link, got {records!r}"
        assert match.status == "linked"
        assert match.target_kind == "concept"
        assert match.layer == 2


class TestComposedOCRSaltResolvesAtFormulaLayer:
    """entity-linking spec "OCR salt-candidate detection resolves composed
    mentions to loaded individuals": a composed OCR salt mention (comma
    subscripts, a `mol %`/`mole %` tail) resolves to the loaded salt
    individual at layer 3, not merely to a compound concept. Pins
    design.md's stated M3 anchor and its ternary extension.
    """

    def test_binary_ocr_composed_salt_links_to_loaded_individual(self) -> None:
        salt_entity, salt_iri = _salt_entity("LiF-BeF2", "66-34")
        known = _compound_known_entities() + [salt_entity]

        records = _link_with(
            known,
            "The reference coolant was LiF-BeF, (66-34 mol %) circulating through the loop.",
        )

        salt = next((r for r in records if r.target_iri == salt_iri), None)
        assert salt is not None, (
            f"expected a layer-3 salt link to {salt_iri} (the MSRE-coolant FLiBe "
            f"composition), got {records!r}"
        )
        assert salt.status == "linked"
        assert salt.target_kind == "salt"
        assert salt.layer == 3
        assert salt.score is None

    def test_ternary_ocr_composed_salt_links_to_loaded_individual(self) -> None:
        salt_entity, salt_iri = _salt_entity("LiF-BeF2-ThF4", "72-16-12")
        known = _compound_known_entities() + [salt_entity]

        records = _link_with(
            known,
            "A ternary mixture LiF-BeF,-ThF, (72-16-12 mol %) was evaluated for fuel-salt service.",
        )

        salt = next((r for r in records if r.target_iri == salt_iri), None)
        assert salt is not None, f"expected a layer-3 ternary salt link to {salt_iri}, got {records!r}"
        assert salt.status == "linked"
        assert salt.target_kind == "salt"
        assert salt.layer == 3

    def test_quaternary_ocr_composed_salt_links_to_loaded_individual(self) -> None:
        salt_entity, salt_iri = _salt_entity("LiF-BeF2-ThF4-UF4", "68-20-11-1")
        known = _compound_known_entities() + [salt_entity]

        records = _link_with(
            known,
            "The quaternary fuel LiF-BeF,-ThF,-UF, (68-20-11-1 mole %) was proposed for the reference core.",
        )

        salt = next((r for r in records if r.target_iri == salt_iri), None)
        assert salt is not None, (
            f"expected a layer-3 quaternary salt link to {salt_iri}, got {records!r}"
        )
        assert salt.status == "linked"
        assert salt.target_kind == "salt"
        assert salt.layer == 3

    def test_unresolvable_ocr_component_yields_no_salt_link(self) -> None:
        """A component whose comma-stripped root has no known-compound match
        (`XeF,` -- xenon fluorides are never loaded) must leave the whole
        span unresolved -- never a partial/guessed salt (design.md D1 /
        salt-formula-normalization spec "Unresolved component yields no
        link")."""
        known = _compound_known_entities()

        records = _link_with(
            known, "An untested LiF-XeF, (50-50 mol %) mixture was proposed for comparison only."
        )

        assert not any(r.target_kind == "salt" for r in records)


class TestComposedOCRSaltSupersedesOverlappingConcept:
    """Mirrors `TestComposedSaltSupersedesOverlappingConcept` for the corpus
    OCR surface form: `voc:flibe`'s bare `"LiF-BeF2"` altLabel seeds an
    OCR-subscript exact-match variant (`"LiF-BeF,"`, design.md D2), so a
    *composed* OCR mention must still resolve to the loaded salt individual
    at layer 3, superseding that overlapping layer-2 concept match -- while
    a bare OCR mention (no composition) still resolves to the concept.
    """

    def test_composed_ocr_mention_resolves_to_the_salt_individual_not_the_concept(self) -> None:
        salt_entity, salt_iri = _salt_entity("LiF-BeF2", "66-34")
        flibe = KnownEntity(target_iri=FLIBE_CONCEPT_IRI, labels=("FLiBe", "LiF-BeF2"), kind="concept")
        known = _compound_known_entities() + [flibe, salt_entity]

        records = _link_with(
            known,
            "The LiF-BeF, (66-34 mol %) coolant was circulated through the primary loop.",
        )

        salt = next((r for r in records if r.target_iri == salt_iri), None)
        assert salt is not None, f"expected a layer-3 salt link to {salt_iri}, got {records!r}"
        assert salt.status == "linked"
        assert salt.target_kind == "salt"
        assert salt.layer == 3

        # The concept must not also appear linked for the superseded span.
        assert not any(r.target_iri == FLIBE_CONCEPT_IRI for r in records)

    def test_bare_ocr_formula_mention_with_no_composition_still_resolves_to_the_concept(
        self,
    ) -> None:
        flibe = KnownEntity(target_iri=FLIBE_CONCEPT_IRI, labels=("FLiBe", "LiF-BeF2"), kind="concept")
        known = _compound_known_entities() + [flibe]

        records = _link_with(known, "FLiBe (i.e. LiF-BeF,) was used as the primary coolant.")

        concept_matches = [r for r in records if r.target_iri == FLIBE_CONCEPT_IRI]
        assert len(concept_matches) >= 1
        for match in concept_matches:
            assert match.status == "linked"
            assert match.target_kind == "concept"
            assert match.layer == 2

        # No salt individual should appear -- there is no composition anywhere.
        assert not any(r.target_kind == "salt" for r in records)


class TestDotSeparatorOCRSaltResolvesAtFormulaLayer:
    """Code-review finding 1: `formula._clean_surface` normalizes the
    middle-dot/bullet/dot-operator separators (`·`/`•`/`⋅`) to '-' before
    `_resolve_components` runs, and the linker now always passes
    `known_compounds` through to `normalize_salt_span` (no more gating on
    `_has_ocr_subscript_artifact`). So a composed OCR salt mention using a
    dot separator -- with mid-span comma-subscript artifacts and a `mol %`
    tail, and no intervening whitespace before the separator -- must resolve
    to the SAME loaded salt individual as the hyphen-separated form, at
    layer 3."""

    def test_dot_separator_ternary_ocr_composed_salt_resolves_to_same_iri_as_hyphen_form(
        self,
    ) -> None:
        salt_entity, salt_iri = _salt_entity("LiF-BeF2-ThF4", "72-16-12")
        known = _compound_known_entities() + [salt_entity]

        dot_records = _link_with(
            known,
            "A ternary mixture LiF·BeF,·ThF, (72-16-12 mol %) was evaluated "
            "for dot-separator OCR robustness.",
        )
        hyphen_records = _link_with(
            known,
            "A ternary mixture LiF-BeF,-ThF, (72-16-12 mol %) was evaluated "
            "for fuel-salt service.",
        )

        dot_salt = next((r for r in dot_records if r.target_iri == salt_iri), None)
        assert dot_salt is not None, (
            f"expected a layer-3 dot-separator salt link to {salt_iri}, got {dot_records!r}"
        )
        assert dot_salt.status == "linked"
        assert dot_salt.target_kind == "salt"
        assert dot_salt.layer == 3

        hyphen_salt = next((r for r in hyphen_records if r.target_iri == salt_iri), None)
        assert hyphen_salt is not None, (
            f"expected a layer-3 hyphen salt link to {salt_iri}, got {hyphen_records!r}"
        )

        # Both surface forms must resolve to the exact same salt IRI.
        assert dot_salt.target_iri == hyphen_salt.target_iri == salt_iri


class TestBoundedFuzzyShortChemistryTokens:
    """entity-linking spec "Bounded fuzzy fallback admits short chemistry
    tokens": eligibility for the bounded rapidfuzz layer is governed by
    `Config.fuzzy_min_token_length`, not a hardcoded constant, so short
    (e.g. 3-char `LiF`/`BeF`) formula tokens above the similarity threshold
    can still be admitted to the fallback."""

    def test_fuzzy_link_accepts_a_three_char_token_when_min_length_is_three(self) -> None:
        known_labels = [("LiF-BeF2", FLIBE_CONCEPT_IRI, "concept")]

        result = fuzzy_link("LiF-BeF", known_labels, threshold=90.0, min_token_length=3)

        assert result is not None
        target_iri, kind, score = result
        assert target_iri == FLIBE_CONCEPT_IRI
        assert kind == "concept"
        assert score >= 90.0

    def test_fuzzy_link_rejects_the_same_three_char_token_when_min_length_is_four(self) -> None:
        known_labels = [("LiF-BeF2", FLIBE_CONCEPT_IRI, "concept")]

        result = fuzzy_link("LiF-BeF", known_labels, threshold=90.0, min_token_length=4)

        assert result is None

    def test_below_threshold_short_token_is_not_force_linked_even_when_eligible(self) -> None:
        known_labels = [("LiF-BeF2", FLIBE_CONCEPT_IRI, "concept")]

        result = fuzzy_link("LiF-Bn", known_labels, threshold=90.0, min_token_length=3)

        assert result is None

    def test_link_segment_links_a_short_chemistry_token_via_fuzzy_when_config_lowers_min_length(
        self,
    ) -> None:
        known = [KnownEntity(target_iri=FLIBE_CONCEPT_IRI, labels=("LiF-BeF2",), kind="concept")]
        text = "A garbled LiF-BeF mixture was mentioned in the OCR-damaged scan."
        known_iris = {e.target_iri for e in known}
        matcher = build_matcher(known)
        seg = _segment("ORNL-TM-2316", text)

        # Explicitly pin the single fuzzy knob at its default value (3)
        # rather than relying on it coincidentally matching the default --
        # this is what `link_segment`'s layer-4 call actually reads for
        # every candidate span, formula-shaped or not (see linker.py).
        low_config = Config(fuzzy_min_token_length=3)
        records = link_segment(seg, matcher, known, known_iris, low_config)
        fuzzy = next((r for r in records if r.layer == 4), None)
        assert fuzzy is not None, f"expected a layer-4 fuzzy link, got {records!r}"
        assert fuzzy.target_iri == FLIBE_CONCEPT_IRI
        assert fuzzy.status == "linked"

    def test_link_segment_does_not_fuzzy_link_the_short_token_when_config_min_length_is_higher(
        self,
    ) -> None:
        known = [KnownEntity(target_iri=FLIBE_CONCEPT_IRI, labels=("LiF-BeF2",), kind="concept")]
        text = "A garbled LiF-BeF mixture was mentioned in the OCR-damaged scan."
        known_iris = {e.target_iri for e in known}
        matcher = build_matcher(known)
        seg = _segment("ORNL-TM-2316", text)

        # Layer 4 eligibility is governed by the single
        # `Config.fuzzy_min_token_length` knob -- see `link_segment`'s
        # layer-4 call in linker.py. Raising it above the 3-char "BeF"
        # token's length is what disables the fuzzy fallback here.
        high_config = Config(fuzzy_min_token_length=6)
        records = link_segment(seg, matcher, known, known_iris, high_config)

        assert not any(r.layer == 4 for r in records)


class TestFormulaCandidateSeparatorWhitespaceIsBounded:
    """Second-cycle ReDoS hardening: `linker._FORMULA_SEP` (the separator
    between formula tokens, e.g. the '-' in "LiF-BeF2") must bound its
    surrounding whitespace to `\\s{0,4}`, not an unbounded `\\s*` run, so a
    pathologically long whitespace run around the separator is never
    swallowed into a single candidate span -- while a normally-spaced
    (single-space) separator still resolves at layer 3, same as an
    unspaced one.
    """

    def test_huge_whitespace_run_around_separator_is_not_swallowed_into_one_candidate(
        self,
    ) -> None:
        text = "LiF" + " " * 50 + "-" + " " * 50 + "BeF2 (66-34 mol%)"

        candidates = linker._find_formula_candidates(text)

        # Either no candidate is found at all, or -- if bounded whitespace
        # elsewhere in the pattern still lets something match -- no single
        # returned candidate's surface swallows the giant whitespace run
        # (a legitimate candidate surface is always well under 60 chars).
        assert all(len(surface) <= 60 for _, _, surface in candidates), (
            f"expected the huge whitespace run around the separator to not be "
            f"captured into one candidate span, got {candidates!r}"
        )

    def test_normally_spaced_separator_still_resolves_to_the_loaded_salt_individual(
        self,
    ) -> None:
        # Positive control: a single space on either side of the formula
        # separator must still be captured as a candidate and resolve at
        # layer 3 to the loaded FLiBe salt individual, exactly like the
        # unspaced "LiF-BeF2" form.
        salt_entity, salt_iri = _salt_entity("LiF-BeF2", "66-34")
        known = _compound_known_entities() + [salt_entity]

        records = _link_with(
            known, "The reference coolant was LiF - BeF2 (66-34 mol %) circulating through the loop."
        )

        salt = next((r for r in records if r.target_iri == salt_iri), None)
        assert salt is not None, (
            f"expected a layer-3 salt link to {salt_iri} for the normally-spaced "
            f"separator form, got {records!r}"
        )
        assert salt.status == "linked"
        assert salt.target_kind == "salt"
        assert salt.layer == 3
