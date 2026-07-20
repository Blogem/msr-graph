"""Hermetic regression test for the CRITICAL SPARQL-injection / invalid-Turtle
defect in the ontology-mining pipeline (mine-ontology-candidates).

`Placement.broader_class`/`.domain`/`.range_` are raw, unvalidated strings
lifted straight from the DeepSeek triage JSON reply (`triage._build_placement`
only checks "non-empty str") and were, before this fix, spliced directly into
CURIE/IRI *term* position in a generated SPARQL `INSERT DATA` string -- a
position `proposals._escape_literal` never protected, since that helper only
escapes *literal* position. A hallucinated or prompt-injected reply could
therefore forge a multi-statement SPARQL update (e.g. `DROP GRAPH
<urn:msr:ontology>`).

This module drives `mine_runner.run_mine` end-to-end with a fake SPARQL
client (records every `.update(...)` string; no network) and a stub
classifier (a fixed JSON reply; no live model), exactly mirroring the fake/
stub shapes used by `test_proposals.py`/`test_mine_integration.py`. No live
GraphDB, no live LLM -- fully hermetic, runs in normal `pytest` collection
(unlike `test_mine_integration.py`, which is guarded behind
`GRAPHDB_REQUIRED=1`).
"""

from __future__ import annotations

import json
from pathlib import Path

from msr_extraction import mine_runner, novelty
from msr_extraction.config import Config
from msr_extraction.mining_types import Candidate, Evidence

REPORT = "FIX-0002"
DOC_IRI = "https://w3id.org/msr-kg/data#FIX-0002"

QUDT_PATH = Path(__file__).parent / "fixtures" / "mining" / "qudt-units.json"

#: The adversarial payload from the defect report: if spliced unguarded into
#: `msr:{broader}` term position, this forges a graph-drop plus a bogus
#: `INSERT DATA` for an attacker-controlled individual.
SPARQL_BREAKOUT_PAYLOAD = (
    'Moderator> } } ; DROP GRAPH <urn:msr:ontology> ; '
    'INSERT DATA { GRAPH <urn:msr:data> { <urn:msr:data#pwned> a owl:Thing'
)


class FakeSparqlClient:
    """Records every `.update(sparql)` string; never touches the network."""

    def __init__(self) -> None:
        self.updates: list[str] = []

    def update(self, sparql_update: str) -> None:
        self.updates.append(sparql_update)


class FakeGraphReader:
    """A `KGSchemaPromptCache`/`run_mine`-compatible reader with an empty
    known-entity set -- hermetic, no SPARQL query, no network."""

    def read_known_entities(self) -> list:
        return []

    def read_version(self) -> str | None:
        return None

    def known_iris(self) -> set[str]:
        return set()


class StubCompleter:
    """Returns a fixed JSON reply for every `.complete(...)` call -- no live
    model (mirrors `test_mine_integration.py`'s `StubClassifier`)."""

    def __init__(self, response: str) -> None:
        self._response = response

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        return self._response


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
    return Candidate(term=term, source="lexical", evidence=evidence, doc_frequency=999)


def test_run_mine_skips_class_candidate_with_sparql_breakout_broader_class(
    monkeypatch, tmp_path: Path
) -> None:
    """A `class`-kind candidate whose `broaderClass` is the SPARQL-breakout
    payload must be dropped entirely: no proposal is counted, and -- the
    critical assertion -- no `.update(...)` string sent to the (fake) graph
    ever contains `DROP GRAPH`, `CLEAR`, or the raw payload text."""
    candidate = _candidate(
        "graphite", "Graphite was used as the moderator material in the reactor core."
    )
    monkeypatch.setattr(novelty, "mine_candidates", lambda config, reader: [candidate])

    response = json.dumps({"kind": "class", "broaderClass": SPARQL_BREAKOUT_PAYLOAD})
    client = StubCompleter(response)
    reader = FakeGraphReader()
    sparql = FakeSparqlClient()
    config = Config(corpus_dir=tmp_path)

    summary = mine_runner.run_mine(
        config, reader=reader, client=client, sparql=sparql, qudt_path=QUDT_PATH
    )

    assert summary["proposals_by_kind"].get("class", 0) == 0
    assert summary["rejected"] == 1
    assert summary["auto_accepted"] == 0

    assert sparql.updates, "expected the stable+per-run Activity provenance writes"
    for update in sparql.updates:
        assert "DROP GRAPH" not in update
        assert "CLEAR" not in update
        assert SPARQL_BREAKOUT_PAYLOAD not in update
        assert "pwned" not in update


def test_run_mine_skips_instance_candidate_with_sparql_breakout_broader_class(
    monkeypatch, tmp_path: Path
) -> None:
    """The same adversarial payload, this time as an `instance`-kind
    candidate's asserted type (the auto-accept/rides-with individual path,
    `mine_runner._as_type_ref` -> `auto_accept.individual_triples`). Must be
    dropped -- never written to `urn:msr:data` or anywhere else."""
    candidate = _candidate(
        "testminesalt", "A new compound TestMineSalt was observed in the melt."
    )
    monkeypatch.setattr(novelty, "mine_candidates", lambda config, reader: [candidate])

    response = json.dumps({"kind": "instance", "broaderClass": SPARQL_BREAKOUT_PAYLOAD})
    client = StubCompleter(response)
    reader = FakeGraphReader()
    sparql = FakeSparqlClient()
    config = Config(corpus_dir=tmp_path)

    summary = mine_runner.run_mine(
        config, reader=reader, client=client, sparql=sparql, qudt_path=QUDT_PATH
    )

    assert summary["auto_accepted"] == 0
    assert summary["dropped"] == 1

    for update in sparql.updates:
        assert "DROP GRAPH" not in update
        assert "CLEAR" not in update
        assert SPARQL_BREAKOUT_PAYLOAD not in update
        assert "pwned" not in update


def test_run_mine_still_stages_legitimate_class_candidate(
    monkeypatch, tmp_path: Path
) -> None:
    """Positive control: the legitimate `graphite` -> `broaderClass:
    "Moderator"` demo case (design.md D7) must still produce exactly one
    `class` proposal, unaffected by the injection guard."""
    candidate = _candidate(
        "graphite", "Graphite was used as the moderator material in the reactor core."
    )
    monkeypatch.setattr(novelty, "mine_candidates", lambda config, reader: [candidate])

    response = json.dumps({"kind": "class", "broaderClass": "Moderator"})
    client = StubCompleter(response)
    reader = FakeGraphReader()
    sparql = FakeSparqlClient()
    config = Config(corpus_dir=tmp_path)

    summary = mine_runner.run_mine(
        config, reader=reader, client=client, sparql=sparql, qudt_path=QUDT_PATH
    )

    assert summary["rejected"] == 0
    assert summary["proposals_by_kind"].get("class") == 1

    proposal_update = next(
        u for u in sparql.updates if "GRAPH <urn:msr:proposal/class-graphite>" in u
    )
    assert "msr:Moderator a owl:Class" in proposal_update
