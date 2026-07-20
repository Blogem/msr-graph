"""Novelty-detection unit tests (openspec/changes/mine-ontology-candidates,
spec novelty-detection, tasks 8.1/8.2).

Hermetic: no live GraphDB, no live model. Builds a small fixture corpus
under ``tmp_path`` -- a curated report's ``segments.jsonl`` /
``normalized.txt`` / ``mentions.jsonl`` plus a handful of full-corpus OCR
sidecars under ``msr-archive/`` -- and drives a real
:class:`~msr_extraction.graph_reader.GraphReader` with an injected
``select_fn`` (mirrors ``test_graph_reader.py``), so no HTTP call is ever
made.

ASSUMPTION (pass-1, flagged in the tester handoff report for
reconciliation at merge): ``novelty.py`` does not exist yet on this
isolated pass-1 branch. Every test below is written against the agreed
module-interface contract (design.md D1/D2, specs/novelty-detection), not
against any implementation, and is expected to fail with a collection
error until the coder's ``novelty.py`` lands. Two normalization
assumptions are baked into the fixtures and called out again in the
handoff report: (1) ``Candidate.term`` is the lower-cased surface form;
(2) an evidence item's ``start_offset``/``end_offset`` are the span's own
offsets (not the enclosing sentence's), per the novelty-detection spec's
"the span's start/end offsets into that document's normalized.txt".
"""

from __future__ import annotations

import json

from msr_extraction.config import Config
from msr_extraction.graph_reader import MSRD, VOC, GraphReader
from msr_extraction.novelty import (
    build_exclusion_set,
    enumerate_lexical_terms,
    mine_candidates,
    read_miss_candidates,
    score_document_frequency,
)

REPORT = "FIX-0001"


def _write_curated_report(config: Config, report: str, sentences: list[str]) -> list[dict]:
    """Write ``normalized.txt`` + ``segments.jsonl`` for ``report``.

    Sentences are joined with a single space; each segment's
    ``char_start``/``char_end`` are computed so
    ``normalized_text[start:end] == sentence`` holds exactly, mirroring
    ``segmenter.py``'s contract. Returns the segment dicts written (report,
    index, text, char_start, char_end) so callers can build matching
    ``mentions.jsonl`` records against real offsets.
    """
    segments: list[dict] = []
    offset = 0
    for index, sentence in enumerate(sentences):
        if index > 0:
            offset += 1  # single-space separator
        start = offset
        end = start + len(sentence)
        segments.append(
            {
                "report": report,
                "index": index,
                "text": sentence,
                "char_start": start,
                "char_end": end,
            }
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

    return segments


def _write_mentions(config: Config, report: str, records: list[dict]) -> None:
    path = config.mentions_path(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record))
            fh.write("\n")


def _write_archive_docs(config: Config, docs: dict[str, str]) -> None:
    """Write ``docs`` (filename -> text) under ``config.archive_dir``."""
    config.archive_dir.mkdir(parents=True, exist_ok=True)
    for name, text in docs.items():
        (config.archive_dir / name).write_text(text, encoding="utf-8")


def _known_entities_reader(labels_by_query_marker: dict[str, list[tuple[str, str]]]) -> GraphReader:
    """Build a real GraphReader with an injected select_fn -- no HTTP call."""

    def select_fn(query: str):
        for marker, pairs in labels_by_query_marker.items():
            if marker in query:
                return [
                    {
                        "c": {"value": iri, "type": "uri"},
                        "label": {"value": label, "type": "literal"},
                    }
                    for iri, label in pairs
                ]
        return []

    return GraphReader("http://example/repositories/msr", select_fn=select_fn)


def _empty_reader() -> GraphReader:
    return _known_entities_reader({})


# --- 8.1: lexical enumeration + salience scoring -------------------------


def test_enumerate_lexical_terms_surfaces_term_absent_from_mentions(tmp_path) -> None:
    """Scenario: "A novel domain term is enumerated from the curated text"
    -- "solubility" is present in the curated segments but chunk 6 never
    linked it (mentions.jsonl carries no record for it), yet the miner's
    own lexical pass still enumerates it."""
    config = Config(corpus_dir=tmp_path)
    sentences = [
        "The solubility of PuF3 in LiF-BeF2 was measured at 280 mole %.",
        "Graphite was used as the moderator material in the core.",
    ]
    _write_curated_report(config, REPORT, sentences)
    _write_mentions(config, REPORT, [])  # chunk 6 never linked "solubility"

    terms = enumerate_lexical_terms([REPORT], config)

    assert "solubility" in terms
    evidence_items = terms["solubility"]
    assert len(evidence_items) >= 1
    ev = evidence_items[0]
    assert ev.report == REPORT
    assert ev.document_iri == f"{MSRD}{REPORT}"
    normalized_text = config.normalized_path(REPORT).read_text(encoding="utf-8")
    assert normalized_text[ev.start_offset : ev.end_offset].lower() == "solubility"
    # grounded in the real curated sentence, not fabricated
    assert ev.sentence_text in normalized_text


def test_status_novel_mention_becomes_instance_kind_miss_candidate(tmp_path) -> None:
    """Scenario: "An unresolved salt-formula miss becomes a candidate" --
    a status:"novel" mentions.jsonl record is read as a miss-sourced
    Candidate."""
    config = Config(corpus_dir=tmp_path)
    sentences = ["A new compound LiF-ThF4-UF4 was observed forming a stable salt."]
    segments = _write_curated_report(config, REPORT, sentences)
    seg = segments[0]
    _write_mentions(
        config,
        REPORT,
        [
            {
                "report": REPORT,
                "seg_index": seg["index"],
                "char_start": seg["char_start"],
                "char_end": seg["char_end"],
                "surface_form": "LiF-ThF4-UF4",
                "status": "novel",
                "target_iri": None,
                "target_kind": None,
                "layer": 5,
                "score": None,
            }
        ],
    )

    candidates = read_miss_candidates([REPORT], config)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source == "miss"
    assert candidate.surface_form == "LiF-ThF4-UF4"
    assert candidate.term == "lif-thf4-uf4"
    assert len(candidate.evidence) == 1
    ev = candidate.evidence[0]
    assert ev.report == REPORT
    assert ev.document_iri == f"{MSRD}{REPORT}"
    assert ev.start_offset == seg["char_start"]
    assert ev.end_offset == seg["char_end"]


def test_read_miss_candidates_ignores_linked_records(tmp_path) -> None:
    """Only status:"novel" records become candidates -- a status:"linked"
    record (chunk 6 already resolved it) is not a miss candidate."""
    config = Config(corpus_dir=tmp_path)
    sentences = ["FLiBe is a well known coolant salt."]
    segments = _write_curated_report(config, REPORT, sentences)
    seg = segments[0]
    _write_mentions(
        config,
        REPORT,
        [
            {
                "report": REPORT,
                "seg_index": seg["index"],
                "char_start": seg["char_start"],
                "char_end": seg["char_end"],
                "surface_form": "FLiBe",
                "status": "linked",
                "target_iri": f"{VOC}flibe",
                "target_kind": "concept",
                "layer": 2,
                "score": None,
            }
        ],
    )

    assert read_miss_candidates([REPORT], config) == []


def test_score_document_frequency_counts_case_folded_matches(tmp_path) -> None:
    """Scenario basis for "A high-frequency term survives the threshold" /
    "A low-frequency term is dropped" -- a small fixture archive yields
    exact, case-folded document-frequency counts."""
    config = Config(corpus_dir=tmp_path)
    docs = {
        "doc0.txt": "Solubility was studied extensively. rareterm appears here.",
        "doc1.txt": "Solubility data varies. RARETERM appears here too.",
        "doc2.txt": "solubility is context dependent.",
        "doc3.txt": "SOLUBILITY was reported in mole percent.",
        "doc4.txt": "Solubility measurements were repeated.",
    }
    _write_archive_docs(config, docs)

    counts = score_document_frequency({"solubility", "rareterm", "absent"}, config)

    assert counts["solubility"] == 5
    assert counts["rareterm"] == 2
    assert counts["absent"] == 0


def test_mine_candidates_threshold_boundary(tmp_path) -> None:
    """Scenario: threshold boundary via the end-to-end mine_candidates
    pipeline -- a term at freq == threshold is KEPT, freq == threshold - 1
    is DROPPED."""
    config = Config(corpus_dir=tmp_path, salience_threshold=3)
    sentences = [
        "The keepterm value was measured across several samples.",
        "A dropterm reading was also noted once.",
    ]
    _write_curated_report(config, REPORT, sentences)
    _write_mentions(config, REPORT, [])
    _write_archive_docs(
        config,
        {
            "doc0.txt": "keepterm dropterm",
            "doc1.txt": "keepterm dropterm",
            "doc2.txt": "keepterm only here",
        },
    )

    candidates = mine_candidates(config, _empty_reader(), reports=[REPORT])
    by_term = {c.term: c for c in candidates}

    assert "keepterm" in by_term  # freq == 3 == threshold -> kept
    assert by_term["keepterm"].doc_frequency == 3
    assert "dropterm" not in by_term  # freq == 2 == threshold - 1 -> dropped


def test_mine_candidates_excludes_known_vocab_term(tmp_path) -> None:
    """Scenario: "A previously-approved term is not re-proposed" -- a
    candidate whose term matches a concept already in urn:msr:vocab is
    excluded, even though it clears the salience threshold easily."""
    config = Config(corpus_dir=tmp_path, salience_threshold=1)
    sentences = ["Graphite was used as the moderator material."]
    _write_curated_report(config, REPORT, sentences)
    _write_mentions(config, REPORT, [])
    _write_archive_docs(config, {"doc0.txt": "graphite graphite graphite"})

    reader = _known_entities_reader({"skos:Concept": [(f"{VOC}graphite", "graphite")]})

    candidates = mine_candidates(config, reader, reports=[REPORT])
    assert "graphite" not in {c.term for c in candidates}


def test_mine_candidates_excludes_already_linked_term(tmp_path) -> None:
    """A term chunk 6 already linked (status:"linked") is excluded from
    the mined pool, independent of the core-dataset reader."""
    config = Config(corpus_dir=tmp_path, salience_threshold=1)
    sentences = ["FLiBe coolant salt was used in the loop."]
    segments = _write_curated_report(config, REPORT, sentences)
    seg = segments[0]
    _write_mentions(
        config,
        REPORT,
        [
            {
                "report": REPORT,
                "seg_index": seg["index"],
                "char_start": seg["char_start"],
                "char_end": seg["char_end"],
                "surface_form": "FLiBe",
                "status": "linked",
                "target_iri": f"{VOC}flibe",
                "target_kind": "concept",
                "layer": 2,
                "score": None,
            }
        ],
    )
    _write_archive_docs(config, {"doc0.txt": "flibe flibe flibe"})

    candidates = mine_candidates(config, _empty_reader(), reports=[REPORT])
    assert "flibe" not in {c.term for c in candidates}


# --- 8.2: core-dataset exclusion guard -----------------------------------


def test_build_exclusion_set_excludes_core_vocab_concept(tmp_path) -> None:
    """Scenario: a term present as a core urn:msr:vocab concept label IS
    excluded."""
    config = Config(corpus_dir=tmp_path)
    _write_curated_report(config, REPORT, ["placeholder sentence for the fixture."])
    _write_mentions(config, REPORT, [])
    reader = _known_entities_reader({"skos:Concept": [(f"{VOC}solubility", "solubility")]})

    excluded = build_exclusion_set(reader, [REPORT], config)
    assert "solubility" in excluded


def test_build_exclusion_set_does_not_exclude_staging_only_term(tmp_path) -> None:
    """Scenario: "Staging membership does not exclude a candidate" -- the
    reader only ever queries the three core FROM graphs (never
    urn:msr:staging), so a term that would exist only in a pending
    proposal is simply never among the injected core bindings here, and is
    therefore not excluded."""
    config = Config(corpus_dir=tmp_path)
    _write_curated_report(config, REPORT, ["placeholder sentence for the fixture."])
    _write_mentions(config, REPORT, [])
    reader = _empty_reader()  # no core bindings at all

    excluded = build_exclusion_set(reader, [REPORT], config)
    assert "pending-staging-term" not in excluded


def test_build_exclusion_set_includes_linked_mention_surface_forms(tmp_path) -> None:
    """The exclusion set also covers chunk 6's already-linked mentions
    (status:"linked" records), not only core-dataset reads."""
    config = Config(corpus_dir=tmp_path)
    segments = _write_curated_report(config, REPORT, ["FLiBe is a coolant salt."])
    seg = segments[0]
    _write_mentions(
        config,
        REPORT,
        [
            {
                "report": REPORT,
                "seg_index": seg["index"],
                "char_start": seg["char_start"],
                "char_end": seg["char_end"],
                "surface_form": "FLiBe",
                "status": "linked",
                "target_iri": f"{VOC}flibe",
                "target_kind": "concept",
                "layer": 2,
                "score": None,
            }
        ],
    )
    reader = _empty_reader()

    excluded = build_exclusion_set(reader, [REPORT], config)
    assert "flibe" in excluded
