"""Guarded corpus-integration test (task 9.7, design.md D8).

Mirrors chunk 1's ``GRAPHDB_REQUIRED`` opt-in semantics: this module is
skipped entirely during normal/CI collection (no stack, no corpus, no
network) and only runs when explicitly opted into via the
``MSR_INGEST_INTEGRATION`` environment variable. Once opted in, the test is
a hard gate, not a soft one — it FAILS (rather than skips) if the stack or
corpus is unavailable, because passing here is the actual acceptance
criterion for chunks 6-8 (design.md D8, specs/document-graph/spec.md).

How to run it
--------------
Bring up a seeded stack and run the real pipeline first::

    make up
    make load-seed
    make ingest

Then, from the repo root::

    MSR_INGEST_INTEGRATION=1 GRAPHDB_URL=http://localhost:7200 \\
        pytest extraction/tests/test_integration.py

Any other ``GRAPHDB_*``/``MSR_*`` variables :class:`~msr_extraction.config.Config`
understands (``GRAPHDB_REPO``, ``MSR_CORPUS_DIR``, ...) may also be set to
point at a non-default stack/corpus location.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("MSR_INGEST_INTEGRATION"),
    reason=(
        "guarded corpus integration test skipped: set MSR_INGEST_INTEGRATION=1 "
        "(after `make up && make load-seed && make ingest`) to run it"
    ),
)

# These are first-party, dependency-light modules (httpx is a real project
# dependency, not test-only) so importing them at module level is safe even
# when this module's tests are skipped -- only the `httpx.post` call inside
# `_sparql_select` actually needs a reachable network/stack.
from msr_extraction import curated, documents, manifest
from msr_extraction.config import Config
from msr_extraction.manifest import resolve_ocr_path
from msr_extraction.sparql import SparqlClient

MSR = "https://w3id.org/msr-kg/ontology#"
MSRD = "https://w3id.org/msr-kg/data#"


def _sparql_select(config: Config, query: str) -> list[dict[str, dict[str, str]]]:
    """Run a SPARQL SELECT against the configured GraphDB repository.

    POSTs form-encoded ``query=`` to
    ``{graphdb_url}/repositories/{graphdb_repo}`` and returns the
    ``results.bindings`` list from the SPARQL JSON results response.
    Any connection error or non-2xx response is a hard failure (this
    module only runs when the caller has opted into requiring a live
    stack), not a skip.
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
    """Run a SPARQL ASK against the configured GraphDB repository.

    Existence checks use ASK rather than ``SELECT (COUNT(*) …)`` over a
    fully-ground triple pattern: GraphDB returns 0 for a ground
    ``{ <s> a <o> }`` COUNT even when the triple exists (an ASK of the same
    pattern correctly returns true), so a COUNT-based presence check yields
    false negatives. ASK is the correct, unaffected primitive here.
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
    return bool(response.json()["boolean"])


def _curated_records(config: Config) -> list[manifest.ManifestRecord]:
    readme_text = config.readme_path.read_text(encoding="utf-8")
    records = manifest.parse_manifest(readme_text)
    curated_set = set(curated.CURATED_REPORTS)
    return [r for r in records if r.report_number in curated_set]


def test_document_nodes_present_for_every_curated_report() -> None:
    """After a real `make ingest`, every curated report has a Document node.

    Pins specs/document-graph/spec.md's "Curated documents present in the
    graph" scenario: the graph contains `msrd:{report#} a msr:Document` in
    `urn:msr:data` for each of the (currently 11) curated reports, and the
    distinct-subject count of `msr:Document` in that graph is at least the
    curated-set size (>= rather than == so pre-existing seed Documents, if
    any, don't break the assertion).
    """
    config = Config.from_env()

    bindings = _sparql_select(
        config,
        f"""
        PREFIX msr: <{MSR}>
        SELECT (COUNT(DISTINCT ?doc) AS ?count)
        WHERE {{ GRAPH <urn:msr:data> {{ ?doc a msr:Document }} }}
        """,
    )
    count = int(bindings[0]["count"]["value"])
    assert count >= len(curated.CURATED_REPORTS), (
        f"expected at least {len(curated.CURATED_REPORTS)} msr:Document nodes "
        f"in urn:msr:data, found {count}"
    )

    for report in curated.CURATED_REPORTS:
        present = _sparql_ask(
            config,
            f"ASK {{ GRAPH <urn:msr:data> {{ <{MSRD}{report}> a <{MSR}Document> }} }}",
        )
        assert present, f"msrd:{report} a msr:Document not found in urn:msr:data"


def test_curated_ocr_contains_evolution_target_patterns() -> None:
    """The curated OCR, read from the real corpus, contains both gate targets.

    Pins design.md D2/D8's evolution-demo gate against the on-disk corpus
    (not a fixture): across the curated set's OCR text, both a
    solubility-with-value-and-unit statement and graphite-as-moderator
    prose must be detectable.
    """
    config = Config.from_env()
    curated_records = _curated_records(config)
    assert curated_records, "no curated manifest records resolved from the real README"

    all_records = manifest.parse_manifest(
        config.readme_path.read_text(encoding="utf-8")
    )

    found = {"solubility": False, "graphite_moderator": False}
    for report in curated.CURATED_REPORTS:
        ocr_path = resolve_ocr_path(all_records, report)
        text = (config.archive_dir / ocr_path).read_text(
            encoding="utf-8", errors="replace"
        )
        targets = curated.detect_evolution_targets(text)
        found["solubility"] = found["solubility"] or targets["solubility"]
        found["graphite_moderator"] = (
            found["graphite_moderator"] or targets["graphite_moderator"]
        )

    assert found["solubility"], (
        "no curated document's OCR matched the solubility+value+unit pattern"
    )
    assert found["graphite_moderator"], (
        "no curated document's OCR matched the graphite-as-moderator pattern"
    )


def test_document_write_is_idempotent_on_rerun() -> None:
    """Re-running the Document-node write leaves urn:msr:data unchanged.

    Pins specs/document-graph/spec.md's "Re-running the write changes
    nothing" scenario: total triple count in `urn:msr:data` before and
    after a second `write_documents` call over the curated records must be
    equal (deterministic IRIs, no blank nodes -> set-semantics no-op).
    """
    config = Config.from_env()
    curated_records = _curated_records(config)
    assert curated_records, "no curated manifest records resolved from the real README"

    def _triple_count() -> int:
        bindings = _sparql_select(
            config,
            "SELECT (COUNT(*) AS ?count) WHERE { GRAPH <urn:msr:data> { ?s ?p ?o } }",
        )
        return int(bindings[0]["count"]["value"])

    before = _triple_count()
    documents.write_documents(curated_records, SparqlClient.from_config(config))
    after_first = _triple_count()
    documents.write_documents(curated_records, SparqlClient.from_config(config))
    after_second = _triple_count()

    assert after_first == after_second, (
        f"expected urn:msr:data triple count to be unchanged after a repeat "
        f"write, was {after_first} then {after_second}"
    )
    # A rerun over an already-ingested stack should also leave the count
    # unchanged relative to before this test's own first write (the write
    # is a no-op if `make ingest` already wrote these same records).
    assert before <= after_first


def test_seed_document_metadata_is_manifest_sourced_single_label() -> None:
    """The pre-seeded Document ends with exactly one, manifest-sourced label.

    Pins specs/document-graph/spec.md's "Re-asserting a seed Document is a
    no-op" scenario by name (not just by aggregate count): the seed A-Box
    types `msrd:ORNL-TM-2316 a msr:Document` but deliberately carries no
    hand-authored label/identifier/date, so after ingest the node has exactly
    one `rdfs:label` — the manifest's — rather than a seed label coexisting
    with a divergent manifest label. This is the check that the count-based
    idempotency test structurally cannot make.
    """
    config = Config.from_env()
    subject = f"{MSRD}ORNL-TM-2316"

    assert _sparql_ask(
        config, f"ASK {{ GRAPH <urn:msr:data> {{ <{subject}> a <{MSR}Document> }} }}"
    ), "seed Document msrd:ORNL-TM-2316 is not typed a msr:Document after ingest"

    # rdfs:label object is a variable here, so COUNT/enumeration is reliable
    # (unlike a fully-ground `a` pattern — see _sparql_ask docstring).
    label_bindings = _sparql_select(
        config,
        f"""
        SELECT ?l WHERE {{ GRAPH <urn:msr:data> {{
            <{subject}> <http://www.w3.org/2000/01/rdf-schema#label> ?l
        }} }}
        """,
    )
    labels = [b["l"]["value"] for b in label_bindings]
    assert len(labels) == 1, (
        f"expected exactly one rdfs:label on the seed Document, found {labels!r} "
        "(a divergent seed label coexisting with the manifest's would give 2)"
    )

    all_records = manifest.parse_manifest(
        config.readme_path.read_text(encoding="utf-8")
    )
    record = next(r for r in all_records if r.report_number == "ORNL-TM-2316")
    assert labels[0] == record.title, (
        f"seed Document label {labels[0]!r} is not the manifest title "
        f"{record.title!r} — manifest must be the single metadata source"
    )
