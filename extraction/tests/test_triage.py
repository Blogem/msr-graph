"""Candidate-triage unit tests (openspec/changes/mine-ontology-candidates,
spec candidate-triage, task 8.3).

Hermetic: every test uses a stub :class:`~msr_extraction.disambiguation.Completer`
implementation returning a fixed, canned response -- never a live model
(design.md D3/D10).

ASSUMPTION (pass-1, flagged in the tester handoff report for
reconciliation at merge): ``triage.py`` does not exist yet on this
isolated pass-1 branch. Every test below is written against the agreed
module-interface contract, not against any implementation, and is
expected to fail with a collection error until the coder's ``triage.py``
lands.
"""

from __future__ import annotations

import json

from msr_extraction import proposals
from msr_extraction.mining_types import (
    Candidate,
    Evidence,
    KIND_CLASS,
    KIND_INSTANCE,
    KIND_PROPERTY,
    VALID_KINDS,
    term_slug,
)
from msr_extraction.triage import classify, signal_kind, triage_candidate

REPORT = "FIX-0001"
DOC_IRI = "https://w3id.org/msr-kg/data#FIX-0001"
PROMPT_PREFIX = "cached KG-schema prompt prefix"


class StubCompleter:
    """A stub Completer returning ``json.dumps(payload)`` -- no network call."""

    def __init__(self, payload) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return json.dumps(self.payload)


class RawTextCompleter:
    """Returns a fixed, possibly-malformed raw string -- for shape-check tests."""

    def __init__(self, text: str) -> None:
        self.text = text

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        return self.text


def _candidate(term: str, sentence: str, *, source: str = "lexical") -> Candidate:
    evidence = (
        Evidence(
            report=REPORT,
            document_iri=DOC_IRI,
            sentence_text=sentence,
            start_offset=0,
            end_offset=len(sentence),
        ),
    )
    return Candidate(term=term, source=source, evidence=evidence, doc_frequency=100)


# --- Context-signal pre-classifier ---------------------------------------


def test_signal_kind_value_and_unit_proposes_property() -> None:
    """Scenario: "A value-plus-unit term triages as a property"."""
    candidate = _candidate("solubility", "The solubility of PuF3 was 280 mole % at 600C.")
    assert signal_kind(candidate) == KIND_PROPERTY


def test_signal_kind_moderator_context_proposes_class() -> None:
    """Scenario: "A moderator-context term triages as a class" -- the
    spec's own example text is "graphite-moderated"."""
    candidate = _candidate("graphite", "The core is graphite-moderated by design.")
    assert signal_kind(candidate) == KIND_CLASS


def test_signal_kind_miss_sourced_candidate_proposes_instance() -> None:
    """A compound-formula surface (miss-sourced candidate) proposes
    kind=instance (design.md D3)."""
    candidate = _candidate("lif-thf4-uf4", "A new compound was observed forming a stable salt.", source="miss")
    assert signal_kind(candidate) == KIND_INSTANCE


# --- Flash classifier confirmation (stubbed) -----------------------------


def test_triage_candidate_routes_graphite_shaped_term_to_class() -> None:
    """Scenario: "Tests use a stubbed classifier" -- a graphite-shaped
    candidate routes to kind=class."""
    candidate = _candidate("graphite", "The core is graphite-moderated by design.")
    stub = StubCompleter(
        {"kind": "class", "broader_class": "https://w3id.org/msr-kg/ontology#Moderator"}
    )

    result = triage_candidate(candidate, PROMPT_PREFIX, stub)

    assert result is not None
    assert result.kind == KIND_CLASS
    assert result.kind in VALID_KINDS
    assert result.placement.broader_class == "https://w3id.org/msr-kg/ontology#Moderator"


def test_triage_candidate_routes_solubility_shaped_term_to_property_with_unit_unset() -> None:
    """Scenario basis: a solubility-shaped candidate routes to
    kind=property with the unit left unset (design.md D6 -- the
    classifier is prompted to leave an ambiguous unit unset rather than
    guess, so the payload here carries no canonical_unit/quantity_kind
    key at all)."""
    candidate = _candidate("solubility", "The solubility of PuF3 was 280 mole % at 600C.")
    stub = StubCompleter({"kind": "property"})

    result = triage_candidate(candidate, PROMPT_PREFIX, stub)

    assert result is not None
    assert result.kind == KIND_PROPERTY
    assert result.placement.canonical_unit is None


def test_triage_candidate_drops_on_malformed_json() -> None:
    """Scenario: "Malformed classifier output drops the candidate"."""
    candidate = _candidate("solubility", "The solubility of PuF3 was 280 mole % at 600C.")
    stub = RawTextCompleter("this is not json at all")

    assert triage_candidate(candidate, PROMPT_PREFIX, stub) is None


def test_triage_candidate_drops_on_non_object_json() -> None:
    """A syntactically valid but non-object JSON payload also fails the
    app-side shape check and drops the candidate."""
    candidate = _candidate("solubility", "The solubility of PuF3 was 280 mole % at 600C.")
    stub = RawTextCompleter('["kind", "property"]')

    assert triage_candidate(candidate, PROMPT_PREFIX, stub) is None


def test_triage_candidate_drops_on_missing_kind_key() -> None:
    """A well-formed JSON object that fails the shape check (no ``kind``
    key at all) also drops the candidate rather than emitting a malformed
    proposal."""
    candidate = _candidate("solubility", "The solubility of PuF3 was 280 mole % at 600C.")
    stub = StubCompleter({"unexpected": "shape"})

    assert triage_candidate(candidate, PROMPT_PREFIX, stub) is None


def test_classify_forwards_the_prompt_prefix_unchanged() -> None:
    """``classify`` forwards ``prompt_prefix`` as the system prompt
    unchanged -- the cached KG-schema prefix must never be mutated
    per-call (design.md D3)."""
    candidate = _candidate("graphite", "The core is graphite-moderated by design.")
    stub = StubCompleter({"kind": "class"})

    result = classify(candidate, KIND_CLASS, PROMPT_PREFIX, stub)

    assert result is not None
    assert result.kind == KIND_CLASS
    assert stub.calls[0][0] == PROMPT_PREFIX


# --- Cross-module: emitted proposal validates against the mini-schema ---


def test_property_proposal_bundle_contains_governance_predicates() -> None:
    """Covers 8.3's cross-module assertion: the property bundle built
    from a triaged "solubility" candidate carries the ChangeProposal
    governance predicates in its staging triples (change-proposal-schema
    spec: kind, pending reviewStatus, hasProposalGraph, hasEvidence)."""
    candidate = _candidate("solubility", "The solubility of PuF3 was 280 mole % at 600C.")
    stub = StubCompleter({"kind": "property"})
    triaged = triage_candidate(candidate, PROMPT_PREFIX, stub)
    assert triaged is not None

    # An empty allowlist is deliberate: canonical_unit is unset for
    # solubility, so the QUDT guard (tested separately in
    # test_proposals.py) must not fire regardless of allowlist contents.
    allowlist = proposals.QudtAllowlist(units=frozenset(), quantity_kinds=frozenset())
    bundle = proposals.build_proposal_bundle(triaged, allowlist, "2026-07-20T00:00:00+00:00")

    assert bundle is not None
    assert bundle.proposal_iri == f"msrd:proposal-property-{term_slug('solubility')}"
    assert "msr:ChangeProposal" in bundle.staging_triples
    assert 'msr:reviewStatus "pending"' in bundle.staging_triples
    assert "msr:hasProposalGraph" in bundle.staging_triples
    assert "msr:hasEvidence" in bundle.staging_triples
