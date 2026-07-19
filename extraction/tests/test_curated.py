"""Evolution-target gate tests (task 9.6, design.md D2/D8).

# PLACEHOLDER target sentences — the finalization step (task 4.4) replaces
# the fixtures under fixtures/target_solubility.txt and
# fixtures/target_graphite.txt with the ACTUAL quoted sentences from the
# curated msr-archive OCR (recorded, with grep-level evidence, in
# docs/DATA_SCOPE.md). Until then these committed fixtures are stand-ins
# that pin the detection *patterns*, not the final evidentiary sentences.

Also pins that the committed curated-set list (``CURATED_REPORTS``) has at
least the 7 confirmed DATA_SCOPE anchors.
"""

from __future__ import annotations

from pathlib import Path

from msr_extraction.curated import CURATED_REPORTS, detect_evolution_targets

FIXTURES = Path(__file__).parent / "fixtures"


def test_detect_solubility_target_present_in_fixture() -> None:
    text = (FIXTURES / "target_solubility.txt").read_text(encoding="utf-8")
    result = detect_evolution_targets(text)
    assert result["solubility"] is True


def test_detect_graphite_moderator_target_present_in_fixture() -> None:
    text = (FIXTURES / "target_graphite.txt").read_text(encoding="utf-8")
    result = detect_evolution_targets(text)
    assert result["graphite_moderator"] is True


def test_detect_solubility_negative_without_numeric_value_and_unit() -> None:
    # Mentions "solubility" but carries no associated numeric value + unit,
    # so this must NOT trip the gate.
    text = (
        "Solubility is an important property of fluoride salts and has "
        "been studied extensively in the literature over several decades."
    )
    result = detect_evolution_targets(text)
    assert result["solubility"] is False


def test_detect_graphite_moderator_negative_without_moderator_context() -> None:
    # Mentions "graphite" but not in a moderator-role context.
    text = "The sample crucible was lined with graphite for corrosion testing."
    result = detect_evolution_targets(text)
    assert result["graphite_moderator"] is False


def test_curated_reports_has_at_least_seven_entries() -> None:
    assert len(CURATED_REPORTS) >= 7
