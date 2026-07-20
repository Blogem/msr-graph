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

refine-mine-salience (7.4) additions below: the run-summary key contract
changes from `{"candidates", "proposals_by_kind", "auto_accepted",
"rejected", "dropped"}` to additionally split "dropped" into
`triage_rejected` (an explicit triage `reject` verdict -- design.md D4) and
`dropped_malformed` (malformed/unrecognized-kind triage output, still a
`None` `TriagedCandidate`), leaving `dropped` for every other drop reason
(unsafe/missing evidence, unresolved schema dependency, the
unreachable-kind branch). The pre-existing
`test_run_mine_preserves_candidate_order_regardless_of_triage_completion_order`
test below is updated to the new key semantics: `baddrop`'s
`{"kind": "not-a-real-kind"}` verdict is an unrecognized-kind malformed
drop, not a generic "dropped" one, under the new contract.
"""

from __future__ import annotations

import json
import re
import threading
import time
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


_TERM_RE = re.compile(r'Candidate term: "(.*?)"')


def _term_from_prompt(user_prompt: str) -> str:
    """Extract the candidate term `triage._build_user_prompt` embeds in the
    user prompt (`Candidate term: "{candidate.term}"`), so a stub completer
    can return a per-candidate response without needing to know call order."""
    match = _TERM_RE.search(user_prompt)
    assert match is not None, f"no candidate term found in prompt: {user_prompt!r}"
    return match.group(1)


class RecordingCompleter:
    """A per-term stub `Completer` that proves both (a) the mine triage pool
    actually runs candidates concurrently, and (b) `run_mine`'s Phase 2
    routing/writes stay in original candidate order regardless of which
    Flash call happens to finish first.

    `responses` maps candidate term -> canned JSON reply. `delays` maps
    candidate term -> a `time.sleep` duration applied *inside* `.complete`
    before returning, deliberately set in REVERSE of candidate submission
    order in the tests below (the first-submitted candidate sleeps
    longest, the last-submitted returns almost immediately) -- so, under
    real concurrency, results are ready in the OPPOSITE order from how
    they were submitted. If `mine_runner` mistakenly used completion order
    (e.g. appended straight from `as_completed`) instead of reassembling by
    original index, this reversal would flip the observed write order and
    the order-preservation assertions below would fail.
    """

    def __init__(self, responses: dict[str, str], delays: dict[str, float]) -> None:
        self._responses = responses
        self._delays = delays
        self._lock = threading.Lock()
        self.call_order: list[str] = []
        self.thread_idents: set[int] = set()

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        term = _term_from_prompt(user_prompt)
        with self._lock:
            self.call_order.append(term)
            self.thread_idents.add(threading.get_ident())
        time.sleep(self._delays.get(term, 0.0))
        return self._responses[term]


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


def test_run_mine_triages_concurrently_via_thread_pool(tmp_path: Path, monkeypatch) -> None:
    """Concurrency actually happens: with several candidates and Flash calls
    that each block for a moment, `run_mine`'s triage phase must overlap
    them across more than one thread -- not run them one at a time on the
    caller's thread, which is what the pre-parallelization serial loop did.
    """
    candidates = [
        _candidate("graphite", "Graphite was used as the moderator material."),
        _candidate("solubility", "Solubility was reported at 12 mole % BeF2."),
        _candidate("moderatedby", "The core was graphite-moderated."),
        _candidate("testminesalt", "A new compound TestMineSalt was observed in the melt."),
    ]
    monkeypatch.setattr(novelty, "mine_candidates", lambda config, reader: candidates)

    responses = {
        "graphite": json.dumps({"kind": "class", "broaderClass": "Moderator"}),
        "solubility": json.dumps({"kind": "property"}),
        "moderatedby": json.dumps(
            {"kind": "relation", "domain": "MoltenSalt", "range": "Constituent"}
        ),
        "testminesalt": json.dumps({"kind": "instance", "broaderClass": "msr:MoltenSalt"}),
    }
    # Every candidate sleeps the same modest amount inside `.complete` --
    # long enough that, if the pool ran serially, four calls would take
    # noticeably longer than the concurrent case, and long enough for
    # several worker threads to be alive at once.
    delays = {term: 0.05 for term in responses}
    completer = RecordingCompleter(responses, delays)

    reader = FakeGraphReader()
    sparql = FakeSparqlClient()
    config = Config(corpus_dir=tmp_path, disambig_concurrency=4)

    start = time.monotonic()
    summary = mine_runner.run_mine(
        config, reader=reader, client=completer, sparql=sparql, qudt_path=QUDT_PATH
    )
    elapsed = time.monotonic() - start

    # Every candidate was triaged exactly once.
    assert sorted(completer.call_order) == sorted(responses)
    # More than one worker thread actually ran `.complete` -- the hallmark
    # of real concurrency, not a bounded pool of size 1 masquerading as one.
    assert len(completer.thread_idents) > 1
    # Four 0.05s calls run concurrently comfortably finish in well under
    # 4 * 0.05s = 0.2s; a generous ceiling keeps this robust against slow
    # CI without being timing-flaky.
    assert elapsed < 0.18, f"triage calls did not appear to run concurrently: {elapsed}s"

    assert summary["dropped"] == 0
    assert summary["rejected"] == 0
    assert summary["auto_accepted"] == 1
    assert summary["proposals_by_kind"] == {"class": 1, "property": 1, "relation": 1}


def test_run_mine_preserves_candidate_order_regardless_of_triage_completion_order(
    tmp_path: Path, monkeypatch
) -> None:
    """Determinism: Phase 2's routing/writes/counts must reflect the ORIGINAL
    candidate order (`novelty.mine_candidates`' output order), never the
    order in which concurrent Flash calls happen to complete.

    Delays are set in reverse of submission order (the first-submitted
    candidate, `graphite`, sleeps longest; the last-submitted,
    `testminesalt`, returns fastest), so under real concurrency the results
    become ready in the OPPOSITE order from how they were submitted. If
    `run_mine` reassembled results in completion order instead of original
    index order, the proposal-graph writes below would come out reordered
    and this test would fail.
    """
    candidates = [
        _candidate("graphite", "Graphite was used as the moderator material."),
        _candidate("solubility", "Solubility was reported at 12 mole % BeF2."),
        _candidate("moderatedby", "The core was graphite-moderated."),
        _candidate("testminesalt", "A new compound TestMineSalt was observed in the melt."),
        _candidate("baddrop", "This candidate is triaged to an unrecognized kind."),
    ]
    monkeypatch.setattr(novelty, "mine_candidates", lambda config, reader: candidates)

    responses = {
        "graphite": json.dumps({"kind": "class", "broaderClass": "Moderator"}),
        "solubility": json.dumps({"kind": "property"}),
        "moderatedby": json.dumps(
            {"kind": "relation", "domain": "MoltenSalt", "range": "Constituent"}
        ),
        "testminesalt": json.dumps({"kind": "instance", "broaderClass": "msr:MoltenSalt"}),
        "baddrop": json.dumps({"kind": "not-a-real-kind"}),
    }
    # Reverse-of-submission-order delays: first submitted (graphite) sleeps
    # longest, last submitted (baddrop) returns immediately.
    delays = {
        "graphite": 0.08,
        "solubility": 0.06,
        "moderatedby": 0.04,
        "testminesalt": 0.02,
        "baddrop": 0.0,
    }
    completer = RecordingCompleter(responses, delays)

    reader = FakeGraphReader()
    sparql = FakeSparqlClient()
    config = Config(corpus_dir=tmp_path, disambig_concurrency=4)

    summary = mine_runner.run_mine(
        config, reader=reader, client=completer, sparql=sparql, qudt_path=QUDT_PATH
    )

    # baddrop: unrecognized kind -> a malformed-shape drop under the new
    # key contract (refine-mine-salience 7.4), distinct from both the
    # generic "dropped" bucket and an explicit triage "reject" verdict.
    assert summary["dropped_malformed"] == 1
    assert summary["dropped"] == 0
    assert summary["triage_rejected"] == 0
    assert summary["rejected"] == 0
    assert summary["auto_accepted"] == 1  # testminesalt: resolves in core (MoltenSalt)
    assert summary["proposals_by_kind"] == {"class": 1, "property": 1, "relation": 1}

    # The three proposal writes below must appear in ORIGINAL candidate
    # order (graphite, solubility, moderatedby) in `sparql.updates`, even
    # though `moderatedby`'s triage call finished before `graphite`'s.
    def _first_index(needle: str) -> int:
        return next(i for i, u in enumerate(sparql.updates) if needle in u)

    class_index = _first_index("GRAPH <urn:msr:proposal/class-graphite>")
    property_index = _first_index("GRAPH <urn:msr:proposal/property-solubility>")
    relation_index = _first_index("GRAPH <urn:msr:proposal/relation-moderatedby>")

    assert class_index < property_index < relation_index


# --- refine-mine-salience 7.4: triage reject / malformed summary keys ----


def test_run_mine_counts_triage_reject_verdict_and_writes_no_proposal(
    monkeypatch, tmp_path: Path
) -> None:
    """Scenario: "An explicit reject verdict drops the candidate"
    (candidate-triage spec) -- a well-formed {"kind": "reject"} triage
    verdict drops the candidate, increments summary["triage_rejected"]
    (distinct from the QUDT-guard "rejected" count and from a
    malformed-output drop), and writes no proposal for it."""
    candidate = _candidate("ornl", "ORNL supported this research effort in 1955.")
    monkeypatch.setattr(novelty, "mine_candidates", lambda config, reader: [candidate])

    response = json.dumps({"kind": "reject"})
    client = StubCompleter(response)
    reader = FakeGraphReader()
    sparql = FakeSparqlClient()
    config = Config(corpus_dir=tmp_path)

    summary = mine_runner.run_mine(
        config, reader=reader, client=client, sparql=sparql, qudt_path=QUDT_PATH
    )

    assert summary["triage_rejected"] == 1
    assert summary["rejected"] == 0
    assert summary["dropped_malformed"] == 0
    assert summary["dropped"] == 0
    assert summary["proposals_by_kind"] == {}
    assert summary["auto_accepted"] == 0


def test_run_mine_counts_malformed_triage_output_distinctly_from_reject(
    monkeypatch, tmp_path: Path
) -> None:
    """Scenario: "Malformed classifier output drops the candidate"
    (candidate-triage spec) -- an unrecognized/missing-kind verdict is
    counted as summary["dropped_malformed"], never folded into
    triage_rejected or the generic dropped count."""
    candidate = _candidate("gibberish", "Some gibberish OCR fragment appeared here.")
    monkeypatch.setattr(novelty, "mine_candidates", lambda config, reader: [candidate])

    response = json.dumps({"kind": "not-a-real-kind"})
    client = StubCompleter(response)
    reader = FakeGraphReader()
    sparql = FakeSparqlClient()
    config = Config(corpus_dir=tmp_path)

    summary = mine_runner.run_mine(
        config, reader=reader, client=client, sparql=sparql, qudt_path=QUDT_PATH
    )

    assert summary["dropped_malformed"] == 1
    assert summary["triage_rejected"] == 0
    assert summary["dropped"] == 0
    assert summary["rejected"] == 0
    assert summary["proposals_by_kind"] == {}
    assert summary["auto_accepted"] == 0


def test_run_mine_still_stages_legitimate_candidate_with_valid_kind_verdict(
    monkeypatch, tmp_path: Path
) -> None:
    """Scenario: "a valid kind -> proposal emitted as before" (7.4 positive
    control) -- a well-formed, routable-kind verdict is unaffected by the
    reject/malformed key split: it still produces exactly one proposal and
    increments none of the drop counters."""
    candidate = _candidate("solubility", "Solubility was reported at 12 mole % BeF2.")
    monkeypatch.setattr(novelty, "mine_candidates", lambda config, reader: [candidate])

    response = json.dumps({"kind": "property"})
    client = StubCompleter(response)
    reader = FakeGraphReader()
    sparql = FakeSparqlClient()
    config = Config(corpus_dir=tmp_path)

    summary = mine_runner.run_mine(
        config, reader=reader, client=client, sparql=sparql, qudt_path=QUDT_PATH
    )

    assert summary["proposals_by_kind"] == {"property": 1}
    assert summary["triage_rejected"] == 0
    assert summary["dropped_malformed"] == 0
    assert summary["dropped"] == 0
    assert summary["rejected"] == 0
