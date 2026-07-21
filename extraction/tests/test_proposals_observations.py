"""Proposal-writer observation-emission unit tests (openspec/changes/
proposal-observation-provenance, specs change-proposal-schema +
proposal-observation-provenance, task 7.2).

Hermetic: a fake SPARQL client records every ``.update(...)`` call; no
network, no live model. Mirrors ``test_proposals.py``'s existing
``FakeSparqlClient``/``_triaged``/``_allowlist`` helper style.

ASSUMPTION (pass-1, flagged for reconciliation at merge): this pass runs
BEFORE the coder's ``proposals.py`` change for task 3.1/3.2 lands (stop
writing ``msr:docFrequency``; emit ``msr:hasObservation`` observation
nodes), so every test below is written against the contract in the shared
task-contract prompt / ``change-proposal-schema`` + ``proposal-observation-
provenance`` specs, not against any implementation:

- Deterministic observation IRI: ``msrd:obs-{kind}-{slug}-{doc-slug}-{run-
  slug}`` -- exact slugging of the document/run segments is left
  unspecified by the specs, so this suite only pins the fixed
  ``msrd:obs-{kind}-{slug}-`` PREFIX (never the full suffix), plus the
  cross-cutting identity/idempotency invariants that ARE spec-mandated:
  same (candidate, run_ts) -> byte-identical bundle; different run_ts ->
  different observation IRIs/timestamps for the SAME document.
- Each observation node carries ``msr:inDocument``, ``msr:occurrenceCount``
  (``^^xsd:integer``), ``msr:inCorpus``, ``msr:observedInRun
  <urn:msr:run:mine/{run_ts}>``, and ``prov:generatedAtTime`` stamped with
  ``run_ts`` itself (the "current mine run" timestamp) as ``^^xsd:dateTime``.
- The ``msr:ChangeProposal`` staging resource references its observations
  via ``msr:hasObservation``, retains ``msr:hasEvidence``, and NO LONGER
  carries a ``msr:docFrequency`` scalar anywhere.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from msr_extraction import corpora
from msr_extraction.mining_types import (
    Candidate,
    Evidence,
    KIND_PROPERTY,
    Observation,
    Placement,
    TriagedCandidate,
)
from msr_extraction.proposals import QudtAllowlist, build_proposal_bundle, write_proposal

REPORT = "FIX-0001"
DOC_A = "https://w3id.org/msr-kg/data#FIX-0001"
DOC_B = "https://w3id.org/msr-kg/data#FIX-0002"
RUN_T1 = "2026-07-20T00:00:00+00:00"
RUN_T2 = "2026-07-21T00:00:00+00:00"

FIXTURE_QUDT_PATH = Path(__file__).parent / "fixtures" / "mining" / "qudt-units.json"


class FakeSparqlClient:
    def __init__(self) -> None:
        self.updates: list[str] = []

    def update(self, sparql_update: str) -> None:
        self.updates.append(sparql_update)


def _evidence() -> tuple[Evidence, ...]:
    return (
        Evidence(
            report=REPORT,
            document_iri=DOC_A,
            sentence_text="The solubility of PuF3 was 280 mole % at 600C.",
            start_offset=4,
            end_offset=14,
        ),
    )


def _observations() -> tuple[Observation, ...]:
    return (
        Observation(document_iri=DOC_A, corpus=corpora.CORPUS_CHEMISTRY, occurrence_count=4),
        Observation(document_iri=DOC_B, corpus=corpora.CORPUS_SAFETY, occurrence_count=2),
    )


def _triaged(observations: tuple[Observation, ...] = ()) -> TriagedCandidate:
    candidate = Candidate(
        term="solubility",
        source="lexical",
        evidence=_evidence(),
        doc_frequency=len({o.document_iri for o in observations}) if observations else 0,
        observations=observations,
    )
    placement = Placement()
    return TriagedCandidate(candidate=candidate, kind=KIND_PROPERTY, placement=placement)


def _allowlist() -> QudtAllowlist:
    return QudtAllowlist(units=frozenset(), quantity_kinds=frozenset())


def _staging_of(bundle) -> str:
    return bundle.staging_triples


# --- observation nodes are emitted, deterministic-prefixed, well-formed --


def test_build_proposal_bundle_emits_one_observation_node_per_document() -> None:
    """Scenario: "A proposal carries per-document observations" -- a
    candidate seen in 2 documents yields 2 Observation nodes, referenced
    from the ChangeProposal resource via msr:hasObservation."""
    triaged = _triaged(_observations())
    bundle = build_proposal_bundle(triaged, _allowlist(), RUN_T1)

    assert bundle is not None
    staging = _staging_of(bundle)
    assert "msr:hasObservation" in staging
    assert staging.count("msr:inDocument") == 2
    assert f"<{DOC_A}>" in staging
    assert f"<{DOC_B}>" in staging


def test_build_proposal_bundle_observation_predicates_are_complete() -> None:
    """Each observation node carries msr:inDocument, msr:occurrenceCount
    (xsd:integer), msr:inCorpus, msr:observedInRun, and
    prov:generatedAtTime."""
    triaged = _triaged(_observations())
    bundle = build_proposal_bundle(triaged, _allowlist(), RUN_T1)
    assert bundle is not None
    staging = _staging_of(bundle)

    assert "msr:occurrenceCount" in staging
    assert '"4"^^xsd:integer' in staging
    assert '"2"^^xsd:integer' in staging
    assert "msr:inCorpus" in staging
    assert corpora.CORPUS_CHEMISTRY in staging
    assert corpora.CORPUS_SAFETY in staging
    assert "msr:observedInRun" in staging
    assert "<urn:msr:run:mine/" + RUN_T1 + ">" in staging
    assert "prov:generatedAtTime" in staging
    assert f'"{RUN_T1}"^^xsd:dateTime' in staging


def test_observation_node_iris_use_the_deterministic_prefix() -> None:
    """Deterministic IRI prefix: msrd:obs-{kind}-{slug}- (exact suffix left
    to the implementation; see module docstring assumption)."""
    triaged = _triaged(_observations())
    bundle = build_proposal_bundle(triaged, _allowlist(), RUN_T1)
    assert bundle is not None
    staging = _staging_of(bundle)

    assert "msrd:obs-property-solubility-" in staging


def test_no_docfrequency_scalar_is_written_anywhere() -> None:
    """change-proposal-schema spec: "Corpus support is carried as
    observations, not a scalar" -- msr:docFrequency must never appear in the
    staging block, with or without observations attached."""
    for observations in (_observations(), ()):
        triaged = _triaged(observations)
        bundle = build_proposal_bundle(triaged, _allowlist(), RUN_T1)
        assert bundle is not None
        assert "msr:docFrequency" not in _staging_of(bundle)


def test_has_evidence_is_retained_alongside_observations() -> None:
    """task 3.2: "keep msr:hasEvidence sample sentences unchanged"."""
    triaged = _triaged(_observations())
    bundle = build_proposal_bundle(triaged, _allowlist(), RUN_T1)
    assert bundle is not None
    staging = _staging_of(bundle)
    assert "msr:hasEvidence" in staging
    assert "msr:evidenceText" in staging


def test_candidate_with_no_observations_yields_no_observation_nodes() -> None:
    """A candidate carrying an empty observations tuple (e.g. a legacy
    candidate built before this change) must not emit a hasObservation
    predicate nor any observation node -- no fabricated data."""
    triaged = _triaged(())
    bundle = build_proposal_bundle(triaged, _allowlist(), RUN_T1)
    assert bundle is not None
    staging = _staging_of(bundle)
    assert "msr:hasObservation" not in staging
    assert "msr:inDocument" not in staging


# --- append-only / idempotency across run_ts -----------------------------


def test_rebuilding_at_the_same_run_ts_is_byte_identical() -> None:
    """Idempotent: rebuilding+rewriting the identical (candidate, run_ts)
    pair twice produces byte-identical staging content -- a re-run of the
    SAME mine invocation must never duplicate or drift its own
    observations."""
    triaged = _triaged(_observations())

    bundle_a = build_proposal_bundle(triaged, _allowlist(), RUN_T1)
    bundle_b = build_proposal_bundle(triaged, _allowlist(), RUN_T1)
    assert bundle_a is not None and bundle_b is not None
    assert bundle_a.staging_triples == bundle_b.staging_triples

    client_a, client_b = FakeSparqlClient(), FakeSparqlClient()
    write_proposal(bundle_a, client_a)
    write_proposal(bundle_b, client_b)
    assert client_a.updates == client_b.updates


def test_rebuilding_at_a_different_run_ts_changes_observation_content() -> None:
    """Append-only: a LATER mining run (different run_ts) observing the
    same candidate/documents again must stamp NEW observedInRun/
    generatedAtTime values -- the staging content for the two runs must
    differ (simulating the append: writing both leaves both recorded,
    since their observation IRIs/timestamps differ), even though the
    underlying document/corpus/count data is identical."""
    triaged = _triaged(_observations())

    bundle_t1 = build_proposal_bundle(triaged, _allowlist(), RUN_T1)
    bundle_t2 = build_proposal_bundle(triaged, _allowlist(), RUN_T2)
    assert bundle_t1 is not None and bundle_t2 is not None

    assert bundle_t1.staging_triples != bundle_t2.staging_triples
    assert RUN_T1 in bundle_t1.staging_triples
    assert RUN_T2 not in bundle_t1.staging_triples
    assert RUN_T2 in bundle_t2.staging_triples
    assert RUN_T1 not in bundle_t2.staging_triples

    # the document/corpus/count facts themselves are unchanged across runs
    for staging in (bundle_t1.staging_triples, bundle_t2.staging_triples):
        assert f"<{DOC_A}>" in staging
        assert f"<{DOC_B}>" in staging
        assert '"4"^^xsd:integer' in staging
        assert '"2"^^xsd:integer' in staging


def test_write_proposal_never_writes_blank_nodes_for_observations() -> None:
    triaged = _triaged(_observations())
    bundle = build_proposal_bundle(triaged, _allowlist(), RUN_T1)
    assert bundle is not None

    client = FakeSparqlClient()
    write_proposal(bundle, client)
    for update in client.updates:
        assert "[]" not in update
        assert "_:" not in update
