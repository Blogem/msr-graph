"""Guarded observation-backfill integration test (task 7.7,
openspec/changes/proposal-observation-provenance, design.md D4/D6,
tasks.md 4.1-4.4).

Mirrors ``test_safety_integration.py``'s opt-in + repo-isolation guard
exactly (see that module's docstring for the established style, itself
mirroring ``test_extract_integration.py``): this module is skipped
entirely during normal/CI collection (no stack, no network) and only runs
once explicitly opted into via ``MSR_BACKFILL_INTEGRATION_TEST``. It ALWAYS
targets the disposable repo resolved from ``GRAPHDB_TEST_REPO`` (default
``msr-test``), never the production ``msr`` repo, and hard-refuses (skips
loudly, before any network call) if that resolution would land on the
production repo -- the same D1/D2 guard ``internal/testutil.RequireGraphDB``
enforces on the Go side and ``test_safety_integration.py`` enforces on the
Python side.

How to run it
--------------
Provision the disposable ``msr-test`` repo first (``make test-repo``), then::

    MSR_BACKFILL_INTEGRATION_TEST=1 GRAPHDB_TEST_REPO=msr-test \\
        GRAPHDB_URL=http://localhost:7200 \\
        uv run --extra test python -m pytest extraction/tests/test_backfill_integration.py -q

Any other ``GRAPHDB_*``/``MSR_*`` variables :class:`~msr_extraction.config.Config`
understands may also be set to point at a non-default stack.

What it covers
---------------
Seeds two staged ``msr:ChangeProposal`` fixtures directly into
``urn:msr:staging`` (one chemistry-genre term, one safety-genre term),
each carrying a stale ``msr:docFrequency`` scalar (reproducing the chunk-8
bug this whole change fixes), plus a tiny on-disk fixture corpus
(``config.archive_dir``'s ``*.txt`` for chemistry, a REAL
``safety_manifest.SAFETY_SOURCES`` id's ``config.safety_normalized_path``
for safety) whose terms match the two proposals. Runs
:func:`~msr_extraction.backfill_observations.run_backfill` against the
disposable repo (self-configuring its own reader/sparql from ``Config``,
task 4.4 -- exactly how the CLI subcommand invokes it) and asserts:

1. each proposal gains an ``msr:hasObservation`` node with
   ``msr:inDocument``/``msr:occurrenceCount``/``msr:inCorpus`` correctly
   attributed to its genre's corpus (task 4.1/4.2);
2. the scanned documents are tagged ``msr:inCorpus`` (task 1.3/4.2);
3. the stale ``msr:docFrequency`` scalars are gone (task 4.3);
4. the review queue's own SPARQL shape (``cmd/server/proposals.go``'s
   ``proposalQueueQuery``, reproduced verbatim below) collapses to exactly
   one row per proposal id, even though the OPTIONAL observation join
   yields one binding per observation (spec proposal-review-api "One row
   per proposal despite multi-corpus/multi-run observations") -- driving
   the actual Go HTTP handler is out of scope for this Python-side suite,
   so this asserts the SPARQL result the handler aggregates from, per the
   task contract's documented fallback;
5. a second ``run_backfill`` invocation (same fixed ``BACKFILL_RUN_TS``)
   leaves ``urn:msr:staging``'s relevant triple counts unchanged
   (idempotent, task 4.3's "Risks/Trade-offs" contract).

Only test-minted subjects are touched: the two proposal IRIs, their
rebuilt observation nodes, and one synthetic chemistry document IRI
(``msrd:test-backfill-it-chem-doc``, never a real corpus id) are cleaned
up in a ``try/finally`` block. The one REAL safety-source document this
test tags with ``msr:inCorpus`` is deliberately left alone in teardown --
that tag is correct, idempotent metadata (not test pollution), and
``test_safety_integration.py`` already establishes that this disposable
repo may carry the four real safety Document nodes.
"""

from __future__ import annotations

import dataclasses
import os

import pytest

# Repo isolation (mirrors test_safety_integration.py's D1/D2 guard,
# internal/testutil.RequireGraphDB on the Go side): resolve the disposable
# test repo from GRAPHDB_TEST_REPO (default "msr-test"), never a hardcoded
# "msr", and hard-refuse before any network call if that resolution lands on
# the production repo (literally "msr", or whatever GRAPHDB_REPO names).
_TEST_REPO = os.environ.get("GRAPHDB_TEST_REPO", "msr-test")
_PROD_REPO = os.environ.get("GRAPHDB_REPO", "msr")

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("MSR_BACKFILL_INTEGRATION_TEST"),
        reason=(
            "guarded observation-backfill integration test skipped: set "
            "MSR_BACKFILL_INTEGRATION_TEST=1 (after `make test-repo`, pointed "
            "at a live GraphDB via GRAPHDB_URL/GRAPHDB_TEST_REPO) to run it"
        ),
    ),
    pytest.mark.skipif(
        _TEST_REPO == "msr" or _TEST_REPO == _PROD_REPO,
        reason=(
            f"refusing to run destructive backfill integration tests against "
            f"the production repo {_TEST_REPO!r}; set GRAPHDB_TEST_REPO to a "
            "disposable repo (see make test-repo)"
        ),
    ),
]

from msr_extraction import safety_manifest
from msr_extraction.backfill_observations import BACKFILL_RUN_TS, run_backfill
from msr_extraction.config import Config
from msr_extraction.sparql import SparqlClient

MSR = "https://w3id.org/msr-kg/ontology#"
MSRD = "https://w3id.org/msr-kg/data#"

# A REAL safety-manifest source id -- run_backfill always re-scans every
# safety_manifest.SAFETY_SOURCES id itself (not caller-injectable), so the
# safety-genre fixture must be written under one of these ids to ever be
# seen by the scan (mirrors test_backfill_observations.py's unit-test
# fixture convention).
SAFETY_SOURCE_ID = safety_manifest.SAFETY_SOURCES[0].id

# Deliberately unique, greppable terms/IRIs -- never appear in any real
# corpus or staged proposal, so this test's fixture is exact and cleanup by
# IRI can never collide with real data.
CHEM_TERM = "zzzbackfillintegrationchemterm"
SAFETY_TERM = "zzzbackfillintegrationsafetyterm"

CHEM_DOC_STEM = "test-backfill-it-chem-doc"
CHEM_DOC_IRI = f"{MSRD}{CHEM_DOC_STEM}"
SAFETY_DOC_IRI = f"{MSRD}{SAFETY_SOURCE_ID}"

PROPOSAL_CHEM_IRI = f"{MSRD}test-backfill-it-proposal-chem"
PROPOSAL_SAFETY_IRI = f"{MSRD}test-backfill-it-proposal-safety"

CORPUS_CHEMISTRY_IRI = f"{MSRD}corpus-chemistry"
CORPUS_SAFETY_IRI = f"{MSRD}corpus-safety"

# Reproduced verbatim from cmd/server/proposals.go's proposalQueueQuery (the
# GET /api/proposals handler's own read) -- see that file's comment for why
# the ?status filter is applied in Go rather than embedded here, and why the
# OPTIONAL observation join legitimately yields one row per observation
# (the handler, and this test, both collapse those back to one row per
# proposal).
_PROPOSAL_QUEUE_QUERY = """\
PREFIX msr: <https://w3id.org/msr-kg/ontology#>
PREFIX prov: <http://www.w3.org/ns/prov#>
SELECT ?s ?kind ?status ?term ?document ?occurrenceCount ?corpus ?generatedAtTime WHERE {
  GRAPH <urn:msr:staging> {
    ?s a msr:ChangeProposal ;
       msr:kind ?kind ;
       msr:reviewStatus ?status ;
       msr:term ?term .
    OPTIONAL {
      ?s msr:hasObservation ?obs .
      ?obs msr:inDocument ?document ;
           msr:occurrenceCount ?occurrenceCount ;
           msr:inCorpus ?corpus ;
           prov:generatedAtTime ?generatedAtTime .
    }
  }
}"""


def _config(tmp_path) -> Config:
    """Build a Config targeting the resolved disposable ``_TEST_REPO`` with a
    fresh ``corpus_dir`` under ``tmp_path`` (never the real 637-doc corpus).

    ``Config`` is a frozen dataclass (mirrors ``test_safety_integration.py``'s
    ``_config`` helper) -- the module-level guard above has already refused
    to run if ``_TEST_REPO`` resolves to the production repo, so this is
    always safe to use directly.
    """
    return dataclasses.replace(
        Config.from_env(), graphdb_repo=_TEST_REPO, corpus_dir=tmp_path
    )


def _sparql_select(config: Config, query: str) -> list[dict[str, dict[str, str]]]:
    """Run a SPARQL SELECT against the configured GraphDB repository.

    Mirrors every other guarded integration module's identical helper: any
    connection error or non-2xx response is a hard failure (this module only
    runs when the caller has opted into requiring a live stack), not a skip.
    """
    import httpx

    endpoint = f"{config.graphdb_url}/repositories/{config.graphdb_repo}"
    response = httpx.post(
        endpoint,
        data={"query": query},
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/sparql-results+json",
        },
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()["results"]["bindings"]


def _sparql_ask(config: Config, query: str) -> bool:
    """Run a SPARQL ASK against the configured GraphDB repository."""
    import httpx

    endpoint = f"{config.graphdb_url}/repositories/{config.graphdb_repo}"
    response = httpx.post(
        endpoint,
        data={"query": query},
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/sparql-results+json",
        },
        timeout=30.0,
    )
    response.raise_for_status()
    return bool(response.json()["boolean"])


def _staging_triple_count(config: Config) -> int:
    bindings = _sparql_select(
        config,
        "SELECT (COUNT(*) AS ?n) WHERE { GRAPH <urn:msr:staging> { ?s ?p ?o } }",
    )
    return int(bindings[0]["n"]["value"])


def _seed_fixture(config: Config) -> None:
    """Seed the two staged proposal fixtures (with stale docFrequency
    scalars) and the tiny on-disk chemistry/safety fixture corpus."""
    sparql = SparqlClient.from_config(config)
    sparql.update(
        f"""\
PREFIX msr: <{MSR}>
PREFIX msrd: <{MSRD}>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
INSERT DATA {{
  GRAPH <urn:msr:staging> {{
    <{PROPOSAL_CHEM_IRI}> a msr:ChangeProposal ;
        msr:kind "property" ;
        msr:term "{CHEM_TERM}" ;
        msr:reviewStatus "pending" ;
        msr:docFrequency "3"^^xsd:integer .
    <{PROPOSAL_SAFETY_IRI}> a msr:ChangeProposal ;
        msr:kind "class" ;
        msr:term "{SAFETY_TERM}" ;
        msr:reviewStatus "pending" ;
        msr:docFrequency "1"^^xsd:integer .
  }}
}}"""
    )

    config.archive_dir.mkdir(parents=True, exist_ok=True)
    (config.archive_dir / f"{CHEM_DOC_STEM}.txt").write_text(
        f"A survey mentioning {CHEM_TERM} in the fixture chemistry corpus.",
        encoding="utf-8",
    )

    safety_path = config.safety_normalized_path(SAFETY_SOURCE_ID)
    safety_path.parent.mkdir(parents=True, exist_ok=True)
    safety_path.write_text(
        f"A passage mentioning {SAFETY_TERM} in the fixture safety corpus.",
        encoding="utf-8",
    )


def _teardown_fixture(config: Config) -> None:
    """Remove every triple this test's fixture could have written.

    Collects each proposal's rebuilt observation IRIs BEFORE deleting the
    proposal itself (mirrors ``test_mine_integration.py``'s teardown
    pattern), since an observation node is a distinct subject the proposal
    deletion alone would not reach.
    """
    sparql = SparqlClient.from_config(config)

    for proposal_iri in (PROPOSAL_CHEM_IRI, PROPOSAL_SAFETY_IRI):
        obs_bindings = _sparql_select(
            config,
            f"""\
PREFIX msr: <{MSR}>
SELECT ?obs WHERE {{
    GRAPH <urn:msr:staging> {{ <{proposal_iri}> msr:hasObservation ?obs }}
}}""",
        )
        for binding in obs_bindings:
            obs_iri = binding["obs"]["value"]
            sparql.update(
                f"DELETE WHERE {{ GRAPH <urn:msr:staging> {{ <{obs_iri}> ?p ?o }} }}"
            )
        sparql.update(
            f"DELETE WHERE {{ GRAPH <urn:msr:staging> {{ <{proposal_iri}> ?p ?o }} }}"
        )

    # The synthetic chemistry document is a test-only IRI -- safe to remove
    # outright. The real safety-source document (SAFETY_DOC_IRI) is
    # deliberately left untouched (see module docstring).
    sparql.update(
        f"DELETE WHERE {{ GRAPH <urn:msr:data> {{ <{CHEM_DOC_IRI}> ?p ?o }} }}"
    )


def test_backfill_writes_observations_tags_documents_and_removes_docfrequency(
    tmp_path,
) -> None:
    """7.7: a full ``run_backfill`` invocation over a small cached fixture
    corpus, against the live disposable repo, writes correct per-corpus
    observations, tags the scanned documents, removes the stale
    ``docFrequency`` scalars, and the queue's own SPARQL shape collapses to
    exactly one row per proposal id."""
    config = _config(tmp_path)

    # Precondition: neither fixture proposal already exists in this
    # disposable repo (a prior aborted run could have left state behind --
    # this makes the teardown-by-IRI below exact rather than merely
    # additive).
    assert not _sparql_ask(
        config, f"ASK {{ GRAPH <urn:msr:staging> {{ <{PROPOSAL_CHEM_IRI}> ?p ?o }} }}"
    ), (
        f"precondition failed: {PROPOSAL_CHEM_IRI} already present in "
        "urn:msr:staging -- a prior run of this test left state behind"
    )
    assert not _sparql_ask(
        config,
        f"ASK {{ GRAPH <urn:msr:staging> {{ <{PROPOSAL_SAFETY_IRI}> ?p ?o }} }}",
    ), (
        f"precondition failed: {PROPOSAL_SAFETY_IRI} already present in "
        "urn:msr:staging -- a prior run of this test left state behind"
    )

    _seed_fixture(config)

    try:
        summary_1 = run_backfill(config)
        assert summary_1.proposals_processed >= 2
        assert summary_1.observations_written >= 2
        assert summary_1.documents_tagged >= 2
        assert summary_1.doc_frequency_scalars_removed >= 2

        # -- chemistry proposal: observation node with inDocument/
        # occurrenceCount/inCorpus, attributed to the chemistry corpus --
        assert _sparql_ask(
            config,
            f"""
            PREFIX msr: <{MSR}>
            ASK {{ GRAPH <urn:msr:staging> {{
                <{PROPOSAL_CHEM_IRI}> msr:hasObservation ?obs .
                ?obs msr:inDocument <{CHEM_DOC_IRI}> ;
                     msr:occurrenceCount ?count ;
                     msr:inCorpus <{CORPUS_CHEMISTRY_IRI}> .
            }} }}
            """,
        ), (
            f"expected {PROPOSAL_CHEM_IRI} to gain an observation over "
            f"{CHEM_DOC_IRI} attributed to msrd:corpus-chemistry"
        )

        # -- safety proposal: observation node attributed to the safety corpus --
        assert _sparql_ask(
            config,
            f"""
            PREFIX msr: <{MSR}>
            ASK {{ GRAPH <urn:msr:staging> {{
                <{PROPOSAL_SAFETY_IRI}> msr:hasObservation ?obs .
                ?obs msr:inDocument <{SAFETY_DOC_IRI}> ;
                     msr:occurrenceCount ?count ;
                     msr:inCorpus <{CORPUS_SAFETY_IRI}> .
            }} }}
            """,
        ), (
            f"expected {PROPOSAL_SAFETY_IRI} to gain an observation over "
            f"{SAFETY_DOC_IRI} attributed to msrd:corpus-safety"
        )

        # -- documents tagged with their corpus (task 1.3/4.2) --
        assert _sparql_ask(
            config,
            f"""
            PREFIX msr: <{MSR}>
            ASK {{ GRAPH <urn:msr:data> {{
                <{CHEM_DOC_IRI}> msr:inCorpus <{CORPUS_CHEMISTRY_IRI}> .
            }} }}
            """,
        )
        assert _sparql_ask(
            config,
            f"""
            PREFIX msr: <{MSR}>
            ASK {{ GRAPH <urn:msr:data> {{
                <{SAFETY_DOC_IRI}> msr:inCorpus <{CORPUS_SAFETY_IRI}> .
            }} }}
            """,
        )

        # -- stale docFrequency scalars are gone (task 4.3) --
        assert not _sparql_ask(
            config,
            f"""
            PREFIX msr: <{MSR}>
            ASK {{ GRAPH <urn:msr:staging> {{
                <{PROPOSAL_CHEM_IRI}> msr:docFrequency ?v .
            }} }}
            """,
        ), f"expected the stale msr:docFrequency scalar on {PROPOSAL_CHEM_IRI} to be removed"
        assert not _sparql_ask(
            config,
            f"""
            PREFIX msr: <{MSR}>
            ASK {{ GRAPH <urn:msr:staging> {{
                <{PROPOSAL_SAFETY_IRI}> msr:docFrequency ?v .
            }} }}
            """,
        ), f"expected the stale msr:docFrequency scalar on {PROPOSAL_SAFETY_IRI} to be removed"

        # -- queue SPARQL shape collapses to one row per proposal id
        # (spec proposal-review-api "One row per proposal despite
        # multi-corpus/multi-run observations") --
        queue_bindings = _sparql_select(config, _PROPOSAL_QUEUE_QUERY)
        our_subjects = {PROPOSAL_CHEM_IRI, PROPOSAL_SAFETY_IRI}
        distinct_ids_seen: dict[str, set[str]] = {}
        for binding in queue_bindings:
            subject = binding["s"]["value"]
            if subject not in our_subjects:
                continue
            distinct_ids_seen.setdefault(subject, set()).add(subject)
        # The join fans out to one BINDING per observation, but each
        # proposal must still collapse to exactly one distinct ?s value --
        # this is what makes the queue handler's per-id aggregation correct
        # (never multiple summary rows for the same proposal id).
        assert distinct_ids_seen.get(PROPOSAL_CHEM_IRI) == {PROPOSAL_CHEM_IRI}
        assert distinct_ids_seen.get(PROPOSAL_SAFETY_IRI) == {PROPOSAL_SAFETY_IRI}

        chem_rows = [b for b in queue_bindings if b["s"]["value"] == PROPOSAL_CHEM_IRI]
        safety_rows = [
            b for b in queue_bindings if b["s"]["value"] == PROPOSAL_SAFETY_IRI
        ]
        assert chem_rows, "expected at least one queue row for the chemistry proposal"
        assert safety_rows, "expected at least one queue row for the safety proposal"
        assert {b["document"]["value"] for b in chem_rows if "document" in b} == {
            CHEM_DOC_IRI
        }
        assert {b["document"]["value"] for b in safety_rows if "document" in b} == {
            SAFETY_DOC_IRI
        }

        # -- idempotency (task 4.3 "Risks/Trade-offs"): re-running with the
        # default fixed BACKFILL_RUN_TS leaves urn:msr:staging's triple
        # count unchanged --
        staging_count_1 = _staging_triple_count(config)

        summary_2 = run_backfill(config)
        assert summary_2.observations_written == summary_1.observations_written
        # No stale docFrequency scalars remain, so the second run's DELETE
        # is skipped entirely (backfill_observations.py's
        # "no unconditional no-op DELETE" contract).
        assert summary_2.doc_frequency_scalars_removed == 0

        staging_count_2 = _staging_triple_count(config)
        assert staging_count_2 == staging_count_1, (
            f"expected urn:msr:staging's triple count to be unchanged across "
            f"a repeat backfill run, was {staging_count_1} then {staging_count_2}"
        )
        assert BACKFILL_RUN_TS == "backfill", (
            "sanity check: this test relies on the default fixed run token "
            "for its idempotency assertion above"
        )
    finally:
        _teardown_fixture(config)

    # -- verify teardown: every subject we wrote is gone --
    assert not _sparql_ask(
        config, f"ASK {{ GRAPH <urn:msr:staging> {{ <{PROPOSAL_CHEM_IRI}> ?p ?o }} }}"
    )
    assert not _sparql_ask(
        config,
        f"ASK {{ GRAPH <urn:msr:staging> {{ <{PROPOSAL_SAFETY_IRI}> ?p ?o }} }}",
    )
    assert not _sparql_ask(
        config, f"ASK {{ GRAPH <urn:msr:data> {{ <{CHEM_DOC_IRI}> ?p ?o }} }}"
    )
