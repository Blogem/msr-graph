"""Backfill-migration unit tests (openspec/changes/proposal-observation-
provenance, spec proposal-observation-provenance, task 7.3).

Hermetic: a fake ``sparql`` client records every ``.update(...)`` call
(mirrors ``test_proposals_observations.py``'s ``FakeSparqlClient``); a fake
``reader`` (duck-typed against ``GraphReader.read_change_proposals``/
``count_doc_frequency_scalars``) stands in for the ``urn:msr:staging`` read.
No network, no live model, no live GraphDB. Fixture corpora are written
under ``tmp_path`` using the same helper style ``test_novelty_observations.py``
established (``config.archive_dir/*.txt`` for chemistry,
``config.safety_normalized_path`` for safety).

Pass 2 reconciliation note: this file was originally written in pass 1
against an assumed ``run_backfill(proposals, config, client, run_ts, ...)``
signature, before ``backfill_observations.py``/``graph_reader.py`` landed.
Rewritten here against the REAL, merged API:

- ``backfill_observations.run_backfill(config, *, reader=None, sparql=None,
  run_ts=BACKFILL_RUN_TS) -> BackfillSummary`` -- proposal discovery happens
  INSIDE ``run_backfill`` via ``reader.read_change_proposals()``, not via a
  caller-supplied list.
- ``graph_reader.StagedProposal(proposal_iri, kind, term)`` -- the fake
  reader below returns these directly (bypassing the real SPARQL-over-HTTP
  ``GraphReader``, mirroring how ``test_novelty_observations.py`` passes an
  empty-``select_fn`` ``GraphReader`` rather than a live one).
- The safety-genre corpus scan inside ``run_backfill`` is NOT parameterized
  by the caller -- it always re-scans every real
  ``safety_manifest.SAFETY_SOURCES`` id. A safety-genre fixture in this file
  must therefore be written under one of those REAL source ids (picked via
  ``safety_manifest.SAFETY_SOURCES[0].id``), not an arbitrary id.
- Idempotency is via the fixed ``BACKFILL_RUN_TS = "backfill"`` run token
  (deterministic observation IRIs), not a caller-varied timestamp.
"""

from __future__ import annotations

from msr_extraction import disambiguation, safety_manifest, triage
from msr_extraction.backfill_observations import BACKFILL_RUN_TS, run_backfill
from msr_extraction.config import Config
from msr_extraction.corpora import CORPUS_CHEMISTRY, CORPUS_SAFETY
from msr_extraction.graph_reader import MSRD, StagedProposal

REPORT_DOC_A = "DOC-A"
REPORT_DOC_B = "DOC-B"
REPORT_DOC_C = "DOC-C"

#: A REAL safety-manifest source id -- `run_backfill` always re-scans every
#: `safety_manifest.SAFETY_SOURCES` id itself (not caller-injectable), so a
#: safety-genre fixture must be written under one of these ids to ever be
#: seen by the scan.
SAFETY_SOURCE_ID = safety_manifest.SAFETY_SOURCES[0].id


class FakeSparqlClient:
    def __init__(self) -> None:
        self.updates: list[str] = []

    def update(self, sparql_update: str) -> None:
        self.updates.append(sparql_update)


class FakeReader:
    """Duck-typed stand-in for `graph_reader.GraphReader`'s two backfill reads."""

    def __init__(self, staged: list[StagedProposal], doc_frequency_scalars: int = 0) -> None:
        self._staged = staged
        self._doc_frequency_scalars = doc_frequency_scalars

    def read_change_proposals(self) -> list[StagedProposal]:
        return list(self._staged)

    def count_doc_frequency_scalars(self) -> int:
        return self._doc_frequency_scalars


def _write_archive_docs(config: Config, docs: dict[str, str]) -> None:
    config.archive_dir.mkdir(parents=True, exist_ok=True)
    for name, text in docs.items():
        (config.archive_dir / name).write_text(text, encoding="utf-8")


def _write_safety_normalized(config: Config, source_id: str, text: str) -> None:
    path = config.safety_normalized_path(source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _combined_text(client: FakeSparqlClient) -> str:
    return "\n".join(client.updates)


def _proposal_iri(term: str, kind: str = "property") -> str:
    return f"{MSRD}proposal-{kind}-{term}"


# --- inference-free ---------------------------------------------------


def test_backfill_never_invokes_triage_or_llm(monkeypatch, tmp_path) -> None:
    """Scenario: "Backfill reconstructs observations without triage" -- the
    backfill re-scans and writes observations without any LLM/triage call.
    Monkeypatches the two possible inference entry points to raise if
    called at all, then asserts the backfill still completes and writes
    observations -- proving neither was invoked, regardless of whether
    backfill_observations.py even imports those modules."""

    def _boom_triage(*args, **kwargs):
        raise AssertionError("backfill must never call triage.triage_candidate")

    def _boom_flash_init(self, *args, **kwargs):
        raise AssertionError("backfill must never construct disambiguation.FlashClient")

    monkeypatch.setattr(triage, "triage_candidate", _boom_triage)
    monkeypatch.setattr(disambiguation.FlashClient, "__init__", _boom_flash_init)

    config = Config(corpus_dir=tmp_path)
    _write_archive_docs(config, {f"{REPORT_DOC_A}.txt": "keepterm appears here"})

    reader = FakeReader([StagedProposal(proposal_iri=_proposal_iri("keepterm"), kind="property", term="keepterm")])
    sparql = FakeSparqlClient()

    summary = run_backfill(config, reader=reader, sparql=sparql)

    assert summary.proposals_processed == 1
    assert summary.observations_written >= 1
    assert sparql.updates, "backfill must write at least one update for a matched term"


# --- deterministic document-frequency reproduction ---------------------


def test_backfill_reproduces_known_document_frequency(tmp_path) -> None:
    """A fixture proposal whose term appears in N fixture documents gains N
    per-document observations reproducing that document frequency (design.md
    D4: "reconstructed counts reproduce the original docFrequency values"),
    with the exact per-document occurrence count (term frequency, D5)."""
    config = Config(corpus_dir=tmp_path)
    _write_archive_docs(
        config,
        {
            f"{REPORT_DOC_A}.txt": "keepterm appears keepterm here keepterm again",  # 3
            f"{REPORT_DOC_B}.txt": "keepterm shows up here once",  # 1
            f"{REPORT_DOC_C}.txt": "no match in this document at all",  # 0
        },
    )

    reader = FakeReader([StagedProposal(proposal_iri=_proposal_iri("keepterm"), kind="property", term="keepterm")])
    sparql = FakeSparqlClient()

    summary = run_backfill(config, reader=reader, sparql=sparql)

    text = _combined_text(sparql)
    assert REPORT_DOC_A in text
    assert REPORT_DOC_B in text
    assert REPORT_DOC_C not in text  # zero-occurrence document contributes nothing
    assert text.count("msr:inDocument") == 2  # exactly 2 distinct matching documents
    assert '"3"^^xsd:integer' in text
    assert '"1"^^xsd:integer' in text
    assert CORPUS_CHEMISTRY in text
    assert summary.observations_written == 2


# --- cross-corpus split -------------------------------------------------


def test_backfill_splits_a_cross_corpus_term_by_corpus(tmp_path) -> None:
    """Scenario: "A previously duplicated proposal is split by corpus" -- a
    term present in BOTH a chemistry fixture document and a REAL safety
    source's normalized text yields observations attributed to the correct,
    distinct corpora on the SAME proposal resource."""
    config = Config(corpus_dir=tmp_path)
    _write_archive_docs(config, {f"{REPORT_DOC_A}.txt": "crossterm appears here"})
    _write_safety_normalized(config, SAFETY_SOURCE_ID, "crossterm appears here too")

    reader = FakeReader([StagedProposal(proposal_iri=_proposal_iri("crossterm"), kind="property", term="crossterm")])
    sparql = FakeSparqlClient()

    summary = run_backfill(config, reader=reader, sparql=sparql)

    text = _combined_text(sparql)
    assert CORPUS_CHEMISTRY in text
    assert CORPUS_SAFETY in text
    assert text.count("msr:inDocument") == 2  # one chemistry + one safety observation
    assert summary.observations_written == 2
    assert summary.documents_tagged == 2


# --- idempotency ---------------------------------------------------------


def test_backfill_is_idempotent_on_rerun(tmp_path) -> None:
    """Re-running the backfill (same staged proposals, same corpus, the
    default fixed BACKFILL_RUN_TS) must not duplicate observations --
    deterministic observation IRIs make a re-run a set-semantics no-op, so
    two independent runs produce byte-identical generated updates (mirrors
    ``test_proposals_observations.py``'s same-run_ts idempotency pattern)."""
    config = Config(corpus_dir=tmp_path)
    _write_archive_docs(config, {f"{REPORT_DOC_A}.txt": "keepterm keepterm here"})

    def _reader() -> FakeReader:
        return FakeReader(
            [StagedProposal(proposal_iri=_proposal_iri("keepterm"), kind="property", term="keepterm")]
        )

    sparql_a, sparql_b = FakeSparqlClient(), FakeSparqlClient()
    summary_a = run_backfill(config, reader=_reader(), sparql=sparql_a)
    summary_b = run_backfill(config, reader=_reader(), sparql=sparql_b)

    assert sparql_a.updates == sparql_b.updates
    assert summary_a == summary_b
    assert BACKFILL_RUN_TS in _combined_text(sparql_a)


# --- stale docFrequency scalar removal -----------------------------------


def test_backfill_removes_stale_docfrequency_scalar(tmp_path) -> None:
    """After backfill, the stale msr:docFrequency scalar is removed (design.md
    D4/D3, task 4.3): the generated updates must include a removal targeting
    msr:docFrequency (a DELETE, not merely an INSERT that leaves the old
    scalar in place alongside the new observations), and the summary reports
    how many scalars were removed."""
    config = Config(corpus_dir=tmp_path)
    _write_archive_docs(config, {f"{REPORT_DOC_A}.txt": "keepterm here"})

    reader = FakeReader(
        [StagedProposal(proposal_iri=_proposal_iri("keepterm"), kind="property", term="keepterm")],
        doc_frequency_scalars=3,
    )
    sparql = FakeSparqlClient()

    summary = run_backfill(config, reader=reader, sparql=sparql)

    text = _combined_text(sparql)
    assert "docFrequency" in text
    assert "DELETE" in text.upper()
    assert summary.doc_frequency_scalars_removed == 3


def test_backfill_skips_the_delete_when_no_stale_scalars_remain(tmp_path) -> None:
    """No stale msr:docFrequency scalars in urn:msr:staging -> no DELETE is
    sent at all (never an unconditional no-op DELETE on every run)."""
    config = Config(corpus_dir=tmp_path)
    _write_archive_docs(config, {f"{REPORT_DOC_A}.txt": "keepterm here"})

    reader = FakeReader(
        [StagedProposal(proposal_iri=_proposal_iri("keepterm"), kind="property", term="keepterm")],
        doc_frequency_scalars=0,
    )
    sparql = FakeSparqlClient()

    summary = run_backfill(config, reader=reader, sparql=sparql)

    assert "docFrequency" not in _combined_text(sparql)
    assert summary.doc_frequency_scalars_removed == 0


# --- document corpus tagging ---------------------------------------------


def test_backfill_tags_scanned_documents_with_corpus(tmp_path) -> None:
    """Task 4.2: matched documents are tagged with msr:inCorpus for their
    genre's corpus -- a matched chemistry document ends up associated with
    msrd:corpus-chemistry and a matched (real) safety source with
    msrd:corpus-safety somewhere in the generated updates."""
    config = Config(corpus_dir=tmp_path)
    _write_archive_docs(config, {f"{REPORT_DOC_A}.txt": "keepterm here"})
    _write_safety_normalized(config, SAFETY_SOURCE_ID, "keepterm here too")

    reader = FakeReader([StagedProposal(proposal_iri=_proposal_iri("keepterm"), kind="property", term="keepterm")])
    sparql = FakeSparqlClient()

    summary = run_backfill(config, reader=reader, sparql=sparql)

    text = _combined_text(sparql)
    assert "msr:inCorpus" in text
    assert REPORT_DOC_A in text and CORPUS_CHEMISTRY in text
    assert SAFETY_SOURCE_ID in text and CORPUS_SAFETY in text
    assert summary.documents_tagged == 2


# --- no fabricated observations for a non-matching term ------------------


def test_backfill_writes_nothing_for_a_proposal_term_with_zero_hits(tmp_path) -> None:
    """A proposal whose stored term no longer matches anything in the cached
    corpora (e.g. corpus drift) must not fabricate an observation -- no
    msr:inDocument for a document that never contained the term, and the
    summary reports zero observations written."""
    config = Config(corpus_dir=tmp_path)
    _write_archive_docs(config, {f"{REPORT_DOC_A}.txt": "totally unrelated content"})

    reader = FakeReader(
        [StagedProposal(proposal_iri=_proposal_iri("nomatchterm"), kind="property", term="nomatchterm")]
    )
    sparql = FakeSparqlClient()

    summary = run_backfill(config, reader=reader, sparql=sparql)

    assert "msr:inDocument" not in _combined_text(sparql)
    assert summary.observations_written == 0
    assert summary.proposals_processed == 1
