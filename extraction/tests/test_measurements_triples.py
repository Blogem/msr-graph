"""Text-derived measurement triple-emission tests (chunk 7, task 8.5 SPARQL
half + 8.10 graph-queryable extraction provenance + 8.12 writer-level
generation provenance + 8.14 SHACL-shape conformance).

Pins the deterministic locator/IRI derivation (``salt_slug``,
``build_locator``, ``measurement_iri``), the exact set of predicates a
written ``msr:PropertyMeasurement`` must carry so it satisfies the merged
``PropertyMeasurementShape`` (seven required properties, an allowlisted
unit, a both-bounds-or-neither ordered temperature range), the
``msr:extractionConfidence``/``msr:extractionRationale`` extraction
provenance, and the ``INSERT DATA { GRAPH <urn:msr:data> { ... } }``
wrapper (mirrors ``test_mentions.py``/``edges.py`` conventions). Hermetic:
no network, no SQLite -- see ``test_measurements_dual_store.py`` for the
dual-store writer (``write_measurement``) and ``to_row``.

Written against ``msr_extraction.measurements`` before it exists (task 8.5
is implemented by a sibling coder in parallel); it is expected to fail
collection until the pass-2 merge. See the pass-1 handoff report for the
signature assumptions this file pins (flagged for reconciliation).
"""

from __future__ import annotations

import re

from msr_extraction.equations import EquationParse
from msr_extraction.measurements import (
    build_locator,
    insert_data,
    measurement_iri,
    measurement_triples,
    salt_slug,
)

SALT_IRI = "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"
PROPERTY_IRI = "https://w3id.org/msr-kg/ontology#viscosity"
PROPERTY_NAME = "viscosity"
UNIT_CURIE = "unit:MilliPA-SEC"
REPORT = "ORNL-TM-2316"
CONFIDENCE = 0.92
RATIONALE = "stated as ..."

EQUATION_NO_RANGE = EquationParse("Arrhenius", [0.084, 4340], None, None)
EQUATION_WITH_RANGE = EquationParse("Linear", [1, 2], 500.0, 900.0)

# Pinned by the task contract (design.md/text-measurement-writing spec
# intent, exact fixture values agreed with the coder for reconciliation).
EXPECTED_LOCATOR = "doc/ORNL-TM-2316/viscosity#BeF2-LiF-34.0-66.0"
EXPECTED_MIRI = "msrd:m-doc-ORNL-TM-2316-viscosity-BeF2-LiF-34.0-66.0"


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _triples(**overrides: object) -> str:
    """Build one ``measurement_triples(...)`` call with the canonical fixture.

    ASSUMPTION (flagged for pass-2 reconciliation): ``measurement_triples``
    takes the same keyword names as ``write_measurement`` (salt_iri,
    property_iri, property_name, unit_curie, equation, uncertainty,
    confidence, rationale, report) minus the writer-only ``client``/
    ``conn``/``run_ts`` parameters -- there is no ``document_iri`` kwarg;
    the document reference is derived from ``report`` (matching the
    ``msrd:{report}`` CURIE convention already established by
    ``mentions.py``/``edges.py``).
    """
    fields: dict[str, object] = dict(
        salt_iri=SALT_IRI,
        property_iri=PROPERTY_IRI,
        property_name=PROPERTY_NAME,
        unit_curie=UNIT_CURIE,
        equation=EQUATION_NO_RANGE,
        uncertainty=None,
        confidence=CONFIDENCE,
        rationale=RATIONALE,
        report=REPORT,
    )
    fields.update(overrides)
    return measurement_triples(**fields)


# --- locator / IRI derivation (8.5) -----------------------------------------


def test_salt_slug_extracts_canonical_local_form() -> None:
    assert salt_slug(SALT_IRI) == "BeF2-LiF-34.0-66.0"


def test_build_locator_matches_pinned_shape() -> None:
    assert build_locator(REPORT, PROPERTY_NAME, SALT_IRI) == EXPECTED_LOCATOR


def test_measurement_iri_is_deterministic_from_locator() -> None:
    assert measurement_iri(EXPECTED_LOCATOR) == EXPECTED_MIRI
    assert measurement_iri(build_locator(REPORT, PROPERTY_NAME, SALT_IRI)) == EXPECTED_MIRI


# --- SHACL-required predicates (8.5 / 8.12 / 8.14) --------------------------


def test_measurement_triples_contains_all_seven_shacl_required_predicates() -> None:
    block = _triples()
    for predicate in (
        "prov:wasDerivedFrom",
        "prov:wasGeneratedBy",
        "msr:dataLocator",
        "msr:forProperty",
        "msr:ofSalt",
        "msr:hasUnit",
        "msr:equationForm",
    ):
        assert predicate in block, f"missing required predicate {predicate}"


def test_measurement_triples_predicate_values() -> None:
    block = _triples()
    assert "msr:ofSalt msrd:salt-BeF2-LiF-34.0-66.0" in block
    assert "msr:forProperty msr:viscosity" in block
    assert "msr:hasUnit unit:MilliPA-SEC" in block
    assert "msr:equationForm msr:Arrhenius" in block
    assert f'msr:dataLocator "{EXPECTED_LOCATOR}"' in block
    assert "msr:citedIn msrd:ORNL-TM-2316" in block
    assert "prov:wasGeneratedBy msrd:activity-extraction" in block
    assert "prov:wasDerivedFrom msrd:ORNL-TM-2316" in block


def test_measurement_triples_carries_extraction_confidence_and_rationale() -> None:
    """Covers 8.10: extraction provenance is queryable on the measurement
    node itself, alongside its property/unit/locator."""
    block = _triples()
    assert "msr:extractionConfidence" in block
    assert "0.92" in block
    assert "msr:extractionRationale" in block
    assert RATIONALE in block


def test_measurement_triples_has_no_blank_nodes() -> None:
    block = _triples()
    assert "[" not in block
    assert "_:" not in block


def test_measurement_triples_is_deterministic() -> None:
    assert _triples() == _triples()


# --- INSERT DATA wrapper (8.5) -----------------------------------------------


def test_insert_data_wraps_graph_and_declares_prefixes() -> None:
    update = _collapse_ws(insert_data(_triples()))
    assert "INSERT DATA" in update
    assert "GRAPH <urn:msr:data>" in update
    assert "PREFIX unit:" in update
    assert "PREFIX msr:" in update
    assert "PREFIX msrd:" in update
    assert "PREFIX prov:" in update
    assert "PREFIX xsd:" in update
    assert EXPECTED_MIRI in update


# --- both-bounds-or-neither ordered temperature range (8.14) ----------------


def test_measurement_triples_omits_temp_range_when_both_bounds_none() -> None:
    block = _triples(equation=EQUATION_NO_RANGE)
    assert "msr:validTempMin" not in block
    assert "msr:validTempMax" not in block


def test_measurement_triples_includes_ordered_temp_range_when_both_bounds_present() -> None:
    block = _triples(equation=EQUATION_WITH_RANGE)
    assert "msr:validTempMin" in block
    assert "msr:validTempMax" in block
    # Ordered: validTempMin appears before validTempMax.
    assert block.index("msr:validTempMin") < block.index("msr:validTempMax")
    # ASSUMPTION: numeric literal rendering (500 vs 500.0) is not pinned --
    # only substring presence of the numeric value is asserted here.
    assert "500" in block
    assert "900" in block


# --- unit allowlist (8.14) ---------------------------------------------------


def test_measurement_triples_only_allowlisted_unit_is_emitted() -> None:
    block = _triples()
    unit_objects = re.findall(r"msr:hasUnit\s+(\S+)", block)
    assert unit_objects == ["unit:MilliPA-SEC"]
