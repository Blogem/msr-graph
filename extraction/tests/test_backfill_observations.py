"""Backfill-migration unit tests (openspec/changes/proposal-observation-
provenance, spec proposal-observation-provenance, task 7.3).

Hermetic: a fake SPARQL client records every ``.update(...)`` call (mirrors
``test_proposals_observations.py``'s ``FakeSparqlClient``); no network, no
live model, no live GraphDB. Fixture corpora are written under ``tmp_path``
using the same helper style ``test_novelty_observations.py`` established
(``config.archive_dir/*.txt`` for chemistry, ``config.safety_normalized_path``
for safety).

ASSUMPTION (pass-1, flagged for reconciliation at merge): this pass runs
BEFORE the coder's ``backfill_observations.py`` module (task 4) lands, so
every test below is written against the following assumed public contract
(design.md D1/D4/D5/D6, tasks 4.1-4.3, and the shared task-contract prompt),
not against any implementation. If the coder's actual module names things
differently, pass 2 reconciles by adjusting only the import / call-site
names below -- the assertions (what must be true of the generated SPARQL
and the inference-free guarantee) come from the spec and should not need to
change.

Assumed contract::

    from msr_extraction.backfill_observations import run_backfill

    run_backfill(
        proposals,       # list[tuple[str, str]] of (term, kind) for every
                         # already-staged msr:ChangeProposal to reconstruct
                         # observations for -- discovery of this list (a
                         # SPARQL SELECT over urn:msr:staging) is the CLI
                         # wrapper's job (task 4.4), not this function's;
                         # this function only re-scans corpora + writes.
        config,          # Config -- source of archive_dir/safety paths
        client,          # SparqlClient (or duck-typed .update(str)) -- the
                         # only I/O this function performs
        run_ts,          # str -- the backfill's own run/generation
                         # timestamp; passing the SAME run_ts twice must
                         # reproduce byte-identical generated updates
                         # (idempotent re-run, design.md "Risks" section)
        *,
        chemistry_reports=None,  # list[str] | None -- report ids to re-scan
                                  # for the chemistry corpus (defaults to
                                  # every archive_dir *.txt sidecar if None)
        safety_reports=None,     # list[str] | None -- source ids to re-scan
                                  # for the safety corpus
    )

Each test below only relies on the observable SPARQL text the fake client
receives (``msr:inDocument``/``msr:occurrenceCount``/``msr:inCorpus``/
``msr:hasObservation``/``msr:docFrequency``-removal/corpus CURIEs), not on
any exact observation-IRI suffix or internal helper name, so the suite stays
robust to the coder's exact internal structure while still pinning the
spec-mandated invariants (inference-free, DF reproduction, corpus split,
idempotent re-run, stale-scalar removal).
"""

from __future__ import annotations

from msr_extraction import corpora, disambiguation, triage
from msr_extraction.config import Config

REPORT_DOC_A = "DOC-A"
REPORT_DOC_B = "DOC-B"
REPORT_DOC_C = "DOC-C"
SAFETY_SRC_A = "SAFETY-A"
RUN_TS = "2026-07-21T00:00:00+00:00"


class FakeSparqlClient:
    def __init__(self) -> None:
        self.updates: list[str] = []

    def update(self, sparql_update: str) -> None:
        self.updates.append(sparql_update)


def _write_archive_docs(config: Config, docs: dict[str, str]) -> None:
    config.archive_dir.mkdir(parents=True, exist_ok=True)
    for name, text in docs.items():
        (config.archive_dir / name).write_text(text, encoding="utf-8")


def _write_safety_normalized(config: Config, source_id: str, text: str) -> None:
    path = config.safety_normalized_path(source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _import_run_backfill():
    """Import the assumed entry point, failing with a clear message if the
    coder named it differently -- this is the single reconciliation point
    pass 2 needs to touch if the name/signature differs."""
    from msr_extraction.backfill_observations import run_backfill

    return run_backfill


def _combined_text(client: FakeSparqlClient) -> str:
    return "\n".join(client.updates)


# --- inference-free ---------------------------------------------------


def test_backfill_never_invokes_triage_or_llm(monkeypatch, tmp_path) -> None:
    """Scenario: "Backfill reconstructs observations without triage" -- the
    backfill re-scans and writes observations without any LLM/triage call.
    Monkeypatches the two possible inference entry points to raise if
    called at all, then asserts the backfill still completes and writes
    observations -- proving neither was invoked, regardless of whether
    backfill_observations.py even imports those modules."""
    run_backfill = _import_run_backfill()

    def _boom_triage(*args, **kwargs):
        raise AssertionError("backfill must never call triage.triage_candidate")

    def _boom_flash_init(self, *args, **kwargs):
        raise AssertionError("backfill must never construct disambiguation.FlashClient")

    monkeypatch.setattr(triage, "triage_candidate", _boom_triage)
    monkeypatch.setattr(disambiguation.FlashClient, "__init__", _boom_flash_init)

    config = Config(corpus_dir=tmp_path)
    _write_archive_docs(config, {f"{REPORT_DOC_A}.txt": "keepterm appears here"})

    client = FakeSparqlClient()
    run_backfill(
        [("keepterm", "property")],
        config,
        client,
        RUN_TS,
        chemistry_reports=[REPORT_DOC_A],
        safety_reports=[],
    )

    assert client.updates, "backfill must write at least one update for a matched term"
    assert "msr:hasObservation" in _combined_text(client) or "msr:inDocument" in _combined_text(client)


# --- deterministic document-frequency reproduction ---------------------


def test_backfill_reproduces_known_document_frequency(tmp_path) -> None:
    """A fixture proposal whose term appears in N fixture documents gains N
    per-document observations reproducing that document frequency (design.md
    D4: "reconstructed counts reproduce the original docFrequency values"),
    with the exact per-document occurrence count (term frequency, D5)."""
    run_backfill = _import_run_backfill()

    config = Config(corpus_dir=tmp_path)
    _write_archive_docs(
        config,
        {
            f"{REPORT_DOC_A}.txt": "keepterm appears keepterm here keepterm again",  # 3
            f"{REPORT_DOC_B}.txt": "keepterm shows up here once",  # 1
            f"{REPORT_DOC_C}.txt": "no match in this document at all",  # 0
        },
    )

    client = FakeSparqlClient()
    run_backfill(
        [("keepterm", "property")],
        config,
        client,
        RUN_TS,
        chemistry_reports=[REPORT_DOC_A, REPORT_DOC_B, REPORT_DOC_C],
        safety_reports=[],
    )

    text = _combined_text(client)
    assert REPORT_DOC_A in text
    assert REPORT_DOC_B in text
    assert REPORT_DOC_C not in text  # zero-occurrence document contributes nothing
    assert text.count("msr:inDocument") == 2  # exactly 2 distinct matching documents
    assert '"3"^^xsd:integer' in text
    assert '"1"^^xsd:integer' in text
    assert corpora.CORPUS_CHEMISTRY in text


# --- cross-corpus split -------------------------------------------------


def test_backfill_splits_a_cross_corpus_term_by_corpus(tmp_path) -> None:
    """Scenario: "A previously duplicated proposal is split by corpus" -- a
    term present in BOTH a chemistry and a safety fixture document yields
    observations attributed to the correct, distinct corpora."""
    run_backfill = _import_run_backfill()

    config = Config(corpus_dir=tmp_path)
    _write_archive_docs(config, {f"{REPORT_DOC_A}.txt": "crossterm appears here"})
    _write_safety_normalized(config, SAFETY_SRC_A, "crossterm appears here too")

    client = FakeSparqlClient()
    run_backfill(
        [("crossterm", "property")],
        config,
        client,
        RUN_TS,
        chemistry_reports=[REPORT_DOC_A],
        safety_reports=[SAFETY_SRC_A],
    )

    text = _combined_text(client)
    assert corpora.CORPUS_CHEMISTRY in text
    assert corpora.CORPUS_SAFETY in text
    assert text.count("msr:inDocument") == 2  # one chemistry + one safety observation


# --- idempotency ---------------------------------------------------------


def test_backfill_is_idempotent_on_rerun(tmp_path) -> None:
    """Re-running the backfill (same proposals, same corpus, same run_ts)
    must not duplicate observations -- either deterministic observation
    IRIs (a re-run is a set-semantics no-op) or a clear-then-rewrite
    strategy; either way, two independent runs produce byte-identical
    generated updates (mirrors ``test_proposals_observations.py``'s
    same-run_ts idempotency pattern)."""
    run_backfill = _import_run_backfill()

    config = Config(corpus_dir=tmp_path)
    _write_archive_docs(config, {f"{REPORT_DOC_A}.txt": "keepterm keepterm here"})

    client_a, client_b = FakeSparqlClient(), FakeSparqlClient()
    run_backfill(
        [("keepterm", "property")],
        config,
        client_a,
        RUN_TS,
        chemistry_reports=[REPORT_DOC_A],
        safety_reports=[],
    )
    run_backfill(
        [("keepterm", "property")],
        config,
        client_b,
        RUN_TS,
        chemistry_reports=[REPORT_DOC_A],
        safety_reports=[],
    )

    assert client_a.updates == client_b.updates


# --- stale docFrequency scalar removal -----------------------------------


def test_backfill_removes_stale_docfrequency_scalar(tmp_path) -> None:
    """After backfill, the stale msr:docFrequency scalar is removed (design.md
    D4/D3, task 4.3): the generated updates must include a removal targeting
    msr:docFrequency (a DELETE, not merely an INSERT that leaves the old
    scalar in place alongside the new observations)."""
    run_backfill = _import_run_backfill()

    config = Config(corpus_dir=tmp_path)
    _write_archive_docs(config, {f"{REPORT_DOC_A}.txt": "keepterm here"})

    client = FakeSparqlClient()
    run_backfill(
        [("keepterm", "property")],
        config,
        client,
        RUN_TS,
        chemistry_reports=[REPORT_DOC_A],
        safety_reports=[],
    )

    text = _combined_text(client)
    assert "docFrequency" in text
    assert "DELETE" in text.upper()


# --- document corpus tagging ---------------------------------------------


def test_backfill_tags_scanned_documents_with_corpus(tmp_path) -> None:
    """Task 4.2: scanned documents are tagged with msr:inCorpus for their
    genre's corpus -- a matched chemistry document ends up associated with
    msrd:corpus-chemistry and a matched safety document with
    msrd:corpus-safety somewhere in the generated updates (either via the
    observation's own msr:inCorpus predicate, or a standalone
    documents.write_corpus_tags-style update -- this test only pins that the
    tagging triple exists for each matched document, not which writer
    produced it)."""
    run_backfill = _import_run_backfill()

    config = Config(corpus_dir=tmp_path)
    _write_archive_docs(config, {f"{REPORT_DOC_A}.txt": "keepterm here"})
    _write_safety_normalized(config, SAFETY_SRC_A, "keepterm here too")

    client = FakeSparqlClient()
    run_backfill(
        [("keepterm", "property")],
        config,
        client,
        RUN_TS,
        chemistry_reports=[REPORT_DOC_A],
        safety_reports=[SAFETY_SRC_A],
    )

    text = _combined_text(client)
    assert "msr:inCorpus" in text
    assert REPORT_DOC_A in text and corpora.CORPUS_CHEMISTRY in text
    assert SAFETY_SRC_A in text and corpora.CORPUS_SAFETY in text


# --- no fabricated observations for a non-matching document -------------


def test_backfill_writes_nothing_for_a_proposal_term_with_zero_hits(tmp_path) -> None:
    """A proposal whose stored term no longer matches anything in the cached
    corpora (e.g. corpus drift) must not fabricate an observation -- no
    msr:inDocument for a document that never contained the term."""
    run_backfill = _import_run_backfill()

    config = Config(corpus_dir=tmp_path)
    _write_archive_docs(config, {f"{REPORT_DOC_A}.txt": "totally unrelated content"})

    client = FakeSparqlClient()
    run_backfill(
        [("nomatchterm", "property")],
        config,
        client,
        RUN_TS,
        chemistry_reports=[REPORT_DOC_A],
        safety_reports=[],
    )

    text = _combined_text(client)
    assert "msr:inDocument" not in text
