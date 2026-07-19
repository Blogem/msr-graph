"""Hermetic end-to-end smoke test for the `link` CLI umbrella (`cli._cmd_link`).

Every other test covering `_cmd_link`'s collaborators (`GraphReader`,
`linker`, `mentions`, `disambiguation`, ...) exercises them piecewise; this
module is the missing end-to-end pass over the actual dispatcher, verifying
the whole wiring holds together without ever touching a live GraphDB or
model. `cli.main(["link"])` is driven directly, with the three collaborator
factories `_cmd_link` constructs (`GraphReader.from_config`,
`SparqlClient.from_config`, `FlashClient.from_config`) monkeypatched to
hermetic fakes in the `cli` module namespace, and `curated.CURATED_REPORTS`
monkeypatched to a single synthetic report so only the tmp-dir corpus this
test writes is processed. A real spaCy-backed matcher
(`seeding.build_matcher`) still runs -- only the network-touching
collaborators are faked.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from msr_extraction import cli, curated
from msr_extraction.graph_reader import KnownEntity

VISCOSITY_IRI = "https://w3id.org/msr-kg/vocab#viscosity"
SALT_IRI = "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"
REPORT = "ORNL-TM-2316"


class _FakeGraphReader:
    """Hermetic stand-in for `GraphReader`: a fixed in-memory known-entity set.

    Implements exactly the surface `_cmd_link`/`KGSchemaPromptCache` need
    (`read_known_entities`, `read_version`, `known_iris`) -- no network.
    """

    def __init__(self, known: list[KnownEntity]) -> None:
        self._known = known

    def read_known_entities(self) -> list[KnownEntity]:
        return list(self._known)

    def read_version(self) -> str:
        return "v1"

    def known_iris(self) -> set[str]:
        return {entity.target_iri for entity in self._known}


class _FakeSparqlClient:
    """Records every `update(sparql)` call instead of hitting a live GraphDB."""

    def __init__(self) -> None:
        self.updates: list[str] = []

    def update(self, sparql_update: str) -> None:
        self.updates.append(sparql_update)


def _known_entities() -> list[KnownEntity]:
    return [
        KnownEntity(target_iri=VISCOSITY_IRI, labels=("viscosity",), kind="concept"),
        KnownEntity(
            target_iri=SALT_IRI,
            labels=("BeF2-LiF (34.0-66.0 mol%)", "LiF-BeF2"),
            kind="salt",
        ),
    ]


def test_cmd_link_smoke_links_report_writes_mentions_and_graph(tmp_path, monkeypatch) -> None:
    """`cli.main(["link"])` runs the full link pipeline hermetically end-to-end.

    Points the corpus at a tmp dir holding one synthetic segment, fakes the
    graph reader / SPARQL update client / Flash client `_cmd_link`
    constructs, and restricts `curated.CURATED_REPORTS` to that one
    synthetic report. Asserts: `main` returns 0; the on-disk
    `mentions.jsonl` contains a linked record for the `viscosity` concept
    and one for the composed `LiF-BeF2 (66-34 mol%)` mention resolving to
    the loaded salt individual; the fake SparqlClient received an
    `INSERT DATA { GRAPH <urn:msr:data> { ... } }` update describing at
    least one `msr:Mention`.
    """
    monkeypatch.setenv("MSR_CORPUS_DIR", str(tmp_path))
    monkeypatch.setattr(curated, "CURATED_REPORTS", [REPORT])

    known = _known_entities()
    monkeypatch.setattr(
        cli,
        "GraphReader",
        SimpleNamespace(from_config=lambda config: _FakeGraphReader(known)),
    )

    fake_sparql = _FakeSparqlClient()
    monkeypatch.setattr(
        cli,
        "SparqlClient",
        SimpleNamespace(from_config=lambda config: fake_sparql),
    )

    # No DeepSeek client configured -> layer 5 candidate spans fall to
    # "novel"; no network call is ever attempted.
    monkeypatch.setattr(cli, "FlashClient", SimpleNamespace(from_config=lambda config: None))

    report_dir = tmp_path / REPORT
    report_dir.mkdir(parents=True)
    text = "The viscosity of LiF-BeF2 (66-34 mol%) was measured."
    segment = {
        "report": REPORT,
        "index": 0,
        "text": text,
        "char_start": 0,
        "char_end": len(text),
    }
    (report_dir / "segments.jsonl").write_text(json.dumps(segment) + "\n", encoding="utf-8")

    result = cli.main(["link"])
    assert result == 0

    mentions_path = report_dir / "mentions.jsonl"
    assert mentions_path.exists(), "expected _cmd_link to write mentions.jsonl"

    records = [
        json.loads(line)
        for line in mentions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    linked = [r for r in records if r["status"] == "linked"]

    viscosity_records = [r for r in linked if r["target_iri"] == VISCOSITY_IRI]
    assert viscosity_records, f"expected a linked viscosity record, got: {records}"
    assert viscosity_records[0]["surface_form"].lower() == "viscosity"

    salt_records = [r for r in linked if r["target_iri"] == SALT_IRI]
    assert salt_records, f"expected a linked composed-salt record, got: {records}"

    assert fake_sparql.updates, "expected at least one SPARQL UPDATE call"
    assert any(
        "INSERT DATA {" in update and "GRAPH <urn:msr:data>" in update and "a msr:Mention" in update
        for update in fake_sparql.updates
    ), f"expected an INSERT DATA update against urn:msr:data with a msr:Mention, got: {fake_sparql.updates}"
