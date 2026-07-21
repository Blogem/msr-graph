"""Safety-property-linking edge tests (openspec/changes/ingest-iaea-safety,
spec ``safety-property-linking``, task 8.5).

Two layers, mirroring the project's existing chunk-7 test split
(``test_edges.py`` for triple emission, ``test_relations_extract.py`` /
``test_relations_validate.py`` for the Flash-call + closed-set-validation
funnel):

1. ``edges.served_by_edge_triples``/``edges.addresses_function_edge_triples``
   (pinned in the tester's task contract) -- deterministic, reified,
   no-blank-node triple blocks, mirroring ``role_edge_triples``/
   ``reactor_edge_triples`` exactly (same reification shape:
   ``rdf:Statement`` + ``msr:extractionConfidence``/
   ``msr:extractionRationale`` + ``msr:citedIn`` + generation provenance).
2. ``relations.validate_relation``/``relations.extract_relations``/
   ``relations.extract_report`` -- the closed-set validation + precision
   guard (co-mention without a stated dependency yields no edge) +
   two-phase-safe rejection of an unknown/not-yet-approved target.

ASSUMPTION (pass-1, flagged for reconciliation at merge): none of
``edges.ServedByEdge``/``edges.AddressesFunctionEdge``/
``edges.served_by_edge_triples``/``edges.addresses_function_edge_triples``,
nor ``relations.validate_relation``'s "served_by_property"/
"addresses_function" kind branches, nor ``KnownSets.safety_functions``/
``.requirements``, exist yet on this isolated pass-1 branch. Every test
below is written against the pinned contract (design.md D4, tasks 4.1-4.3,
mirroring the existing ``RoleEdge``/``ReactorEdge`` + "role"/"reactor" kind
conventions) rather than any implementation, and is expected to fail with
a collection error (edges-layer tests) or a ValueError/assertion failure
(relations-layer tests, since ``validate_relation`` itself already exists
and currently has no "served_by_property"/"addresses_function" branch) --
NOT a shared identical failure mode, but both are pass-1-expected.
``relations.extract_relations`` itself is already-landed and genre-agnostic
(no ``kind`` dispatch inside it), so the co-mention-no-edge test exercises
real, already-existing code.
"""

from __future__ import annotations

import json
from pathlib import Path

from msr_extraction.config import Config
from msr_extraction.edges import (
    AddressesFunctionEdge,
    ServedByEdge,
    addresses_function_edge_triples,
    served_by_edge_triples,
)
from msr_extraction.relations import (
    KnownSets,
    LinkedMention,
    SelectedSentence,
    extract_relations,
    extract_report,
    validate_relation,
)

REPORT = "GIF-Holcomb-MSR-safety"
DOCUMENT_IRI = "https://w3id.org/msr-kg/data#GIF-Holcomb-MSR-safety"

SAFETY_FUNCTION = "https://w3id.org/msr-kg/data#sf-heat-removal"
UNKNOWN_SAFETY_FUNCTION = "https://w3id.org/msr-kg/data#sf-not-yet-approved"
REQUIREMENT = "https://w3id.org/msr-kg/data#requirement-coolant-selection"
SPECIFIC_HEAT = "https://w3id.org/msr-kg/ontology#specificHeat"
VISCOSITY = "https://w3id.org/msr-kg/ontology#viscosity"
UNKNOWN_PROPERTY = "https://w3id.org/msr-kg/ontology#solubility"

THRESHOLD = 0.5


class StubCompleter:
    """Same shape as the project's other stub Completers: ``.complete(system,
    user) -> str``, never touches the network."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self.response


SERVED_BY_EDGE = ServedByEdge(
    safety_function_iri=SAFETY_FUNCTION,
    property_iri=SPECIFIC_HEAT,
    report=REPORT,
    document_iri=DOCUMENT_IRI,
    confidence=0.9,
    rationale="heat capacity is cited as needed for natural circulation cooling",
)

ADDRESSES_FUNCTION_EDGE = AddressesFunctionEdge(
    requirement_iri=REQUIREMENT,
    safety_function_iri=SAFETY_FUNCTION,
    report=REPORT,
    document_iri=DOCUMENT_IRI,
    confidence=0.85,
    rationale="the coolant-selection requirement is stated to serve heat removal",
)


def _known() -> KnownSets:
    return KnownSets(
        molten_salts=set(),
        physical_properties={SPECIFIC_HEAT, VISCOSITY},
        salt_roles=set(),
        reactor_concepts=set(),
        safety_functions=frozenset({SAFETY_FUNCTION}),
        requirements=frozenset({REQUIREMENT}),
    )


def _sentence(text: str, linked_mentions: list[LinkedMention] | None = None) -> SelectedSentence:
    return SelectedSentence(
        report=REPORT,
        seg_index=0,
        char_start=0,
        char_end=len(text),
        text=text,
        linked_mentions=linked_mentions or [],
    )


# --- edges.py: served_by_property triple emission --------------------------


def test_served_by_edge_triples_contain_the_direct_edge() -> None:
    block = served_by_edge_triples(SERVED_BY_EDGE)
    assert "msrd:sf-heat-removal msr:servedByProperty msr:specificHeat" in block


def test_served_by_edge_triples_contain_reification_with_predicate_and_object() -> None:
    block = served_by_edge_triples(SERVED_BY_EDGE)
    assert "a rdf:Statement" in block
    assert "rdf:predicate msr:servedByProperty" in block
    assert "rdf:object msr:specificHeat" in block


def test_served_by_edge_triples_carry_confidence_and_rationale() -> None:
    block = served_by_edge_triples(SERVED_BY_EDGE)
    assert "msr:extractionConfidence" in block
    assert "msr:extractionRationale" in block


def test_served_by_edge_triples_carry_generation_provenance() -> None:
    block = served_by_edge_triples(SERVED_BY_EDGE)
    assert "prov:wasGeneratedBy msrd:activity-extraction" in block
    assert "prov:wasDerivedFrom msrd:GIF-Holcomb-MSR-safety" in block or (
        f"prov:wasDerivedFrom <{DOCUMENT_IRI}>" in block
    )


def test_served_by_edge_triples_have_no_blank_nodes() -> None:
    block = served_by_edge_triples(SERVED_BY_EDGE)
    assert "[" not in block
    assert "_:" not in block


def test_served_by_edge_triples_are_deterministic() -> None:
    assert served_by_edge_triples(SERVED_BY_EDGE) == served_by_edge_triples(SERVED_BY_EDGE)


def test_served_by_edge_triples_never_mention_a_molten_salt_or_bare_value() -> None:
    """Scenario: "No direct safety-to-salt or safety-to-value edge" -- the
    edge triple block for a servedByProperty edge relates only the safety
    function and the property, never a MoltenSalt individual."""
    block = served_by_edge_triples(SERVED_BY_EDGE)
    assert "MoltenSalt" not in block


# --- edges.py: addresses_function triple emission --------------------------


def test_addresses_function_edge_triples_contain_the_direct_edge() -> None:
    block = addresses_function_edge_triples(ADDRESSES_FUNCTION_EDGE)
    assert "msrd:requirement-coolant-selection msr:addressesFunction msrd:sf-heat-removal" in block


def test_addresses_function_edge_triples_contain_reification_with_predicate_and_object() -> None:
    block = addresses_function_edge_triples(ADDRESSES_FUNCTION_EDGE)
    assert "a rdf:Statement" in block
    assert "rdf:predicate msr:addressesFunction" in block
    assert "rdf:object msrd:sf-heat-removal" in block


def test_addresses_function_edge_triples_carry_confidence_and_rationale() -> None:
    block = addresses_function_edge_triples(ADDRESSES_FUNCTION_EDGE)
    assert "msr:extractionConfidence" in block
    assert "msr:extractionRationale" in block


def test_addresses_function_edge_triples_carry_generation_provenance() -> None:
    block = addresses_function_edge_triples(ADDRESSES_FUNCTION_EDGE)
    assert "prov:wasGeneratedBy msrd:activity-extraction" in block


def test_addresses_function_edge_triples_have_no_blank_nodes() -> None:
    block = addresses_function_edge_triples(ADDRESSES_FUNCTION_EDGE)
    assert "[" not in block
    assert "_:" not in block


def test_addresses_function_edge_triples_are_deterministic() -> None:
    assert addresses_function_edge_triples(ADDRESSES_FUNCTION_EDGE) == addresses_function_edge_triples(
        ADDRESSES_FUNCTION_EDGE
    )


# --- relations.py: closed-set validation (task 4.1/4.2/4.3) ----------------


def test_served_by_property_relation_is_written_when_property_is_known() -> None:
    """Scenario: "Stated dependency produces an edge" -- a servedByProperty
    relation targeting an existing seed PhysicalProperty validates."""
    raw = {
        "kind": "served_by_property",
        "safety_function": SAFETY_FUNCTION,
        "property": SPECIFIC_HEAT,
        "confidence": 0.9,
        "rationale": "heat capacity is cited as needed for natural circulation cooling",
    }
    validated, record = validate_relation(raw, _sentence("stub"), _known(), None, THRESHOLD)

    assert validated is not None
    assert record.disposition == "written"


def test_served_by_property_relation_is_rejected_for_unknown_property() -> None:
    """Scenario basis: "Each edge's PhysicalProperty target MUST already
    exist in core; an edge to an unknown property IRI SHALL be rejected"."""
    raw = {
        "kind": "served_by_property",
        "safety_function": SAFETY_FUNCTION,
        "property": UNKNOWN_PROPERTY,
        "confidence": 0.9,
        "rationale": "an unknown property reference",
    }
    validated, record = validate_relation(raw, _sentence("stub"), _known(), None, THRESHOLD)

    assert validated is None
    assert record.disposition == "rejected"


def test_served_by_property_relation_never_carries_a_salt_reference() -> None:
    """Scenario: "No direct safety-to-salt or safety-to-value edge" -- the
    validated payload (whatever its exact type) exposes no salt-shaped
    field the writer could use to assert a SafetyFunction->MoltenSalt
    edge."""
    raw = {
        "kind": "served_by_property",
        "safety_function": SAFETY_FUNCTION,
        "property": SPECIFIC_HEAT,
        "confidence": 0.9,
        "rationale": "heat capacity is cited as needed for natural circulation cooling",
    }
    validated, _record = validate_relation(raw, _sentence("stub"), _known(), None, THRESHOLD)

    assert validated is not None
    assert not hasattr(validated, "salt_iri")


def test_addresses_function_relation_is_written_when_target_is_approved() -> None:
    """Scenario: "Requirement addresses a function" -- once the target
    SafetyFunction has been approved into core (present in
    known.safety_functions), the edge validates."""
    raw = {
        "kind": "addresses_function",
        "requirement": REQUIREMENT,
        "safety_function": SAFETY_FUNCTION,
        "confidence": 0.85,
        "rationale": "the coolant-selection requirement is stated to serve heat removal",
    }
    validated, record = validate_relation(raw, _sentence("stub"), _known(), None, THRESHOLD)

    assert validated is not None
    assert record.disposition == "written"


def test_addresses_function_relation_is_rejected_when_target_not_yet_approved() -> None:
    """Scenario: "An edge to a not-yet-approved function is rejected" --
    exactly as the closed-set validation rejects any relation naming an
    entity absent from core."""
    raw = {
        "kind": "addresses_function",
        "requirement": REQUIREMENT,
        "safety_function": UNKNOWN_SAFETY_FUNCTION,
        "confidence": 0.85,
        "rationale": "references a safety function not yet promoted to core",
    }
    validated, record = validate_relation(raw, _sentence("stub"), _known(), None, THRESHOLD)

    assert validated is None
    assert record.disposition == "rejected"


def test_below_threshold_served_by_property_relation_is_skipped_not_written() -> None:
    """Scenario: "A below-confidence-threshold edge is skipped" -- no edge
    or reification node is written; the relation is recorded with
    disposition:"skipped"."""
    raw = {
        "kind": "served_by_property",
        "safety_function": SAFETY_FUNCTION,
        "property": SPECIFIC_HEAT,
        "confidence": 0.1,
        "rationale": "low-confidence extraction",
    }
    validated, record = validate_relation(raw, _sentence("stub"), _known(), None, THRESHOLD)

    assert validated is None
    assert record.disposition == "skipped"


# --- co-mention without a stated dependency yields no edge -----------------


def test_co_mention_sentence_with_no_stated_dependency_yields_no_relation() -> None:
    """Scenario: "Co-mention without a stated dependency produces no edge"
    -- exercised at the extract_relations layer (already-landed,
    genre-agnostic code): a sentence naming both a safety function and a
    property, with the stub Completer correctly declining to propose any
    relation (mirroring how a real Flash call would respond to a sentence
    stating no dependency), yields nothing to validate."""
    stub = StubCompleter(json.dumps({"relations": []}))
    sentence = _sentence(
        "Heat removal and specific heat are both discussed in this chapter.",
        linked_mentions=[
            LinkedMention(
                surface_form="heat removal", target_iri=SAFETY_FUNCTION, target_kind="class"
            ),
            LinkedMention(
                surface_form="specific heat", target_iri=SPECIFIC_HEAT, target_kind="class"
            ),
        ],
    )

    relations, ok = extract_relations(sentence, "cached-kg-schema-prefix", stub)

    assert ok is True
    assert relations == []


# --- extract_report(..., genre="safety") end-to-end trace ------------------


def test_extract_report_safety_genre_writes_to_the_safety_relations_trace(tmp_path) -> None:
    """extract_report(..., genre="safety") writes its trace to
    config.safety_relations_path(report) (the Wave-1 config plumbing
    already provides this path), mirroring write_relations_jsonl's
    contract for the chemistry genre."""
    config = Config(corpus_dir=tmp_path)
    segments_path = config.segments_path(REPORT)
    segments_path.parent.mkdir(parents=True, exist_ok=True)
    sentence_text = "Heat capacity is needed for natural circulation cooling of the core."
    with segments_path.open("w", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "report": REPORT,
                    "index": 0,
                    "text": sentence_text,
                    "char_start": 0,
                    "char_end": len(sentence_text),
                }
            )
            + "\n"
        )
    mentions_path = config.mentions_path(REPORT)
    mentions_path.parent.mkdir(parents=True, exist_ok=True)
    with mentions_path.open("w", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "report": REPORT,
                    "seg_index": 0,
                    "char_start": 0,
                    "char_end": len(sentence_text),
                    "surface_form": "heat capacity",
                    "status": "linked",
                    "target_iri": SAFETY_FUNCTION,
                    "target_kind": "class",
                    "layer": 2,
                    "score": None,
                }
            )
            + "\n"
        )

    raw_relation = {
        "kind": "served_by_property",
        "safety_function": SAFETY_FUNCTION,
        "property": SPECIFIC_HEAT,
        "confidence": 0.9,
        "rationale": "heat capacity is cited as needed for natural circulation cooling",
    }
    stub = StubCompleter(json.dumps({"relations": [raw_relation]}))

    extract_report(
        REPORT, config, "cached-kg-schema-prefix", stub, _known(), None, genre="safety"
    )

    trace_path = config.safety_relations_path(REPORT)
    assert trace_path.exists()
    lines = [line for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= 1
    records = [json.loads(line) for line in lines]
    assert any(r["disposition"] == "written" for r in records)
