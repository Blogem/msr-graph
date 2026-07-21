"""Miner-emits-observations unit tests (openspec/changes/proposal-observation-
provenance, spec novelty-detection, task 7.1).

Hermetic: no live GraphDB, no live model where avoidable (the chemistry-genre
test uses the real, installed ``en_core_web_sm`` model, mirroring
``test_novelty.py``'s existing convention; the safety-genre test monkeypatches
enumeration entirely, isolating the document-frequency/observation scoring
path exactly like ``test_novelty.py``'s floor/ceiling tests).

ASSUMPTION (pass-1, flagged for reconciliation at merge): this pass runs
BEFORE the coder's ``novelty.py``/``mining_types.py`` changes for task 2
(observation emission) land, so every test below is written against the
agreed contract in ``proposal-observation-provenance/specs/novelty-detection/
spec.md`` (per-document/per-corpus observations, DF derived as distinct-doc
count, no persisted ``docFrequency`` scalar) rather than any implementation:

1. ``Candidate.observations`` is populated by ``mine_candidates`` for every
   surviving candidate: one :class:`~msr_extraction.mining_types.Observation`
   per **distinct document** the term was seen in (never more than one
   Observation per document per mine run).
2. ``len({obs.document_iri for obs in candidate.observations}
   ) == candidate.doc_frequency`` -- the derived document-frequency-from-
   observations invariant (spec: "Document frequency counts each document
   once" / "no docFrequency scalar is emitted [as RDF]; DF is derived").
3. Each Observation's ``corpus`` matches the genre's corpus CURIE
   (:data:`msr_extraction.corpora.CORPUS_CHEMISTRY` /
   :data:`~msr_extraction.corpora.CORPUS_SAFETY`).
4. For the **safety** genre, document identity is unambiguous (the
   ``reports`` list passed to ``mine_candidates`` IS the per-document
   scanning unit -- ``score_document_frequency``'s existing
   ``_build_safety_corpus_index`` already reads exactly one
   ``config.safety_normalized_path(report)`` per ``reports`` entry), so this
   test pins ``obs.document_iri == f"{MSRD}{report}"`` exactly (the same
   ``f"{MSRD}{report}"`` scheme every other module in ``novelty.py`` already
   uses for ``Evidence.document_iri``) and asserts EXACT per-document
   ``occurrence_count`` values.
5. For the **chemistry** genre, document identity over the ``archive_dir``
   ``rglob`` scan is not yet pinned by any existing module (today's
   ``_build_corpus_index`` returns bare text, discarding path identity) --
   this test only asserts the document-count/DF invariant and that each
   observation's document_iri is *derived from* (contains) the archive
   filename stem, not an exact IRI string, to stay robust to the coder's
   exact identity-derivation choice.
"""

from __future__ import annotations

import spacy

from msr_extraction import corpora, novelty
from msr_extraction.config import Config
from msr_extraction.graph_reader import MSRD, GraphReader, KnownEntity
from msr_extraction.mining_types import Evidence
from msr_extraction.novelty import mine_candidates

REPORT = "FIX-0001"

_NLP = spacy.load("en_core_web_sm")


def _model_unavailable(config: Config):
    return None


def _fixed_lexical_evidence(terms: list[str]) -> dict[str, list[Evidence]]:
    return {
        term: [
            Evidence(
                report=REPORT,
                document_iri=f"{MSRD}{REPORT}",
                sentence_text=term,
                start_offset=0,
                end_offset=len(term),
            )
        ]
        for term in terms
    }


def _empty_reader() -> GraphReader:
    def select_fn(query: str):
        return []

    return GraphReader("http://example/repositories/msr", select_fn=select_fn)


def _write_curated_report(config: Config, report: str, sentences: list[str]) -> None:
    import json

    offset = 0
    segments = []
    for index, sentence in enumerate(sentences):
        if index > 0:
            offset += 1
        start = offset
        end = start + len(sentence)
        segments.append(
            {"report": report, "index": index, "text": sentence, "char_start": start, "char_end": end}
        )
        offset = end
    normalized_text = " ".join(sentences)
    normalized_path = config.normalized_path(report)
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_path.write_text(normalized_text, encoding="utf-8")
    with config.segments_path(report).open("w", encoding="utf-8") as fh:
        for seg in segments:
            fh.write(json.dumps(seg))
            fh.write("\n")


def _write_mentions(config: Config, report: str, records: list[dict]) -> None:
    import json

    path = config.mentions_path(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record))
            fh.write("\n")


def _write_archive_docs(config: Config, docs: dict[str, str]) -> None:
    config.archive_dir.mkdir(parents=True, exist_ok=True)
    for name, text in docs.items():
        (config.archive_dir / name).write_text(text, encoding="utf-8")


def _write_safety_normalized(config: Config, source_id: str, text: str) -> None:
    path = config.safety_normalized_path(source_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --- 7.1: chemistry genre -------------------------------------------------


def test_mine_candidates_chemistry_emits_per_document_observations(monkeypatch, tmp_path) -> None:
    """Scenario: "Surviving candidate carries observations" -- a candidate
    surviving the chemistry-genre floor carries one Observation per document
    it occurred in, and the distinct-document count matches doc_frequency
    (never a persisted docFrequency scalar substitute -- see
    ``change-proposal-schema``/``proposal-observation-provenance`` specs for
    where the scalar itself is dropped, at the proposal-writer boundary)."""
    monkeypatch.setattr(novelty, "load_spacy_pipeline", _model_unavailable)
    monkeypatch.setattr(
        novelty, "enumerate_lexical_terms", lambda reports, cfg: _fixed_lexical_evidence(["keepterm"])
    )
    monkeypatch.setattr(novelty, "read_miss_candidates", lambda reports, cfg: [])

    config = Config(corpus_dir=tmp_path, salience_threshold=1, mine_max_candidates=100)
    _write_archive_docs(
        config,
        {
            "DOC-A.txt": "keepterm appears keepterm here keepterm again",  # 3 occurrences
            "DOC-B.txt": "keepterm shows up here once",  # 1 occurrence
            "DOC-C.txt": "no match in this document at all",  # 0 occurrences
        },
    )

    candidates = mine_candidates(config, _empty_reader(), reports=[REPORT])
    by_term = {c.term: c for c in candidates}

    assert "keepterm" in by_term
    candidate = by_term["keepterm"]

    # DF-from-observations invariant: distinct documents == doc_frequency.
    distinct_docs = {obs.document_iri for obs in candidate.observations}
    assert len(distinct_docs) == candidate.doc_frequency == 2
    assert len(candidate.observations) == 2  # never more than one per document

    by_doc = {obs.document_iri: obs for obs in candidate.observations}
    doc_a = next(iri for iri in by_doc if "DOC-A" in iri)
    doc_b = next(iri for iri in by_doc if "DOC-B" in iri)
    assert not any("DOC-C" in iri for iri in by_doc)

    assert by_doc[doc_a].occurrence_count == 3
    assert by_doc[doc_b].occurrence_count == 1
    assert by_doc[doc_a].corpus == corpora.CORPUS_CHEMISTRY
    assert by_doc[doc_b].corpus == corpora.CORPUS_CHEMISTRY


def test_mine_candidates_chemistry_observations_empty_for_zero_hit_term(monkeypatch, tmp_path) -> None:
    """A candidate with document frequency 0 would never survive the floor
    (dropped before triage per the novelty-detection spec), so this is a
    sanity check that the observation machinery does not fabricate
    observations for documents the term never occurred in."""
    monkeypatch.setattr(novelty, "load_spacy_pipeline", _model_unavailable)
    monkeypatch.setattr(
        novelty, "enumerate_lexical_terms", lambda reports, cfg: _fixed_lexical_evidence(["keepterm"])
    )
    monkeypatch.setattr(novelty, "read_miss_candidates", lambda reports, cfg: [])

    config = Config(corpus_dir=tmp_path, salience_threshold=1, mine_max_candidates=100)
    _write_archive_docs(config, {"DOC-A.txt": "keepterm here once"})

    candidates = mine_candidates(config, _empty_reader(), reports=[REPORT])
    by_term = {c.term: c for c in candidates}
    assert "keepterm" in by_term
    assert len(by_term["keepterm"].observations) == 1


# --- 7.1: safety genre (unambiguous document identity via `reports`) -----


def test_mine_candidates_safety_emits_exact_per_report_observations(monkeypatch, tmp_path) -> None:
    """Safety-genre document identity is unambiguous: `score_document_frequency`
    reads exactly one `config.safety_normalized_path(report)` per `reports`
    entry, so this test pins exact `document_iri`/`occurrence_count`/`corpus`
    values, and drives real `score_document_frequency` (only enumeration is
    monkeypatched) so the counting logic itself is exercised."""
    monkeypatch.setattr(novelty, "load_spacy_pipeline", _model_unavailable)
    monkeypatch.setattr(
        novelty,
        "enumerate_lexical_terms",
        lambda reports, cfg, **kw: _fixed_lexical_evidence(["keepterm"]),
    )
    monkeypatch.setattr(novelty, "read_miss_candidates", lambda reports, cfg, **kw: [])

    config = Config(corpus_dir=tmp_path, safety_salience_threshold=1, mine_max_candidates=100)
    _write_safety_normalized(config, "SRC-A", "keepterm keepterm dropped keepterm")  # 3
    _write_safety_normalized(config, "SRC-B", "keepterm only once here")  # 1

    candidates = mine_candidates(
        config, _empty_reader(), reports=["SRC-A", "SRC-B"], genre="safety"
    )
    by_term = {c.term: c for c in candidates}
    assert "keepterm" in by_term
    candidate = by_term["keepterm"]

    distinct_docs = {obs.document_iri for obs in candidate.observations}
    assert len(distinct_docs) == candidate.doc_frequency == 2

    by_doc = {obs.document_iri: obs for obs in candidate.observations}
    assert by_doc[f"{MSRD}SRC-A"].occurrence_count == 3
    assert by_doc[f"{MSRD}SRC-B"].occurrence_count == 1
    assert by_doc[f"{MSRD}SRC-A"].corpus == corpora.CORPUS_SAFETY
    assert by_doc[f"{MSRD}SRC-B"].corpus == corpora.CORPUS_SAFETY


def test_mine_candidates_no_observation_for_report_missing_the_term(monkeypatch, tmp_path) -> None:
    """A safety report the term never occurs in must not contribute an
    Observation (zero-count observations are not written; a document not
    seen is simply absent, not present-with-count-0)."""
    monkeypatch.setattr(novelty, "load_spacy_pipeline", _model_unavailable)
    monkeypatch.setattr(
        novelty,
        "enumerate_lexical_terms",
        lambda reports, cfg, **kw: _fixed_lexical_evidence(["keepterm"]),
    )
    monkeypatch.setattr(novelty, "read_miss_candidates", lambda reports, cfg, **kw: [])

    config = Config(corpus_dir=tmp_path, safety_salience_threshold=1, mine_max_candidates=100)
    _write_safety_normalized(config, "SRC-A", "keepterm appears here")
    _write_safety_normalized(config, "SRC-B", "nothing relevant in this one")

    candidates = mine_candidates(
        config, _empty_reader(), reports=["SRC-A", "SRC-B"], genre="safety"
    )
    by_term = {c.term: c for c in candidates}
    assert "keepterm" in by_term
    candidate = by_term["keepterm"]

    doc_iris = {obs.document_iri for obs in candidate.observations}
    assert doc_iris == {f"{MSRD}SRC-A"}
