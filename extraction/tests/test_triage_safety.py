"""Genre-aware safety-candidate triage tests (openspec/changes/
ingest-iaea-safety, spec ``safety-ontology-evolution``, task 8.4).

Hermetic: every test uses a stub :class:`~msr_extraction.disambiguation.Completer`
implementation returning a fixed, canned response -- never a live model
(design.md D3/D10, mirroring ``test_triage.py``).

Per design.md D3/tasks.md 3.2, the genre-aware change is scoped entirely
to ``triage.py``'s prompt/classifier confirmation step -- the fixed kind
set (``property``/``class``/``instance``/``relation``), the
``change-proposal-schema`` mini-schema, ``proposal-staging``, and
``approval-typed-routing`` are explicitly UNCHANGED. This file therefore
reuses the existing, already-landed ``proposals.build_proposal_bundle``
(exercised the same way ``test_triage.py``'s
"cross-module: emitted proposal validates against the mini-schema" test
already does) as the "validate against the chunk-8 mini-schema" step
called for by task 8.4, rather than inventing a new validator.

ASSUMPTION (pass-1, flagged for reconciliation at merge):
``triage.triage_candidate``/``triage.classify`` do not yet accept a
``genre`` keyword on this isolated pass-1 branch (task 3.2) -- every test
below is written against that pinned contract, not against any
implementation, and is expected to fail (TypeError on the unrecognized
kwarg) until the coder's change lands. The stub Flash payloads below use
``broaderClass``/``domain``/``range`` values naming the safety branch's
five classes (``msr:SafetyFunction``, ``msr:Requirement``, ...) per
design.md D3/tasks.md 3.3 -- these are the classifier's OWN proposed
placement (an LLM claim), not anything this module hardcodes.
"""

from __future__ import annotations

import json

from msr_extraction import proposals
from msr_extraction.mining_types import (
    Candidate,
    Evidence,
    KIND_CLASS,
    KIND_RELATION,
    term_slug,
)
from msr_extraction.triage import triage_candidate

REPORT = "SAFETY-FIX-0001"
DOC_IRI = "https://w3id.org/msr-kg/data#SAFETY-FIX-0001"
PROMPT_PREFIX = "cached KG-schema prompt prefix"
RUN_TS = "2027-01-01T00:00:00+00:00"


class StubCompleter:
    """A stub Completer returning ``json.dumps(payload)`` -- no network call."""

    def __init__(self, payload) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return json.dumps(self.payload)


def _candidate(term: str, sentence: str) -> Candidate:
    evidence = (
        Evidence(
            report=REPORT,
            document_iri=DOC_IRI,
            sentence_text=sentence,
            start_offset=0,
            end_offset=len(sentence),
        ),
    )
    return Candidate(term=term, source="lexical", evidence=evidence, doc_frequency=42)


_ALLOWLIST = proposals.QudtAllowlist(units=frozenset(), quantity_kinds=frozenset())


# --- A safety concept triages as a class proposal with a Safety placement --


def test_heat_removal_triages_as_class_with_safety_broader_class_placement() -> None:
    """Scenario: "A safety concept is triaged as a class proposal with a
    Safety placement" -- "heat removal" routes to kind=class with a
    proposed Safety broader-class placement, not rejected as boilerplate."""
    candidate = _candidate(
        "heat removal",
        "Effective heat removal is essential for reactor safety.",
    )
    stub = StubCompleter({"kind": "class", "broaderClass": "msr:SafetyFunction"})

    result = triage_candidate(candidate, PROMPT_PREFIX, stub, genre="safety")

    assert result is not None
    assert result.kind == KIND_CLASS
    assert result.placement.broader_class == "msr:SafetyFunction"


def test_safety_class_proposal_validates_against_the_mini_schema() -> None:
    """Cross-module (mirrors test_triage.py's equivalent chemistry test):
    the triaged safety-class candidate's proposal bundle carries the
    ChangeProposal governance predicates (kind, pending reviewStatus,
    hasProposalGraph, hasEvidence) AND the proposed owl:Class axiom for
    the Safety broader-class placement, in urn:msr:proposal/{id}
    (invisible to the core-dataset client until approved) -- the unchanged
    change-proposal-schema mini-schema."""
    candidate = _candidate(
        "confinement of radioactive material",
        "The reactor design ensures confinement of radioactive material at all times.",
    )
    stub = StubCompleter({"kind": "class", "broaderClass": "msr:SafetyFunction"})
    triaged = triage_candidate(candidate, PROMPT_PREFIX, stub, genre="safety")
    assert triaged is not None

    bundle = proposals.build_proposal_bundle(triaged, _ALLOWLIST, RUN_TS)

    assert bundle is not None
    slug = term_slug("confinement of radioactive material")
    assert bundle.proposal_iri == f"msrd:proposal-class-{slug}"
    assert "msr:ChangeProposal" in bundle.staging_triples
    assert 'msr:kind "class"' in bundle.staging_triples
    assert 'msr:reviewStatus "pending"' in bundle.staging_triples
    assert "msr:hasProposalGraph" in bundle.staging_triples
    assert "msr:hasEvidence" in bundle.staging_triples
    assert "msr:SafetyFunction a owl:Class" in bundle.proposal_graph_triples


def test_safety_class_proposal_sits_in_its_own_dedicated_graph_invisible_until_approved() -> None:
    candidate = _candidate(
        "control of reactivity",
        "Adequate control of reactivity is maintained throughout normal operation.",
    )
    stub = StubCompleter({"kind": "class", "broaderClass": "msr:SafetyFunction"})
    triaged = triage_candidate(candidate, PROMPT_PREFIX, stub, genre="safety")
    assert triaged is not None

    bundle = proposals.build_proposal_bundle(triaged, _ALLOWLIST, RUN_TS)

    assert bundle is not None
    slug = term_slug("control of reactivity")
    assert bundle.proposal_graph == f"urn:msr:proposal/class-{slug}"


# --- A linking edge triages as a relation proposal -------------------------


def test_served_by_property_concept_triages_as_relation_with_domain_and_range() -> None:
    """Scenario: "A linking edge is triaged as a relation proposal" -- a
    mined linking concept (safety-function-to-property dependency) routes
    to kind=relation with a proposed domain/range, not kind=class."""
    candidate = _candidate(
        "served by property",
        "Heat removal relies on the salt's heat capacity and viscosity.",
    )
    stub = StubCompleter(
        {
            "kind": "relation",
            "domain": "msr:SafetyFunction",
            "range": "msr:PhysicalProperty",
        }
    )

    result = triage_candidate(candidate, PROMPT_PREFIX, stub, genre="safety")

    assert result is not None
    assert result.kind == KIND_RELATION
    assert result.placement.domain == "msr:SafetyFunction"
    assert result.placement.range_ == "msr:PhysicalProperty"


def test_relation_proposal_validates_against_the_mini_schema() -> None:
    """The relation-kind proposal's object-property triples (unchanged
    change-proposal-schema shape) carry the proposed domain/range in the
    dedicated proposal graph, ready to route to urn:msr:ontology by triple
    type on approval (approval-typed-routing, unchanged)."""
    candidate = _candidate(
        "addresses function",
        "This coolant-selection requirement serves the heat-removal function.",
    )
    stub = StubCompleter(
        {
            "kind": "relation",
            "domain": "msr:Requirement",
            "range": "msr:SafetyFunction",
        }
    )
    triaged = triage_candidate(candidate, PROMPT_PREFIX, stub, genre="safety")
    assert triaged is not None

    bundle = proposals.build_proposal_bundle(triaged, _ALLOWLIST, RUN_TS)

    assert bundle is not None
    assert 'msr:kind "relation"' in bundle.staging_triples
    assert "a owl:ObjectProperty" in bundle.proposal_graph_triples
    assert "rdfs:domain msr:Requirement" in bundle.proposal_graph_triples
    assert "rdfs:range msr:SafetyFunction" in bundle.proposal_graph_triples


# --- The genre prompt does not reject domain-shaped safety phrases ---------


def test_domain_shaped_safety_phrase_is_not_rejected_as_boilerplate() -> None:
    """Scenario basis: "The genre prompt SHALL keep the classifier from
    rejecting domain-shaped safety phrases as boilerplate" -- a stub
    standing in for a genre-aware Flash confirmation returns a routable
    kind (never the explicit reject verdict) for a safety-shaped
    candidate."""
    candidate = _candidate(
        "defence in depth",
        "The plant relies on defence in depth as a safety principle.",
    )
    stub = StubCompleter({"kind": "class", "broaderClass": "msr:DefenceInDepth"})

    result = triage_candidate(candidate, PROMPT_PREFIX, stub, genre="safety")

    assert result is not None
    assert result.kind == KIND_CLASS
