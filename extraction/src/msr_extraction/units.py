"""Unit surface-form to QUDT ``unit:`` CURIE mapper (design.md D4).

Implements the ``unit-qudt-mapping`` spec: a dedicated mapper turns an
extracted unit surface form (``cP``, ``mPa·s``, ``g/cm³``, ``mN/m``,
``S/cm``, ...) into the canonical QUDT ``unit:`` CURIE for the
corresponding property, driven entirely by the vendored, tracked
``ontology/qudt-units.json`` allowlist (chunk 2's file — the single source
of truth reused across Go and Python; this module never hardcodes a QUDT
IRI). A surface form that has no known mapping, maps to a CURIE absent
from the allowlist, or maps to a unit outside the extracted property's own
dimension (e.g. a viscosity unit given for a density value) is rejected
rather than silently written, mirroring chunk 2's fail-loud unit guard.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from msr_extraction.config import Config

# Unicode/ASCII variants treated as equivalent when normalizing a surface
# form (spec: "·"<->".", "³"<->"3", "μ"<->"u"). Case is preserved — unit
# case is significant ("cP" vs "S/cm").
_NORMALIZE_CHARS = {
    "·": ".",  # middle dot -> period
    "³": "3",  # superscript three -> "3"
    "μ": "u",  # greek mu -> "u"
}

# Surface-form -> property-name table. Each surface form maps to the
# *property* it names a unit for; the actual QUDT CURIE is then looked up
# from qudt-units.json's per-property `unitCurie` (never hardcoded here),
# so this table stays a pure "what property does this surface form belong
# to" fact and can't drift from the vendored allowlist.
_SURFACE_FORM_TO_PROPERTY: dict[str, str] = {
    # viscosity: cP, mPa*s (and mPa.s / mPas after normalization)
    "cP": "viscosity",
    "mPa.s": "viscosity",
    "mPas": "viscosity",
    # density: g/cm3 (and g/cm³ / g/cc after normalization)
    "g/cm3": "density",
    "g/cc": "density",
    # surface tension
    "mN/m": "surfaceTension",
    # electrical conductivity
    "S/cm": "electricalConductivity",
}


def _normalize(surface_form: str) -> str:
    """Normalize a surface form for lookup (whitespace + unicode variants).

    Strips leading/trailing whitespace and folds the unicode/ASCII variant
    pairs in :data:`_NORMALIZE_CHARS` to their ASCII form. Does NOT
    lowercase — unit case is significant (``cP``, ``S/cm``).
    """
    normalized = surface_form.strip()
    for unicode_char, ascii_char in _NORMALIZE_CHARS.items():
        normalized = normalized.replace(unicode_char, ascii_char)
    return normalized


@dataclass(frozen=True)
class UnitResult:
    """The outcome of resolving a unit surface form against the allowlist."""

    unit_curie: str | None  # e.g. "unit:MilliPA-SEC" when ok, else None
    ok: bool
    reason: str  # "" when ok; else "unmappable" | "out-of-allowlist" | "dimension-mismatch"


class UnitMapper:
    """Maps unit surface forms to canonical, allowlisted QUDT ``unit:`` CURIEs.

    Driven entirely by the vendored ``ontology/qudt-units.json`` (chunk 2) —
    see the module docstring and design.md D4 / the ``unit-qudt-mapping``
    spec.
    """

    def __init__(self, catalog: dict) -> None:
        self._properties: dict = catalog.get("properties", {})
        allowed_units: list[str] = catalog.get("allowedUnits", [])
        unit_prefix: str = catalog.get("prefixes", {}).get(
            "unit", "http://qudt.org/vocab/unit/"
        )
        self._allowed_curies: set[str] = {
            self._iri_to_curie(iri, unit_prefix) for iri in allowed_units
        }

    @staticmethod
    def _iri_to_curie(iri: str, unit_prefix: str) -> str:
        if iri.startswith(unit_prefix):
            return "unit:" + iri[len(unit_prefix) :]
        return iri

    @classmethod
    def from_path(cls, path: Path) -> UnitMapper:
        """Build a UnitMapper from a qudt-units.json file at ``path``."""
        catalog = json.loads(Path(path).read_text())
        return cls(catalog)

    @classmethod
    def from_config(cls, config: Config) -> UnitMapper:
        """Build a UnitMapper from ``config.qudt_units_path``."""
        return cls.from_path(config.qudt_units_path)

    def canonical_unit_curie_for(self, property_name: str) -> str | None:
        """The canonical ``unit:`` CURIE for ``property_name``, or None."""
        entry = self._properties.get(property_name)
        if entry is None:
            return None
        return entry.get("unitCurie")

    def is_allowed(self, unit_curie: str) -> bool:
        """Whether ``unit_curie`` is a member of the vendored allowlist."""
        return unit_curie in self._allowed_curies

    def resolve(self, surface_form: str, property_name: str) -> UnitResult:
        """Resolve ``surface_form`` to a canonical, validated ``unit:`` CURIE.

        1. Normalizes the surface form (whitespace + unicode variants).
        2. Maps it to a property via the surface-form table, then looks up
           that property's canonical ``unitCurie`` from the vendored
           catalog. No mapping -> ``"unmappable"``.
        3. Validates the mapped CURIE against the vendored allowlist. Not
           present -> ``"out-of-allowlist"``.
        4. Checks the mapped CURIE equals ``property_name``'s own canonical
           unit (dimensional consistency). Mismatch -> ``"dimension-mismatch"``.
        """
        normalized = _normalize(surface_form)
        mapped_property = _SURFACE_FORM_TO_PROPERTY.get(normalized)
        if mapped_property is None:
            return UnitResult(None, False, "unmappable")

        unit_curie = self.canonical_unit_curie_for(mapped_property)
        if unit_curie is None:
            return UnitResult(None, False, "unmappable")

        if not self.is_allowed(unit_curie):
            return UnitResult(None, False, "out-of-allowlist")

        expected_curie = self.canonical_unit_curie_for(property_name)
        if expected_curie is None or unit_curie != expected_curie:
            return UnitResult(None, False, "dimension-mismatch")

        return UnitResult(unit_curie, True, "")
