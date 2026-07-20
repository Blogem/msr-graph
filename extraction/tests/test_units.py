"""Unit -> QUDT mapping tests (task 8.3, spec unit-qudt-mapping).

Pins ``UnitMapper.resolve(surface, property) -> UnitResult`` against the
vendored ``ontology/qudt-units.json`` allowlist: known surface forms map to
their canonical ``unit:`` CURIE for the matching property, an unmappable
surface form is rejected with reason ``"unmappable"``, and a
dimensionally-inconsistent surface form/property pairing (a real, mappable
unit for the *wrong* property) is rejected with reason
``"dimension-mismatch"``. Also pins ``is_allowed`` against the allowlist.

Hermetic: builds the mapper from the real vendored JSON on disk (no
network, no live model).
"""

from __future__ import annotations

from pathlib import Path

from msr_extraction.units import UnitMapper, UnitResult

QUDT_UNITS_PATH = Path(__file__).resolve().parents[2] / "ontology" / "qudt-units.json"


def _mapper() -> UnitMapper:
    return UnitMapper.from_path(QUDT_UNITS_PATH)


def test_from_path_loads_the_vendored_qudt_units_json() -> None:
    mapper = _mapper()
    assert isinstance(mapper, UnitMapper)


def test_resolve_viscosity_cp_maps_to_millipa_sec() -> None:
    result = _mapper().resolve("cP", "viscosity")
    assert isinstance(result, UnitResult)
    assert result.ok is True
    assert result.unit_curie == "unit:MilliPA-SEC"


def test_resolve_viscosity_mpa_s_maps_to_millipa_sec() -> None:
    result = _mapper().resolve("mPa·s", "viscosity")
    assert result.ok is True
    assert result.unit_curie == "unit:MilliPA-SEC"


def test_resolve_density_g_per_cm3_maps_to_gm_per_centim3() -> None:
    result = _mapper().resolve("g/cm³", "density")
    assert result.ok is True
    assert result.unit_curie == "unit:GM-PER-CentiM3"


def test_resolve_surface_tension_mn_per_m_maps_to_millin_per_m() -> None:
    result = _mapper().resolve("mN/m", "surfaceTension")
    assert result.ok is True
    assert result.unit_curie == "unit:MilliN-PER-M"


def test_resolve_electrical_conductivity_s_per_cm_maps_to_s_per_centim() -> None:
    result = _mapper().resolve("S/cm", "electricalConductivity")
    assert result.ok is True
    assert result.unit_curie == "unit:S-PER-CentiM"


def test_resolve_unmappable_surface_form_is_rejected() -> None:
    result = _mapper().resolve("furlongs", "density")
    assert result.ok is False
    assert result.reason == "unmappable"


def test_resolve_dimension_mismatch_is_rejected() -> None:
    """mPa·s is a real, mappable viscosity unit -- but paired with the
    wrong property (density) it must be rejected as a dimension mismatch,
    not silently accepted or treated as merely unmappable."""
    result = _mapper().resolve("mPa·s", "density")
    assert result.ok is False
    assert result.reason == "dimension-mismatch"


def test_is_allowed_true_for_an_allowlisted_unit_curie() -> None:
    assert _mapper().is_allowed("unit:MilliPA-SEC") is True


def test_is_allowed_false_for_a_non_allowlisted_unit_curie() -> None:
    assert _mapper().is_allowed("unit:NOPE") is False
