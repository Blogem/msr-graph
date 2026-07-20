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
import re
import threading
import time
from types import SimpleNamespace

import pytest

from msr_extraction import cli, curated
from msr_extraction.graph_reader import KnownEntity

VISCOSITY_IRI = "https://w3id.org/msr-kg/vocab#viscosity"
SALT_IRI = "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"
REPORT = "ORNL-TM-2316"
REPORT_2 = "ORNL-TM-0728"


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


class _CountingFlashClient:
    """Fake `Completer` recording every `complete()` call's mention surface.

    Always declares the span novel, so layer 5 records it as novel without
    linking -- this test only cares about *how many* model calls happen and
    for which surface (parsed out of the `Mention: "..."` line the
    disambiguation user prompt embeds).
    """

    def __init__(self) -> None:
        self.surfaces: list[str] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        match = re.search(r'Mention: "([^"]*)"', user_prompt)
        self.surfaces.append(match.group(1) if match else "")
        return json.dumps({"novel": True})


class _LinkingFlashClient:
    """Fake `Completer` that always links to a fixed IRI."""

    def __init__(self, target_iri: str) -> None:
        self.target_iri = target_iri

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        return json.dumps({"link": self.target_iri})


class _ConcurrencyTrackingFlashClient:
    """Fake `Completer` recording the peak number of concurrent `complete()`
    calls, to prove the pre-warm pool runs more than one at a time."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls = 0

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        with self._lock:
            self.in_flight += 1
            self.calls += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        time.sleep(0.1)
        with self._lock:
            self.in_flight -= 1
        return json.dumps({"novel": True})


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


def test_cmd_link_memoizes_disambiguation_by_surface(tmp_path, monkeypatch) -> None:
    """Layer-5 disambiguation is memoized per surface within a run.

    A single segment mentions the unresolved salt-shaped span "NaCl-KCl"
    twice and "KF-ZrF4" once (both separator-joined formulas, so they are
    candidate spans, but absent from `_known_entities`, so they fall through
    layers 2-4 to layer 5; the surrounding words are lowercase so they are
    not themselves candidates). The counting Flash fake proves the second
    "NaCl-KCl" was served from cache: it produces two mention records but
    only one model call, and no surface is ever sent to the model twice.
    """
    monkeypatch.setenv("MSR_CORPUS_DIR", str(tmp_path))
    monkeypatch.setattr(curated, "CURATED_REPORTS", [REPORT])

    known = _known_entities()
    monkeypatch.setattr(
        cli,
        "GraphReader",
        SimpleNamespace(from_config=lambda config: _FakeGraphReader(known)),
    )
    monkeypatch.setattr(
        cli,
        "SparqlClient",
        SimpleNamespace(from_config=lambda config: _FakeSparqlClient()),
    )
    fake_flash = _CountingFlashClient()
    monkeypatch.setattr(
        cli,
        "FlashClient",
        SimpleNamespace(from_config=lambda config: fake_flash),
    )

    report_dir = tmp_path / REPORT
    report_dir.mkdir(parents=True)
    text = "molten NaCl-KCl was tested. later NaCl-KCl again, and KF-ZrF4 too."
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

    records = [
        json.loads(line)
        for line in (report_dir / "mentions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    nacl_records = [r for r in records if r["surface_form"] == "NaCl-KCl"]
    assert len(nacl_records) == 2, f"expected NaCl-KCl to be mentioned twice, got: {records}"

    # ...yet Flash was called only once for NaCl-KCl (second occurrence
    # cached), KF-ZrF4 once, and no surface was ever sent to the model twice.
    assert fake_flash.surfaces.count("NaCl-KCl") == 1, fake_flash.surfaces
    assert fake_flash.surfaces.count("KF-ZrF4") == 1, fake_flash.surfaces
    assert len(fake_flash.surfaces) == len(set(fake_flash.surfaces)), (
        f"a surface was sent to Flash more than once (cache miss): {fake_flash.surfaces}"
    )


def test_cmd_link_prewarm_linked_outcome_flows_into_mentions(tmp_path, monkeypatch) -> None:
    """A disambiguation that returns a link resolves the span in the real
    pass: the concurrent pre-warm populates the cache, and the caching
    disambiguator applies the linked outcome to the layer-5 mention record."""
    monkeypatch.setenv("MSR_CORPUS_DIR", str(tmp_path))
    monkeypatch.setattr(curated, "CURATED_REPORTS", [REPORT])

    known = _known_entities()
    monkeypatch.setattr(
        cli, "GraphReader",
        SimpleNamespace(from_config=lambda config: _FakeGraphReader(known)),
    )
    monkeypatch.setattr(
        cli, "SparqlClient",
        SimpleNamespace(from_config=lambda config: _FakeSparqlClient()),
    )
    monkeypatch.setattr(
        cli, "FlashClient",
        SimpleNamespace(from_config=lambda config: _LinkingFlashClient(SALT_IRI)),
    )

    report_dir = tmp_path / REPORT
    report_dir.mkdir(parents=True)
    text = "molten NaCl-KCl was tested."
    segment = {"report": REPORT, "index": 0, "text": text, "char_start": 0, "char_end": len(text)}
    (report_dir / "segments.jsonl").write_text(json.dumps(segment) + "\n", encoding="utf-8")

    assert cli.main(["link"]) == 0

    records = [
        json.loads(line)
        for line in (report_dir / "mentions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    nacl = [r for r in records if r["surface_form"] == "NaCl-KCl"]
    assert nacl, f"expected a NaCl-KCl record, got: {records}"
    assert nacl[0]["status"] == "linked"
    assert nacl[0]["target_iri"] == SALT_IRI
    assert nacl[0]["layer"] == 5


def test_cmd_link_prewarm_resolves_surfaces_concurrently(tmp_path, monkeypatch) -> None:
    """Several distinct unresolved surfaces are resolved by the pre-warm pool
    with more than one model call in flight at once (not strictly serial)."""
    monkeypatch.setenv("MSR_CORPUS_DIR", str(tmp_path))
    monkeypatch.setenv("MSR_DISAMBIG_CONCURRENCY", "8")
    monkeypatch.setattr(curated, "CURATED_REPORTS", [REPORT])

    known = _known_entities()
    monkeypatch.setattr(
        cli, "GraphReader",
        SimpleNamespace(from_config=lambda config: _FakeGraphReader(known)),
    )
    monkeypatch.setattr(
        cli, "SparqlClient",
        SimpleNamespace(from_config=lambda config: _FakeSparqlClient()),
    )
    fake = _ConcurrencyTrackingFlashClient()
    monkeypatch.setattr(
        cli, "FlashClient",
        SimpleNamespace(from_config=lambda config: fake),
    )

    report_dir = tmp_path / REPORT
    report_dir.mkdir(parents=True)
    # Four distinct salt-shaped spans, none in _known_entities -> all reach
    # layer 5 and are pending together in the pre-warm pool.
    text = "melts NaCl-KCl and KF-ZrF4 and MgF2-CaF2 and RbF-CsF were compared."
    segment = {"report": REPORT, "index": 0, "text": text, "char_start": 0, "char_end": len(text)}
    (report_dir / "segments.jsonl").write_text(json.dumps(segment) + "\n", encoding="utf-8")

    assert cli.main(["link"]) == 0

    assert fake.calls == 4, f"expected one call per distinct surface, got {fake.calls}"
    assert fake.max_in_flight >= 2, (
        f"expected concurrent resolution, peak in-flight was {fake.max_in_flight}"
    )


# --- `_resolve_link_reports` (pure helper) -----------------------------------


def test_resolve_link_reports_no_flags_returns_all_in_order() -> None:
    all_reports = ["A", "B", "C"]
    assert cli._resolve_link_reports(all_reports, None, None) == all_reports


def test_resolve_link_reports_report_filter_preserves_curated_order() -> None:
    all_reports = ["A", "B", "C", "D"]
    # Requested out of order; result follows all_reports order, not request order.
    assert cli._resolve_link_reports(all_reports, ["C", "A"], None) == ["A", "C"]


def test_resolve_link_reports_unknown_report_raises_value_error() -> None:
    all_reports = ["A", "B", "C"]
    with pytest.raises(ValueError, match="BOGUS"):
        cli._resolve_link_reports(all_reports, ["A", "BOGUS"], None)


def test_resolve_link_reports_limit_takes_first_n() -> None:
    all_reports = ["A", "B", "C"]
    assert cli._resolve_link_reports(all_reports, None, 2) == ["A", "B"]


def test_resolve_link_reports_report_and_limit_filters_then_limits() -> None:
    all_reports = ["A", "B", "C", "D"]
    assert cli._resolve_link_reports(all_reports, ["D", "B", "C"], 2) == ["B", "C"]


@pytest.mark.parametrize("limit", [0, -1])
def test_resolve_link_reports_nonpositive_limit_raises_value_error(limit: int) -> None:
    all_reports = ["A", "B", "C"]
    with pytest.raises(ValueError, match="--limit"):
        cli._resolve_link_reports(all_reports, None, limit)


# --- CLI `--report`/`--limit` selection --------------------------------------


def _write_segment(report_dir, report: str, text: str) -> None:
    report_dir.mkdir(parents=True)
    segment = {
        "report": report,
        "index": 0,
        "text": text,
        "char_start": 0,
        "char_end": len(text),
    }
    (report_dir / "segments.jsonl").write_text(json.dumps(segment) + "\n", encoding="utf-8")


def _patch_link_collaborators(monkeypatch) -> _FakeSparqlClient:
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
    monkeypatch.setattr(cli, "FlashClient", SimpleNamespace(from_config=lambda config: None))
    return fake_sparql


def test_cmd_link_report_flag_processes_only_selected_report(tmp_path, monkeypatch) -> None:
    """`cli.main(["link", "--report", REPORT])` with two curated reports on
    disk only writes `mentions.jsonl` for the selected report."""
    monkeypatch.setenv("MSR_CORPUS_DIR", str(tmp_path))
    monkeypatch.setattr(curated, "CURATED_REPORTS", [REPORT, REPORT_2])
    _patch_link_collaborators(monkeypatch)

    text = "The viscosity of LiF-BeF2 (66-34 mol%) was measured."
    _write_segment(tmp_path / REPORT, REPORT, text)
    _write_segment(tmp_path / REPORT_2, REPORT_2, text)

    result = cli.main(["link", "--report", REPORT])
    assert result == 0

    assert (tmp_path / REPORT / "mentions.jsonl").exists()
    assert not (tmp_path / REPORT_2 / "mentions.jsonl").exists()


def test_cmd_link_unknown_report_flag_returns_nonzero(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MSR_CORPUS_DIR", str(tmp_path))
    monkeypatch.setattr(curated, "CURATED_REPORTS", [REPORT])
    _patch_link_collaborators(monkeypatch)

    result = cli.main(["link", "--report", "BOGUS"])
    assert result != 0
    assert not (tmp_path / REPORT / "mentions.jsonl").exists()
