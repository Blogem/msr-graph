"""Guarded link-pipeline integration test (task 10.9, design.md D9/D10).

Mirrors ``test_integration.py``'s ``MSR_INGEST_INTEGRATION`` opt-in pattern
(itself mirroring chunk 1's ``GRAPHDB_REQUIRED`` semantics): this module is
skipped entirely during normal/CI collection (no stack, no corpus, no
network) and only runs when explicitly opted into via the
``MSR_LINK_INTEGRATION`` environment variable. Once opted in, the test is a
hard gate, not a soft one -- it FAILS (rather than skips) if the stack or
corpus is unavailable, because passing here is the actual acceptance
criterion for chunk 6 (design.md D9/D10, specs/entity-linking/spec.md).

How to run it
--------------
Bring up a seeded, catalogued, ingested, and *linked* stack first::

    make up
    make load-seed
    make load-nist
    make ingest
    make link

Then, from the repo root::

    MSR_LINK_INTEGRATION=1 GRAPHDB_URL=http://localhost:7200 \\
        pytest extraction/tests/test_link_integration.py

Any other ``GRAPHDB_*``/``MSR_*`` variables :class:`~msr_extraction.config.Config`
understands may also be set to point at a non-default stack/corpus location.

Note on chunk-6 module availability: at the time this test module was
authored (pass 1, tester writing against the linker API contract in
parallel with the coder), ``msr_extraction.linker`` did not yet exist in
this worktree. Importing it unconditionally at module level would break
*collection* of this file even though its tests are meant to be skipped by
default -- so that import (and the other chunk-6-only imports it needs) is
deferred into the one test function that needs it, exactly like
``test_integration.py`` defers ``import httpx`` into ``_sparql_select``/
``_sparql_ask`` for the same reason (a not-yet-guaranteed dependency must
not be required merely to *load* this module).
"""

from __future__ import annotations

import json
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("MSR_LINK_INTEGRATION"),
    reason=(
        "guarded link-pipeline integration test skipped: set MSR_LINK_INTEGRATION=1 "
        "(after `make up && make load-seed && make load-nist && make ingest && "
        "make link`) to run it"
    ),
)

from msr_extraction.config import Config

MSR = "https://w3id.org/msr-kg/ontology#"
MSRD = "https://w3id.org/msr-kg/data#"
VOC = "https://w3id.org/msr-kg/vocab#"

REPORT = "ORNL-TM-2316"

# Anchor surface forms -> expected target IRI, mirroring design.md D10's
# "guarded integration" bullet and specs/entity-linking/spec.md's "Anchor
# entities link to the correct targets" scenario.
_ANCHORS = {
    "FLiBe": f"{VOC}flibe",
    "viscosity": f"{VOC}viscosity",
    "MSRE": f"{VOC}msre-reactor",
}

# The loaded MSRE-coolant FLiBe individual (design.md Context / D3):
# 34 mol% BeF2 / 66 mol% LiF, minted by the chunk-2 NIST loader.
_COMPOSED_SALT_IRI = f"{MSRD}salt-BeF2-LiF-34.0-66.0"


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
    fully-ground triple pattern (see ``test_integration.py``'s identical
    helper docstring): GraphDB returns 0 for a ground COUNT even when the
    triple exists, so ASK is the correct primitive here.
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


def _mention_triple_count(config: Config) -> int:
    """Count all triples whose subject is typed ``msr:Mention`` in ``urn:msr:data``.

    Joining ``?m a msr:Mention`` with the unconstrained ``?m ?p ?o`` counts
    every triple belonging to a Mention individual (its type triple plus
    ``linksTo``/``inDocument``/``surfaceForm``/``startOffset``/``endOffset``),
    i.e. the full "mention triples" set design.md D7 describes -- not just
    the count of distinct Mention subjects.
    """
    bindings = _sparql_select(
        config,
        f"""
        PREFIX msr: <{MSR}>
        SELECT (COUNT(*) AS ?count) WHERE {{
            GRAPH <urn:msr:data> {{
                ?m a msr:Mention .
                ?m ?p ?o .
            }}
        }}
        """,
    )
    return int(bindings[0]["count"]["value"])


def test_anchor_mentions_resolve_to_correct_targets() -> None:
    """After a real `make link` run, each anchor surface has a correctly-targeted msr:Mention.

    Pins specs/entity-linking/spec.md's "Anchor entities link to the correct
    targets" scenario against the real corpus/graph (not a fixture): for
    each of ``LiF-BeF2``/``FLiBe``, ``viscosity``, and ``MSRE``, at least one
    ``msr:Mention`` in ``urn:msr:data`` has that surface form and
    ``msr:linksTo`` the expected concept/individual.
    """
    config = Config.from_env()

    for surface, target_iri in _ANCHORS.items():
        bindings = _sparql_select(
            config,
            f"""
            PREFIX msr: <{MSR}>
            SELECT ?m WHERE {{
                GRAPH <urn:msr:data> {{
                    ?m a msr:Mention ;
                       msr:surfaceForm "{surface}" ;
                       msr:linksTo <{target_iri}> .
                }}
            }}
            """,
        )
        assert bindings, (
            f"expected an msr:Mention with surfaceForm {surface!r} linking to "
            f"<{target_iri}> in urn:msr:data, found none"
        )


def test_lif_bef2_composed_mention_links_to_loaded_salt_individual() -> None:
    """A LiF-BeF2 composed mention resolves to the loaded MoltenSalt individual.

    Pins specs/entity-linking/spec.md's "Salt mention resolves to the loaded
    individual" scenario: at least one ``msr:Mention`` in ``urn:msr:data``
    ``msr:linksTo`` the loaded MSRE-coolant FLiBe individual
    ``msrd:salt-BeF2-LiF-34.0-66.0`` (34 mol% BeF2 / 66 mol% LiF), not merely
    a vocab concept.

    ground-demo-in-real-docs (design.md D4): with no hand-curated seed
    A-Box, this ``ASK`` for a real composed-mention ``msr:linksTo`` edge
    into ``msrd:salt-BeF2-LiF-34.0-66.0`` (minted only by ``loader nist``)
    is the **authoritative end-to-end grounding-edge acceptance check** for
    that change -- there is no other path (seed or otherwise) that could
    make this pass except the real ingest -> link pipeline actually
    grounding a salt mention to the loaded individual.
    """
    config = Config.from_env()

    present = _sparql_ask(
        config,
        f"""
        PREFIX msr: <{MSR}>
        ASK {{
            GRAPH <urn:msr:data> {{
                ?m a msr:Mention ;
                   msr:linksTo <{_COMPOSED_SALT_IRI}> .
            }}
        }}
        """,
    )
    assert present, (
        f"expected at least one msr:Mention linking to the loaded salt individual "
        f"<{_COMPOSED_SALT_IRI}> (a LiF-BeF2 composed mention) in urn:msr:data"
    )


def test_second_link_run_is_idempotent() -> None:
    """Re-running the link pipeline over the same corpus leaves the mention-triple count unchanged.

    Pins specs/entity-linking/spec.md's "Deterministic regeneration" /
    design.md D7's idempotency contract: deterministic IRIs and no blank
    nodes mean writing the same linked mentions a second time is a
    set-semantics no-op. This test performs that second write itself (over
    the real ``segments.jsonl`` for ORNL-TM-2316, using the real graph's
    known entities) and compares the ``urn:msr:data`` mention-triple count
    before and after.
    """
    # Deferred: msr_extraction.linker is the one chunk-6 module that did not
    # exist in this worktree at pass-1 authoring time (see module docstring).
    # Deferring here keeps this module collectible regardless.
    from msr_extraction import mentions as mentions_mod
    from msr_extraction.graph_reader import GraphReader
    from msr_extraction.linker import Segment, link_segment
    from msr_extraction.seeding import build_matcher
    from msr_extraction.sparql import SparqlClient

    config = Config.from_env()

    segments_path = config.segments_path(REPORT)
    assert segments_path.exists(), (
        f"expected chunk-5 segments artifact at {segments_path} -- run `make ingest` first"
    )

    reader = GraphReader.from_config(config)
    known_entities = reader.read_known_entities()
    assert known_entities, "expected a non-empty known-entity set from the seeded graph"
    known_iris = {e.target_iri for e in known_entities}
    matcher = build_matcher(known_entities)

    linked_records = []
    with segments_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            seg = Segment(
                report=obj["report"],
                index=obj["index"],
                text=obj["text"],
                char_start=obj["char_start"],
                char_end=obj["char_end"],
            )
            records = link_segment(
                seg, matcher, known_entities, known_iris, config, disambiguator=None
            )
            linked_records.extend(r for r in records if r.status == "linked")

    assert linked_records, (
        f"expected at least one linked record over the real {REPORT} segments"
    )

    document_iri = f"{MSRD}{REPORT}"
    to_write = [
        mentions_mod.Mention(
            report=r.report,
            start=r.char_start,
            end=r.char_end,
            surface_form=r.surface_form,
            target_iri=r.target_iri,
            document_iri=document_iri,
        )
        for r in linked_records
    ]

    client = SparqlClient.from_config(config)

    before = _mention_triple_count(config)
    mentions_mod.write_mentions(to_write, client)
    after_first = _mention_triple_count(config)
    mentions_mod.write_mentions(to_write, client)
    after_second = _mention_triple_count(config)

    assert after_first == after_second, (
        f"expected urn:msr:data mention-triple count to be unchanged after a "
        f"repeat write, was {after_first} then {after_second}"
    )
    assert before <= after_first
