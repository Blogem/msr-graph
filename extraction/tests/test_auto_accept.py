"""Instance auto-accept unit tests (openspec/changes/mine-ontology-candidates,
spec instance-auto-accept, task 8.6).

Hermetic: a fake SPARQL client records every ``.update(...)`` call; no
network. Exercises the auto-accept-vs-rides-with-proposal decision and the
provenance-completeness contract (``prov:wasGeneratedBy msrd:activity-mine``
+ ``prov:wasDerivedFrom`` the source Document, design.md D8/D9).

ASSUMPTION (pass-1, flagged in the tester handoff report for
reconciliation at merge): ``auto_accept.py`` does not exist yet on this
isolated pass-1 branch. Every test below is written against the agreed
module-interface contract, not against any implementation, and is
expected to fail with a collection error until the coder's
``auto_accept.py`` lands. The biggest interface guess: ``resolves_in_core``
is assumed to check ``triaged.placement.broader_class`` against
``known_iris`` -- the module interface only names
``resolves_in_core(triaged, known_iris, *, core_types=None) -> bool``, so
which field of ``TriagedCandidate`` carries the type being checked is not
pinned by the contract; flagged for reconciliation at merge.
"""

from __future__ import annotations

from msr_extraction.auto_accept import (
    Individual,
    data_insert_data,
    individual_triples,
    resolves_in_core,
    write_auto_accepted,
)
from msr_extraction.graph_reader import MSR, MSRD
from msr_extraction.mine_provenance import ACTIVITY_IRI, activity_insert_data, stable_activity_insert_data
from msr_extraction.mining_types import Candidate, KIND_INSTANCE, Placement, TriagedCandidate

REPORT = "FIX-0001"
DOC_IRI = f"{MSRD}{REPORT}"
RUN_TS_A = "2026-07-20T00:00:00+00:00"
RUN_TS_B = "2026-07-21T00:00:00+00:00"


class FakeSparqlClient:
    """Records every ``.update(sparql)`` string; never touches the network."""

    def __init__(self) -> None:
        self.updates: list[str] = []

    def update(self, sparql_update: str) -> None:
        self.updates.append(sparql_update)


def _individual(iri: str = "msrd:salt-fix-0001") -> Individual:
    return Individual(iri=iri, type_iri=f"{MSR}MoltenSalt", document_iri=DOC_IRI)


# --- individual_triples: provenance-complete, no msr:citedIn -------------


def test_individual_triples_are_provenance_complete_and_flagged() -> None:
    """Scenario: "A new salt under MoltenSalt is written directly to
    data" -- carries prov:wasGeneratedBy msrd:activity-mine +
    prov:wasDerivedFrom its source Document, flagged msr:autoAccepted
    true, and no msr:citedIn (deferred to chunk-7 citation extraction)."""
    triples = individual_triples(_individual())

    assert f"prov:wasGeneratedBy {ACTIVITY_IRI}" in triples
    assert f"prov:wasDerivedFrom <{DOC_IRI}>" in triples
    assert "msr:autoAccepted" in triples
    assert "true" in triples.lower()
    assert "msr:citedIn" not in triples


# --- resolves_in_core: auto-accept vs. rides-with-proposal ---------------


def test_resolves_in_core_true_for_existing_catalog_class() -> None:
    """Scenario basis: an instance typed by an existing core class
    resolves within core -> auto-accept."""
    candidate = Candidate(term="new-salt", source="miss", evidence=(), doc_frequency=10)
    triaged = TriagedCandidate(
        candidate=candidate,
        kind=KIND_INSTANCE,
        placement=Placement(broader_class=f"{MSR}MoltenSalt"),
    )
    known_iris = {f"{MSR}MoltenSalt"}

    assert resolves_in_core(triaged, known_iris) is True


def test_resolves_in_core_false_for_proposed_class() -> None:
    """Scenario: "graphite rides the Moderator proposal" -- an instance
    depending on a *proposed* class (not in the known-IRI set) does not
    resolve within core."""
    candidate = Candidate(term="graphite", source="lexical", evidence=(), doc_frequency=10)
    triaged = TriagedCandidate(
        candidate=candidate,
        kind=KIND_INSTANCE,
        placement=Placement(broader_class=f"{MSR}Moderator"),
    )
    known_iris = {f"{MSR}MoltenSalt"}  # Moderator is NOT known -- it's proposed

    assert resolves_in_core(triaged, known_iris) is False


# --- data_insert_data / write_auto_accepted -------------------------------


def test_data_insert_data_targets_the_data_graph() -> None:
    update = data_insert_data([_individual()])
    assert "GRAPH <urn:msr:data>" in update
    assert "msrd:salt-fix-0001" in update


def test_write_auto_accepted_sends_data_and_provenance_updates() -> None:
    """Scenario: "Per-run activity and lineage land in the provenance
    graph" -- write_auto_accepted sends a GRAPH <urn:msr:data> INSERT DATA
    plus a GRAPH <urn:msr:provenance> generation-edge INSERT DATA (via
    mine_provenance)."""
    client = FakeSparqlClient()
    write_auto_accepted([_individual()], client, RUN_TS_A)

    assert len(client.updates) >= 2
    assert any("GRAPH <urn:msr:data>" in u for u in client.updates)
    provenance_updates = [u for u in client.updates if "GRAPH <urn:msr:provenance>" in u]
    assert len(provenance_updates) >= 1
    assert any("prov:wasGeneratedBy" in u for u in provenance_updates)


def test_write_auto_accepted_data_write_is_idempotent_across_run_ts() -> None:
    """Scenario: "The provenance graph is append-only across runs" -- two
    runs at distinct wall-clock timestamps: the urn:msr:data INSERT DATA
    is byte-identical (deterministic IRIs, no blank nodes), while the
    urn:msr:provenance generation-edge update differs by run node."""
    client_a = FakeSparqlClient()
    write_auto_accepted([_individual()], client_a, RUN_TS_A)

    client_b = FakeSparqlClient()
    write_auto_accepted([_individual()], client_b, RUN_TS_B)

    data_update_a = next(u for u in client_a.updates if "GRAPH <urn:msr:data>" in u)
    data_update_b = next(u for u in client_b.updates if "GRAPH <urn:msr:data>" in u)
    assert data_update_a == data_update_b

    prov_update_a = next(u for u in client_a.updates if "GRAPH <urn:msr:provenance>" in u)
    prov_update_b = next(u for u in client_b.updates if "GRAPH <urn:msr:provenance>" in u)
    assert prov_update_a != prov_update_b
    assert f"run:mine/{RUN_TS_A}" in prov_update_a
    assert f"run:mine/{RUN_TS_B}" in prov_update_b


def test_write_auto_accepted_is_a_noop_for_empty_individuals() -> None:
    """Mirrors the mentions.py/documents.py convention: no writes at all
    when there is nothing to write."""
    client = FakeSparqlClient()
    write_auto_accepted([], client, RUN_TS_A)
    assert client.updates == []


# --- stable vs. per-run activity typing (also exercised directly in
#     test_mine_provenance.py; repeated here per the 8.6 scenario list) --


def test_stable_activity_has_no_timestamp_while_run_activity_does() -> None:
    """Scenario: "The stable mine activity is typed idempotently in the
    data graph" -- stable_activity_insert_data() carries no timestamp
    literal, while activity_insert_data(ts) does."""
    stable = stable_activity_insert_data()
    run = activity_insert_data(RUN_TS_A)

    assert "prov:startedAtTime" not in stable
    assert "prov:endedAtTime" not in stable
    assert "prov:startedAtTime" in run
    assert "prov:endedAtTime" in run
