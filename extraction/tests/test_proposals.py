"""Proposal-emission unit tests (openspec/changes/mine-ontology-candidates,
specs change-proposal-schema + proposal-staging, tasks 8.3-8.5, 8.7).

Hermetic: a fake SPARQL client records every ``.update(...)`` call; no
network, no live model.

ASSUMPTION (pass-1, flagged in the tester handoff report for
reconciliation at merge): ``proposals.py`` does not exist yet on this
isolated pass-1 branch. Every test below is written against the agreed
module-interface contract, not against any implementation, and is
expected to fail with a collection error until the coder's
``proposals.py`` lands.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from msr_extraction.mining_types import (
    Candidate,
    Evidence,
    KIND_CLASS,
    KIND_PROPERTY,
    Placement,
    TriagedCandidate,
    term_slug,
)
from msr_extraction.proposals import (
    QudtAllowlist,
    build_proposal_bundle,
    load_qudt_allowlist,
    write_proposal,
)

REPORT = "FIX-0001"
DOC_IRI = "https://w3id.org/msr-kg/data#FIX-0001"
RUN_TS = "2026-07-20T00:00:00+00:00"

IN_ALLOWLIST_UNIT = "http://qudt.org/vocab/unit/GM-PER-CentiM3"
OUT_OF_ALLOWLIST_UNIT = "http://qudt.org/vocab/unit/MOL-PER-MOL"
IN_ALLOWLIST_QK = "http://qudt.org/vocab/quantitykind/Density"
OUT_OF_ALLOWLIST_QK = "http://qudt.org/vocab/quantitykind/MoleFraction"

FIXTURE_QUDT_PATH = Path(__file__).parent / "fixtures" / "mining" / "qudt-units.json"


class FakeSparqlClient:
    """Records every ``.update(sparql)`` string; never touches the network."""

    def __init__(self) -> None:
        self.updates: list[str] = []

    def update(self, sparql_update: str) -> None:
        self.updates.append(sparql_update)


def _evidence() -> tuple[Evidence, ...]:
    return (
        Evidence(
            report=REPORT,
            document_iri=DOC_IRI,
            sentence_text="The solubility of PuF3 was 280 mole % at 600C.",
            start_offset=4,
            end_offset=14,
        ),
    )


def _triaged(term: str, kind: str, *, canonical_unit=None, quantity_kind=None) -> TriagedCandidate:
    candidate = Candidate(term=term, source="lexical", evidence=_evidence(), doc_frequency=280)
    placement = Placement(canonical_unit=canonical_unit, quantity_kind=quantity_kind)
    return TriagedCandidate(candidate=candidate, kind=kind, placement=placement)


def _allowlist() -> QudtAllowlist:
    return QudtAllowlist(
        units=frozenset({IN_ALLOWLIST_UNIT}),
        quantity_kinds=frozenset({IN_ALLOWLIST_QK}),
    )


# --- QUDT allowlist loader -------------------------------------------------


def test_load_qudt_allowlist_reads_the_vendored_fixture_shape() -> None:
    allowlist = load_qudt_allowlist(FIXTURE_QUDT_PATH)
    assert IN_ALLOWLIST_UNIT in allowlist.units
    assert IN_ALLOWLIST_QK in allowlist.quantity_kinds
    assert OUT_OF_ALLOWLIST_UNIT not in allowlist.units
    assert OUT_OF_ALLOWLIST_QK not in allowlist.quantity_kinds


# --- 8.4: QUDT-allowlist guard on build_proposal_bundle -------------------


@pytest.mark.parametrize(
    "canonical_unit, quantity_kind, expect_rejected",
    [
        pytest.param(OUT_OF_ALLOWLIST_UNIT, None, True, id="out-of-allowlist-unit-rejected"),
        pytest.param(IN_ALLOWLIST_UNIT, None, False, id="in-allowlist-unit-kept"),
        pytest.param(None, None, False, id="unit-and-qk-unset-guard-does-not-fire"),
        pytest.param(None, OUT_OF_ALLOWLIST_QK, True, id="out-of-allowlist-qk-rejected"),
        pytest.param(None, IN_ALLOWLIST_QK, False, id="in-allowlist-qk-kept"),
    ],
)
def test_build_proposal_bundle_qudt_allowlist_guard(canonical_unit, quantity_kind, expect_rejected) -> None:
    triaged = _triaged(
        "solubility", KIND_PROPERTY, canonical_unit=canonical_unit, quantity_kind=quantity_kind
    )

    bundle = build_proposal_bundle(triaged, _allowlist(), RUN_TS)

    if expect_rejected:
        assert bundle is None
    else:
        assert bundle is not None


# --- 8.5: deterministic IRIs, staging/proposal-graph split, idempotency --


def test_build_proposal_bundle_mints_deterministic_iris() -> None:
    """Scenario: "A candidate mints deterministic proposal IRIs"."""
    triaged = _triaged("solubility", KIND_PROPERTY)
    bundle = build_proposal_bundle(triaged, _allowlist(), RUN_TS)

    assert bundle is not None
    assert bundle.proposal_iri == f"msrd:proposal-property-{term_slug('solubility')}"
    assert bundle.proposal_graph == f"urn:msr:proposal/property-{term_slug('solubility')}"


def test_write_proposal_splits_staging_and_proposal_graph_updates() -> None:
    """Scenario: "Proposal split across staging and proposal graph" -- one
    INSERT DATA names GRAPH <urn:msr:staging> (the ChangeProposal
    resource), a second names GRAPH <urn:msr:proposal/{id}> (the proposed
    axioms)."""
    triaged = _triaged("solubility", KIND_PROPERTY)
    bundle = build_proposal_bundle(triaged, _allowlist(), RUN_TS)
    assert bundle is not None

    client = FakeSparqlClient()
    write_proposal(bundle, client)

    assert len(client.updates) == 2
    staging_update = next(u for u in client.updates if "GRAPH <urn:msr:staging>" in u)
    proposal_update = next(
        u for u in client.updates if "GRAPH <urn:msr:proposal/property-solubility>" in u
    )

    assert "msrd:proposal-property-solubility" in staging_update
    assert "msr:ChangeProposal" in staging_update
    # The proposal graph carries the actual proposed axioms, not a second
    # copy of the governance ChangeProposal resource.
    assert "a msr:ChangeProposal" not in proposal_update


def test_write_proposal_never_writes_blank_nodes() -> None:
    """Scenario: "A candidate mints deterministic proposal IRIs" -- "no
    blank nodes are written"."""
    triaged = _triaged("solubility", KIND_PROPERTY)
    bundle = build_proposal_bundle(triaged, _allowlist(), RUN_TS)
    assert bundle is not None

    client = FakeSparqlClient()
    write_proposal(bundle, client)

    for update in client.updates:
        assert "[]" not in update
        assert "_:" not in update


def test_write_proposal_is_idempotent_across_identical_reruns() -> None:
    """Scenario: "Re-run adds no duplicate proposals" -- rebuilding and
    rewriting the same triaged candidate at the same run_ts produces
    byte-identical update strings."""
    triaged = _triaged("solubility", KIND_PROPERTY)

    client_a = FakeSparqlClient()
    bundle_a = build_proposal_bundle(triaged, _allowlist(), RUN_TS)
    assert bundle_a is not None
    write_proposal(bundle_a, client_a)

    client_b = FakeSparqlClient()
    bundle_b = build_proposal_bundle(triaged, _allowlist(), RUN_TS)
    assert bundle_b is not None
    write_proposal(bundle_b, client_b)

    assert client_a.updates == client_b.updates


def test_write_proposal_is_idempotent_across_different_run_timestamps() -> None:
    """Scenario: cross-run idempotency (task 8.5 completion) -- building
    and writing the same triaged candidate at two DIFFERENT run_ts values
    (as would happen across two separate `mine` invocations) produces
    byte-identical urn:msr:staging / urn:msr:proposal/{id} INSERT DATA
    updates. run_ts is accepted by build_proposal_bundle but must not leak
    into the (idempotent) bundle content -- the per-run
    prov:wasGeneratedBy attribution lives in urn:msr:provenance, written
    by the CLI via mine_provenance, not embedded here. In particular the
    staging block must never carry an urn:msr:run:mine/ node."""
    triaged = _triaged("solubility", KIND_PROPERTY)

    client_t1 = FakeSparqlClient()
    bundle_t1 = build_proposal_bundle(triaged, _allowlist(), "T1")
    assert bundle_t1 is not None
    write_proposal(bundle_t1, client_t1)

    client_t2 = FakeSparqlClient()
    bundle_t2 = build_proposal_bundle(triaged, _allowlist(), "T2")
    assert bundle_t2 is not None
    write_proposal(bundle_t2, client_t2)

    assert client_t1.updates == client_t2.updates

    staging_update = next(u for u in client_t1.updates if "GRAPH <urn:msr:staging>" in u)
    assert "urn:msr:run:mine/" not in staging_update
    for update in client_t1.updates:
        assert "T1" not in update
        assert "T2" not in update


def test_write_proposal_appends_extra_proposal_triples() -> None:
    """The ``extra_proposal_triples`` hook (e.g. the graphite bundle's
    Moderator-typed individual riding with the class proposal, design.md
    D7) is appended into the proposal graph's update, not the staging
    update."""
    triaged = _triaged("graphite", KIND_CLASS)
    bundle = build_proposal_bundle(triaged, _allowlist(), RUN_TS)
    assert bundle is not None

    client = FakeSparqlClient()
    extra = "msrd:graphite a msr:Moderator ."
    write_proposal(bundle, client, extra_proposal_triples=extra)

    proposal_update = next(
        u for u in client.updates if "GRAPH <urn:msr:proposal/class-graphite>" in u
    )
    staging_update = next(u for u in client.updates if "GRAPH <urn:msr:staging>" in u)
    assert extra in proposal_update
    assert extra not in staging_update


# --- 8.7: proposals are structurally kept out of the core dataset -------


def test_write_proposal_never_targets_core_graphs() -> None:
    """Structural pin: everything write_proposal sends targets
    urn:msr:staging / urn:msr:proposal/... and NEVER urn:msr:data or the
    other two core graphs. The live core-reader-invisibility check (a
    mined proposal is unreachable via the core-dataset client) is a
    separate, guarded integration test (task 8.8) -- not this unit test."""
    triaged = _triaged("solubility", KIND_PROPERTY)
    bundle = build_proposal_bundle(triaged, _allowlist(), RUN_TS)
    assert bundle is not None

    client = FakeSparqlClient()
    write_proposal(bundle, client)

    for update in client.updates:
        assert "GRAPH <urn:msr:data>" not in update
        assert "GRAPH <urn:msr:ontology>" not in update
        assert "GRAPH <urn:msr:vocab>" not in update
