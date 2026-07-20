"""spaCy matcher seeding tests (task 3.4, design.md D1/D2, specs/entity-ruler-seeding).

Builds a real spaCy `EntityRuler`-backed matcher (`build_matcher`) from a
small `KnownEntity` set and asserts:

- an exact-label span resolves to the right target IRI/kind with correct
  char offsets;
- matching is case-insensitive (`phrase_matcher_attr="LOWER"`);
- a spacing/hyphen surface variant of a label matches its target (layer 2
  of the design.md D2 layered scheme);
- an abbreviation label (`MSRE`) matches its concept;
- rebuilding the matcher from the same input is deterministic.
"""

from __future__ import annotations

from msr_extraction.graph_reader import KnownEntity
from msr_extraction.seeding import build_matcher

VISCOSITY_IRI = "https://w3id.org/msr-kg/vocab#viscosity"
MSRE_REACTOR_IRI = "https://w3id.org/msr-kg/vocab#msre-reactor"
SALT_IRI = "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"


def _known_entities() -> list[KnownEntity]:
    return [
        KnownEntity(target_iri=VISCOSITY_IRI, labels=("viscosity",), kind="concept"),
        KnownEntity(
            target_iri=MSRE_REACTOR_IRI,
            labels=("MSRE", "molten salt reactor experiment"),
            kind="concept",
        ),
        KnownEntity(
            target_iri=SALT_IRI,
            labels=("BeF2-LiF (34.0-66.0 mol%)", "LiF-BeF2"),
            kind="salt",
        ),
    ]


def test_exact_match_resolves_to_target_iri_and_kind_with_correct_offsets() -> None:
    matcher = build_matcher(_known_entities())
    text = "The viscosity of the melt was measured at high temperature."

    matches = matcher.match(text)

    viscosity_matches = [m for m in matches if m.target_iri == VISCOSITY_IRI]
    assert len(viscosity_matches) == 1
    match = viscosity_matches[0]
    assert match.kind == "concept"
    assert text[match.start : match.end] == match.surface
    assert match.surface.lower() == "viscosity"


def test_match_is_case_insensitive() -> None:
    matcher = build_matcher(_known_entities())
    text = "Viscosity was measured across several runs."

    matches = matcher.match(text)

    viscosity_matches = [m for m in matches if m.target_iri == VISCOSITY_IRI]
    assert len(viscosity_matches) == 1
    match = viscosity_matches[0]
    assert text[match.start : match.end] == match.surface
    assert match.surface == "Viscosity"


def test_spacing_variant_of_a_label_matches_the_salt_iri() -> None:
    matcher = build_matcher(_known_entities())
    text = "The sample was described as lif bef2 in the report."

    matches = matcher.match(text)

    salt_matches = [m for m in matches if m.target_iri == SALT_IRI]
    assert len(salt_matches) == 1
    match = salt_matches[0]
    assert match.kind == "salt"
    assert text[match.start : match.end] == match.surface
    assert match.surface.lower() == "lif bef2"


def test_msre_abbreviation_matches_the_reactor_concept() -> None:
    matcher = build_matcher(_known_entities())
    text = "MSRE operated at Oak Ridge National Laboratory."

    matches = matcher.match(text)

    msre_matches = [m for m in matches if m.target_iri == MSRE_REACTOR_IRI]
    assert len(msre_matches) == 1
    match = msre_matches[0]
    assert match.kind == "concept"
    assert text[match.start : match.end] == match.surface
    assert match.surface == "MSRE"


def test_ocr_variants_never_seeded_for_a_non_catalog_formula() -> None:
    """specs/entity-ruler-seeding/spec.md "OCR variants derive only from
    known formulas": `variants.generate_variants` only ever expands from
    labels the known-entity catalog actually carries (design.md D1/D2), so a
    formula-shaped compound the catalog never loaded -- here, xenon
    fluorides ("XeF2") is deliberately absent from `_known_entities()` --
    never gets an OCR-subscript pattern seeded for it at all. Matching stays
    catalog-anchored: a garbled "XeF," surface must not match anything,
    proving there is no free-floating pattern generation over arbitrary
    chemistry independent of the loaded catalog."""
    known = _known_entities()  # no XeF2 / xenon-fluorides entity anywhere
    matcher = build_matcher(known)
    text = "Trace XeF, was reported as an unidentified OCR artifact in the scan."

    matches = matcher.match(text)

    assert matches == []


def test_rebuild_is_deterministic_for_the_same_text() -> None:
    text = (
        "The viscosity of MSRE fuel, described as lif bef2, was measured "
        "and compared to BeF2-LiF (34.0-66.0 mol%) data."
    )

    first_matches = build_matcher(_known_entities()).match(text)
    second_matches = build_matcher(_known_entities()).match(text)

    assert first_matches == second_matches
    assert len(first_matches) > 0
