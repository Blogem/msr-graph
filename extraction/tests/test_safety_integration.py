"""Guarded safety-corpus integration test (task 8.9, design.md D1-D4/D8,
openspec/changes/ingest-iaea-safety).

Mirrors ``test_extract_integration.py``'s ``MSR_EXTRACT_INTEGRATION``
opt-in pattern exactly (itself mirroring ``test_link_integration.py``):
this module is skipped entirely during normal/CI collection (no stack, no
corpus, no network, no LLM credentials) and only runs when explicitly
opted into via the ``MSR_SAFETY_CORPUS_TEST`` environment variable. Once
opted in, the test is a hard gate, not a soft one -- it FAILS (rather than
skips) if the stack/corpus/approval step is missing, because passing here
is the actual acceptance criterion for chunk 11 (design.md's own "Guarded
corpus integration" bullet, tasks.md 8.9):

    after a real `make ingest-safety`: the four safety Document nodes
    present with attribution; the three fundamental safety functions
    surfaced as proposals; after approval, `msrd:sf-heat-removal
    msr:servedByProperty msr:specificHeat` resolvable and traceable to a
    salt measurement; a second run leaves `urn:msr:data` triple counts
    unchanged.

How to run it
--------------
Bring up a seeded, catalogued stack, run the safety ingest pipeline, then
approve the mined SafetyFunction/Requirement proposals (and the two
linking relations) via the chunk-9 approval API, then re-run the safety
pipeline so the second-phase linking relations resolve::

    make up && make load-nist
    (cd extraction && uv run python -m msr_extraction safety ingest)
    # ... review + approve the mined safety branch via the chunk-9 API ...
    (cd extraction && uv run python -m msr_extraction safety ingest)

Then, from the repo root::

    MSR_SAFETY_CORPUS_TEST=1 GRAPHDB_URL=http://localhost:7200 \\
        pytest extraction/tests/test_safety_integration.py

Any other ``GRAPHDB_*``/``MSR_*`` variables :class:`~msr_extraction.config.Config`
understands may also be set to point at a non-default stack.

Note on heavy-dependency deferral: exactly like ``test_extract_integration.py``
defers ``httpx``/``sqlite3``/``msr_extraction.cli`` imports into the test
bodies, this module defers ``httpx`` into the one helper that needs it, so
the module COLLECTS cleanly (no live stack required merely to *import* this
file) even though its tests are meant to be skipped by default.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("MSR_SAFETY_CORPUS_TEST"),
    reason=(
        "guarded safety-corpus integration test skipped: set "
        "MSR_SAFETY_CORPUS_TEST=1 (after `make up && make load-nist` and "
        "running `safety ingest` twice, with a manual approval of the "
        "mined safety branch in between) to run it"
    ),
)

from msr_extraction import safety_manifest
from msr_extraction.config import Config

MSR = "https://w3id.org/msr-kg/ontology#"
MSRD = "https://w3id.org/msr-kg/data#"

# The three fundamental safety functions design.md D3/specs/
# safety-ontology-evolution require to surface as staging proposals
# (evidence-bearing, mined from the ingested safety genre), matched by
# substring against each proposal's msr:term literal.
_FUNDAMENTAL_SAFETY_FUNCTION_TERMS = (
    ("confinement", "radioactive"),
    ("control", "reactivity"),
    ("heat", "removal"),
)

# The real, minted grounding example design.md's own D4 worked example
# pins (GIF Holcomb: "heat capacity ... for natural circulation cooling"):
# the approved msr:SafetyFunction individual for "heat removal".
_SF_HEAT_REMOVAL_IRI = f"{MSRD}sf-heat-removal"
_SPECIFIC_HEAT_IRI = f"{MSR}specificHeat"


def _sparql_select(config: Config, query: str) -> list[dict[str, dict[str, str]]]:
    """Run a SPARQL SELECT against the configured GraphDB repository.

    Mirrors ``test_extract_integration.py``'s identical helper: any
    connection error or non-2xx response is a hard failure (this module
    only runs when the caller has opted into requiring a live stack), not
    a skip.
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
    """Run a SPARQL ASK against the configured GraphDB repository. Mirrors
    ``test_extract_integration.py``'s identical helper."""
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


def _run_safety_ingest_cli(config: Config) -> None:
    """Invoke ``python -m msr_extraction safety ingest`` in-process against
    ``config``. Mirrors ``test_extract_integration.py``'s
    ``_run_extract_cli`` (in-process, not subprocess, so the second run
    reuses the exact same process environment)."""
    from msr_extraction import cli

    exit_code = cli.main(["safety", "ingest"])
    assert exit_code == 0, f"expected `safety ingest` to exit 0, got {exit_code}"


def test_four_safety_documents_present_with_attribution() -> None:
    """A real `safety ingest` run writes all four attributed safety Document nodes.

    Pins specs/safety-source-acquisition/spec.md's Document-node
    requirement (design.md D2, tasks 2.1/2.2): each of the four
    ``safety_manifest.SAFETY_SOURCES`` IDs has an ``msr:Document`` in
    ``urn:msr:data`` carrying ``rdfs:label``, ``dcterms:identifier``,
    ``dcterms:date``, ``dcterms:publisher``, ``dcterms:rights``, and
    ``dcterms:source`` (confirmed against ``documents.write_safety_documents``'s
    triple shape).
    """
    config = Config.from_env()

    assert len(safety_manifest.SAFETY_SOURCES) == 4, (
        "expected exactly four safety sources in the manifest"
    )

    for source in safety_manifest.SAFETY_SOURCES:
        bindings = _sparql_select(
            config,
            f"""
            PREFIX msr: <{MSR}>
            PREFIX msrd: <{MSRD}>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            PREFIX dcterms: <http://purl.org/dc/terms/>
            SELECT ?label ?identifier ?date ?publisher ?rights ?source WHERE {{
                GRAPH <urn:msr:data> {{
                    msrd:{source.id} a msr:Document ;
                        rdfs:label ?label ;
                        dcterms:identifier ?identifier ;
                        dcterms:date ?date ;
                        dcterms:publisher ?publisher ;
                        dcterms:rights ?rights ;
                        dcterms:source ?source .
                }}
            }}
            """,
        )
        assert bindings, (
            f"expected an attributed msr:Document msrd:{source.id} in "
            "urn:msr:data -- run `safety ingest` (safety documents stage) first"
        )
        row = bindings[0]
        assert row["label"]["value"], f"{source.id}: expected a non-empty rdfs:label"
        assert row["identifier"]["value"] == source.id, (
            f"{source.id}: expected dcterms:identifier to equal the source id"
        )
        assert row["publisher"]["value"], f"{source.id}: expected a non-empty dcterms:publisher"
        assert row["rights"]["value"], f"{source.id}: expected a non-empty dcterms:rights"
        assert row["source"]["value"], f"{source.id}: expected a non-empty dcterms:source"


def test_three_fundamental_safety_functions_surfaced_as_proposals() -> None:
    """The miner's proposals for the three fundamental safety functions
    are present in staging, each with evidence citing a safety Document.

    Pins specs/safety-ontology-evolution/spec.md's "Fundamental safety
    functions surface as proposals" scenario: a `msr:ChangeProposal` per
    phrase in `urn:msr:staging`, carrying `msr:term` (substring-matched,
    case-insensitively, against the phrase's content words) and at least
    one `msr:hasEvidence` Evidence node `msr:citedIn` one of the four
    safety Documents (confirmed against `proposals._staging_resource_block`'s
    real triple shape).
    """
    config = Config.from_env()
    safety_document_iris = {f"{MSRD}{source.id}" for source in safety_manifest.SAFETY_SOURCES}

    for words in _FUNDAMENTAL_SAFETY_FUNCTION_TERMS:
        filters = " && ".join(f'CONTAINS(LCASE(?term), "{w}")' for w in words)
        bindings = _sparql_select(
            config,
            f"""
            PREFIX msr: <{MSR}>
            SELECT ?proposal ?term ?citedIn WHERE {{
                GRAPH <urn:msr:staging> {{
                    ?proposal a msr:ChangeProposal ;
                        msr:term ?term ;
                        msr:hasEvidence ?evidence .
                    ?evidence msr:citedIn ?citedIn .
                }}
                FILTER({filters})
            }}
            """,
        )
        assert bindings, (
            f"expected a staged msr:ChangeProposal whose msr:term contains "
            f"all of {words!r} -- run `safety ingest` (mine stage) first"
        )
        cited_documents = {row["citedIn"]["value"] for row in bindings}
        assert cited_documents & safety_document_iris, (
            f"expected the {words!r} proposal's evidence to cite one of the "
            f"four safety Documents {sorted(safety_document_iris)}, got "
            f"{sorted(cited_documents)}"
        )


def test_served_by_property_edge_resolvable_and_traceable_to_a_salt_measurement() -> None:
    """After approval, msrd:sf-heat-removal servedByProperty specificHeat
    resolves, and specificHeat is traceable to a real salt measurement.

    Pins the design.md D4 grounding example (GIF Holcomb: "heat capacity
    ... for natural circulation cooling") and the D9-style cross-document
    join this whole change exists to demonstrate: once the mined
    SafetyFunction/servedByProperty edge is approved into core, the direct
    edge is queryable in `urn:msr:data`, AND `msr:specificHeat` already has
    at least one real `msr:PropertyMeasurement` (`msr:forProperty
    msr:specificHeat`) from the chemistry corpus -- so the safety function
    is genuinely traceable to a measured salt property, not merely to a
    bare, ungrounded property IRI.
    """
    config = Config.from_env()

    edge_present = _sparql_ask(
        config,
        f"""
        PREFIX msr: <{MSR}>
        PREFIX msrd: <{MSRD}>
        ASK {{
            GRAPH <urn:msr:data> {{
                msrd:sf-heat-removal msr:servedByProperty msr:specificHeat .
            }}
        }}
        """,
    )
    assert edge_present, (
        f"expected <{_SF_HEAT_REMOVAL_IRI}> msr:servedByProperty <{_SPECIFIC_HEAT_IRI}> "
        "in urn:msr:data -- approve the mined safety branch (SafetyFunction "
        "individual + servedByProperty/addressesFunction object properties) "
        "via the chunk-9 approval API, then re-run `safety ingest` so the "
        "second-phase linking relations resolve"
    )

    measurement_bindings = _sparql_select(
        config,
        f"""
        PREFIX msr: <{MSR}>
        SELECT ?measurement ?salt WHERE {{
            GRAPH <urn:msr:data> {{
                ?measurement a msr:PropertyMeasurement ;
                    msr:forProperty msr:specificHeat ;
                    msr:ofSalt ?salt .
            }}
        }}
        """,
    )
    assert measurement_bindings, (
        "expected at least one msr:PropertyMeasurement msr:forProperty "
        "msr:specificHeat in urn:msr:data -- msr:specificHeat must already "
        "be grounded to a real salt measurement for the safety function to "
        "be traceable to one"
    )
    assert measurement_bindings[0]["salt"]["value"], (
        "expected the specificHeat measurement to name a msr:ofSalt individual"
    )


def test_second_safety_ingest_run_leaves_data_triple_count_unchanged() -> None:
    """Re-running `safety ingest` is a no-op on `urn:msr:data`'s triple count.

    Pins design.md D4/D8's idempotency contract: deterministic IRIs and
    additive `INSERT DATA` mean a second `safety ingest` invocation (over
    the same corpus, same approval state) leaves `urn:msr:data`'s total
    triple count unchanged, exactly mirroring
    ``test_extract_integration.py``'s
    ``test_second_extract_run_is_idempotent_in_data_and_sqlite``.
    """
    config = Config.from_env()

    def _data_triple_count() -> int:
        bindings = _sparql_select(
            config,
            """
            SELECT (COUNT(*) AS ?count) WHERE {
                GRAPH <urn:msr:data> { ?s ?p ?o }
            }
            """,
        )
        return int(bindings[0]["count"]["value"])

    before = _data_triple_count()

    _run_safety_ingest_cli(config)

    after = _data_triple_count()

    assert after == before, (
        f"expected urn:msr:data triple count to be unchanged after a repeat "
        f"`safety ingest` run, was {before} then {after}"
    )
