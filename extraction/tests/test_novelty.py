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

refine-mine-salience (7.1-7.3) additions below: spaCy noun-chunk
enumeration, hardened token-sequence-aware exclusion, and the coarse
cost-bound floor/ceiling. These use the REAL ``en_core_web_sm`` pipeline
(installed for this change, design.md D5) injected via ``mine_candidates``'s
``nlp=`` keyword, or monkeypatch ``novelty.load_spacy_pipeline`` to
simulate model-unavailable. Fixture sentences below were dry-run against
the real model to confirm their ``doc.ents``/``doc.noun_chunks`` shape
before being pinned into assertions (see the tester handoff report).
"""

from __future__ import annotations

import json
import logging

import spacy

from msr_extraction import novelty
from msr_extraction.config import Config
from msr_extraction.graph_reader import MSR, MSRD, VOC, GraphReader, KnownEntity
from msr_extraction.mining_types import Evidence
from msr_extraction.novelty import (
    build_exclusion_set,
    enumerate_lexical_terms,
    mine_candidates,
    read_miss_candidates,
    score_document_frequency,
)

REPORT = "FIX-0001"

#: Real, installed spaCy model (design.md D5 pins it as a build-time wheel
#: dependency) -- loaded once at module import time and passed explicitly
#: via ``mine_candidates(..., nlp=_NLP)`` so enumeration is deterministic
#: and every test avoids a per-test reload cost.
_NLP = spacy.load("en_core_web_sm")


def _raise_model_unavailable(config: Config):
    """A ``load_spacy_pipeline`` stand-in simulating the model failing to load."""
    raise OSError("simulated: en_core_web_sm not installed")


def _fixed_lexical_evidence(terms: list[str]) -> dict[str, list[Evidence]]:
    """A minimal, fully-controlled ``enumerate_lexical_terms``-shaped return
    value: one candidate term -> one fabricated Evidence each. Used to
    monkeypatch enumeration away entirely so the floor/ceiling cost-bound
    tests (7.3) exercise only that logic, independent of spaCy/n-gram
    enumeration specifics or real corpus text."""
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


def _any_term_contains_subsequence(terms: list[str], label_tokens: list[str]) -> bool:
    """Whether any ``term`` (space-joined tokens) contains ``label_tokens``
    as a contiguous subsequence -- the novelty-detection spec's "a known
    label's full token sequence appearing in a candidate excludes it"
    containment rule, checked independent of how a candidate's own token
    count/splitting is implemented."""
    n = len(label_tokens)
    for term in terms:
        tokens = term.split()
        if any(tokens[i : i + n] == label_tokens for i in range(len(tokens) - n + 1)):
            return True
    return False


class FakeKnownEntitiesReader:
    """A minimal GraphReader stand-in exposing only an injected
    :class:`~msr_extraction.graph_reader.KnownEntity` list.

    Models the "restricted to the three core FROM graphs" read guarantee
    directly, without any SPARQL query text: a term that would exist only
    in ``urn:msr:staging`` is simply never present in the injected list, so
    it can never be excluded on that basis (novelty-detection spec,
    "Staging membership does not exclude a candidate").
    """

    def __init__(self, entities: list[KnownEntity]) -> None:
        self._entities = entities

    def read_known_entities(self) -> list[KnownEntity]:
        return self._entities

    def read_version(self) -> str | None:
        return None

    def known_iris(self) -> set[str]:
        return {entity.target_iri for entity in self._entities}


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
    # Evidence.sentence_text is the full enclosing segment, not the bare
    # term -- the term must appear as a substring of it.
    assert "solubility" in ev.sentence_text.lower()
    normalized_text = config.normalized_path(REPORT).read_text(encoding="utf-8")
    assert normalized_text[ev.start_offset : ev.end_offset] == ev.sentence_text
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


# --- refine-mine-salience 7.1: spaCy noun-chunk enumeration --------------


def test_mine_candidates_enumerates_spacy_noun_chunk_concept_absent_from_mentions(
    tmp_path,
) -> None:
    """Scenario: "A novel domain term is enumerated as a noun chunk" -- the
    curated text contains "solubility", chunk 6 never linked it
    (mentions.jsonl carries no record for it), yet the spaCy noun-chunk pass
    still enumerates it as a candidate."""
    config = Config(corpus_dir=tmp_path, salience_threshold=0)
    sentences = [
        "The solubility of the fuel salt was measured extensively by the laboratory team.",
    ]
    _write_curated_report(config, REPORT, sentences)
    _write_mentions(config, REPORT, [])

    candidates = mine_candidates(config, _empty_reader(), reports=[REPORT], nlp=_NLP)

    terms = [c.term for c in candidates]
    assert any("solubility" in term for term in terms)


def test_mine_candidates_includes_status_novel_miss_with_spacy_enumeration_active(
    tmp_path,
) -> None:
    """Scenario: "An unresolved salt-formula miss becomes a candidate" --
    exercised end-to-end through mine_candidates with real spaCy
    enumeration active (nlp=_NLP), proving the chunk-6 miss path is
    untouched by the new spaCy enumeration source."""
    config = Config(corpus_dir=tmp_path, salience_threshold=0)
    sentences = ["A new compound LiF-ThF4-UF4 was observed forming a stable salt in the loop."]
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

    candidates = mine_candidates(config, _empty_reader(), reports=[REPORT], nlp=_NLP)

    miss_candidates = [c for c in candidates if c.source == "miss"]
    assert any(c.term == "lif-thf4-uf4" for c in miss_candidates)


def test_mine_candidates_drops_org_entity_tokens_lab_or_org_name(tmp_path) -> None:
    """Scenario: "A proper noun is not enumerated as a candidate" -- an ORG
    entity (a laboratory/organization name, e.g. "Union Carbide
    Corporation") is dropped at the spaCy enumeration stage, while the
    co-occurring non-entity noun chunk ("graphite moderator materials")
    from the same sentence survives. Dry-run confirmed real
    ``en_core_web_sm`` tags all three tokens ``ent_type_=="ORG"`` for this
    sentence."""
    config = Config(corpus_dir=tmp_path, salience_threshold=0)
    sentences = [
        "Union Carbide Corporation supported the study of graphite moderator materials.",
    ]
    _write_curated_report(config, REPORT, sentences)
    _write_mentions(config, REPORT, [])

    candidates = mine_candidates(config, _empty_reader(), reports=[REPORT], nlp=_NLP)
    terms = [c.term for c in candidates]

    dropped_tokens = {"union", "carbide", "corporation"}
    assert not any(dropped_tokens & set(term.split()) for term in terms)
    assert any("graphite" in term for term in terms)


def test_mine_candidates_drops_person_entity_tokens_author_name(tmp_path) -> None:
    """Scenario: "A proper noun is not enumerated as a candidate" -- a
    PERSON entity (an author name) is dropped, while the co-occurring
    non-entity noun chunk ("graphite moderator materials") survives. Dry-run
    confirmed real ``en_core_web_sm`` tags "Alice Johnson" PERSON and "Oak
    Ridge National Laboratory" ORG for this sentence."""
    config = Config(corpus_dir=tmp_path, salience_threshold=0)
    sentences = [
        "Dr. Alice Johnson led the study of graphite moderator materials "
        "at Oak Ridge National Laboratory.",
    ]
    _write_curated_report(config, REPORT, sentences)
    _write_mentions(config, REPORT, [])

    candidates = mine_candidates(config, _empty_reader(), reports=[REPORT], nlp=_NLP)
    terms = [c.term for c in candidates]

    dropped_tokens = {"alice", "johnson", "oak", "ridge", "national", "laboratory"}
    assert not any(dropped_tokens & set(term.split()) for term in terms)
    assert any("graphite" in term for term in terms)


def test_mine_candidates_falls_back_to_ngram_pass_when_spacy_model_unavailable(
    monkeypatch, tmp_path, caplog
) -> None:
    """Scenario basis: "If the spaCy model cannot be loaded, the miner SHALL
    log an error and fall back to the prior n-gram term-candidate pass
    rather than failing" (novelty-detection spec; design.md D5). Simulated
    by making ``load_spacy_pipeline`` raise -- ``mine_candidates`` must not
    propagate the exception, and the fallback n-gram pass must still
    enumerate a plain lexical term."""
    monkeypatch.setattr(novelty, "load_spacy_pipeline", _raise_model_unavailable)

    config = Config(corpus_dir=tmp_path, salience_threshold=0)
    sentences = ["The keepterm value was measured across several samples in the study."]
    _write_curated_report(config, REPORT, sentences)
    _write_mentions(config, REPORT, [])

    with caplog.at_level(logging.ERROR):
        candidates = mine_candidates(config, _empty_reader(), reports=[REPORT])

    terms = {c.term for c in candidates}
    assert "keepterm" in terms
    assert any("spacy" in rec.message.lower() for rec in caplog.records)


# --- refine-mine-salience 7.2: hardened, token-sequence-aware exclusion --


def test_mine_candidates_excludes_camelcase_variant_of_known_class_label(tmp_path) -> None:
    """Scenario: "A spelling variant of a known label is excluded" -- the
    spaCy-enumerated "molten salt" noun chunk is excluded because it
    normalizes to the same token sequence as the core class label
    "MoltenSalt", even though the raw strings differ (design.md D2)."""
    config = Config(corpus_dir=tmp_path, salience_threshold=0)
    sentences = ["The molten salt was pumped through the loop during the test."]
    _write_curated_report(config, REPORT, sentences)
    _write_mentions(config, REPORT, [])
    entity = KnownEntity(target_iri=f"{MSR}MoltenSalt", labels=("MoltenSalt",), kind="class")
    reader = FakeKnownEntitiesReader([entity])

    candidates = mine_candidates(config, reader, reports=[REPORT], nlp=_NLP)

    assert not _any_term_contains_subsequence(
        [c.term for c in candidates], ["molten", "salt"]
    )


def test_build_exclusion_set_normalizes_camelcase_class_label(tmp_path) -> None:
    """Direct-level companion to the mine_candidates integration test above
    -- whatever internal representation build_exclusion_set returns, the
    normalized ("molten", "salt") token sequence derived from the camelCase
    class label "MoltenSalt" must be discoverable in it."""
    config = Config(corpus_dir=tmp_path)
    _write_curated_report(config, REPORT, ["placeholder sentence for the fixture."])
    _write_mentions(config, REPORT, [])
    entity = KnownEntity(target_iri=f"{MSR}MoltenSalt", labels=("MoltenSalt",), kind="class")
    reader = FakeKnownEntitiesReader([entity])

    excluded = build_exclusion_set(reader, [REPORT], config)

    assert "molten salt" in excluded or ("molten", "salt") in excluded


def test_mine_candidates_excludes_chunk7_reactor_label(tmp_path) -> None:
    """Scenario: hardened exclusion also covers chunk-7's role/reactor
    layer labels (design.md D2/D4.1) -- a reactor-name candidate ("MSRE")
    is excluded because a known reactor label matches it, even though
    "MSRE" carries no NER entity type in this fixture sentence (dry-run
    confirmed ``doc.ents == []`` here)."""
    config = Config(corpus_dir=tmp_path, salience_threshold=0)
    sentences = ["The reactor core used graphite blocks for the MSRE design."]
    _write_curated_report(config, REPORT, sentences)
    _write_mentions(config, REPORT, [])
    entity = KnownEntity(target_iri=f"{VOC}msre", labels=("MSRE",), kind="reactor")
    reader = FakeKnownEntitiesReader([entity])

    candidates = mine_candidates(config, reader, reports=[REPORT], nlp=_NLP)
    terms = [c.term for c in candidates]

    assert not any("msre" in term.split() for term in terms)
    assert any("graphite" in term for term in terms)


def test_mine_candidates_excludes_seed_property_label(tmp_path) -> None:
    """Scenario basis: hardened exclusion covers physical-property labels
    already modeled in the core dataset (design.md context: "density",
    "viscosity", "corrosion" are the validated already-excluded terms)."""
    config = Config(corpus_dir=tmp_path, salience_threshold=0)
    sentences = ["The density of the salt was measured during the run."]
    _write_curated_report(config, REPORT, sentences)
    _write_mentions(config, REPORT, [])
    entity = KnownEntity(target_iri=f"{MSR}density", labels=("density",), kind="class")
    reader = FakeKnownEntitiesReader([entity])

    candidates = mine_candidates(config, reader, reports=[REPORT], nlp=_NLP)
    assert "density" not in {c.term for c in candidates}


def test_mine_candidates_does_not_exclude_term_sharing_single_token_with_known_label(
    tmp_path,
) -> None:
    """Scenario: "A novel term sharing one token with a known label is not
    excluded" -- the candidate "thermal conductivity" shares only the token
    "thermal" with the known label "thermal expansion" (not its full token
    sequence), so it is NOT excluded on that basis."""
    config = Config(corpus_dir=tmp_path, salience_threshold=0)
    sentences = ["The thermal conductivity was recorded during the run."]
    _write_curated_report(config, REPORT, sentences)
    _write_mentions(config, REPORT, [])
    entity = KnownEntity(
        target_iri=f"{MSR}ThermalExpansion", labels=("thermal expansion",), kind="class"
    )
    reader = FakeKnownEntitiesReader([entity])

    candidates = mine_candidates(config, reader, reports=[REPORT], nlp=_NLP)
    terms = [c.term for c in candidates]

    assert any("conductivity" in term for term in terms)


def test_mine_candidates_does_not_exclude_staging_only_term_spacy_path(tmp_path) -> None:
    """Scenario: "Staging membership does not exclude a candidate" -- the
    injected reader models the "only the three core FROM graphs" read
    restriction directly by exposing only an unrelated core label, so a
    term that would exist only as a pending urn:msr:staging proposal is
    simply never present in it and is therefore not excluded."""
    config = Config(corpus_dir=tmp_path, salience_threshold=0)
    sentences = ["The eutectic mixture behavior was studied during the run."]
    _write_curated_report(config, REPORT, sentences)
    _write_mentions(config, REPORT, [])
    entity = KnownEntity(target_iri=f"{MSR}MoltenSalt", labels=("MoltenSalt",), kind="class")
    reader = FakeKnownEntitiesReader([entity])  # unrelated core label only

    candidates = mine_candidates(config, reader, reports=[REPORT], nlp=_NLP)
    terms = [c.term for c in candidates]

    assert any("eutectic" in term for term in terms)


# --- refine-mine-salience 7.3: coarse cost bound (floor + ceiling) -------


def test_mine_candidates_floor_drops_rare_term(monkeypatch, tmp_path) -> None:
    """Scenario: "A rare OCR one-off is dropped by the floor" -- enumeration
    is monkeypatched away entirely (fixed lexical terms + fixed document
    frequencies) so the floor comparison is exercised in isolation,
    independent of spaCy/n-gram enumeration specifics."""
    monkeypatch.setattr(novelty, "load_spacy_pipeline", _raise_model_unavailable)
    monkeypatch.setattr(
        novelty,
        "enumerate_lexical_terms",
        lambda reports, cfg: _fixed_lexical_evidence(["keepterm", "dropterm"]),
    )
    monkeypatch.setattr(novelty, "read_miss_candidates", lambda reports, cfg: [])
    monkeypatch.setattr(
        novelty, "score_document_frequency", lambda terms, cfg: {"keepterm": 3, "dropterm": 2}
    )

    config = Config(corpus_dir=tmp_path, salience_threshold=3, mine_max_candidates=100)

    candidates = mine_candidates(config, _empty_reader(), reports=[REPORT])
    by_term = {c.term: c for c in candidates}

    assert "keepterm" in by_term
    assert by_term["keepterm"].doc_frequency == 3
    assert "dropterm" not in by_term


def test_mine_candidates_ceiling_caps_and_logs_cut_count(monkeypatch, tmp_path, caplog) -> None:
    """Scenario: "The candidate set is bounded by the ceiling" -- five
    candidates survive floor+exclusion but mine_max_candidates=2, so only
    the top-2 by document frequency are kept and the cut count (3) is
    logged (never a silent truncation)."""
    monkeypatch.setattr(novelty, "load_spacy_pipeline", _raise_model_unavailable)
    monkeypatch.setattr(
        novelty,
        "enumerate_lexical_terms",
        lambda reports, cfg: _fixed_lexical_evidence(
            ["alpha", "beta", "gamma", "delta", "epsilon"]
        ),
    )
    monkeypatch.setattr(novelty, "read_miss_candidates", lambda reports, cfg: [])
    frequencies = {"alpha": 10, "beta": 9, "gamma": 8, "delta": 7, "epsilon": 6}
    monkeypatch.setattr(novelty, "score_document_frequency", lambda terms, cfg: frequencies)

    config = Config(corpus_dir=tmp_path, salience_threshold=1, mine_max_candidates=2)

    with caplog.at_level(logging.INFO):
        candidates = mine_candidates(config, _empty_reader(), reports=[REPORT])

    terms = {c.term for c in candidates}
    assert len(candidates) == 2
    assert terms == {"alpha", "beta"}  # top-2 by document frequency
    assert any(
        "3" in rec.message and ("cut" in rec.message.lower() or "ceiling" in rec.message.lower())
        for rec in caplog.records
    )


def test_mine_candidates_ceiling_cut_is_deterministic_across_runs(monkeypatch, tmp_path) -> None:
    """The runaway-cut tie-break is deterministic -- repeated runs over an
    identical survivor set with TIED document frequencies always produce
    the same kept subset, never e.g. a random sample (design.md D3: "a
    deterministic tie-break")."""
    monkeypatch.setattr(novelty, "load_spacy_pipeline", _raise_model_unavailable)
    monkeypatch.setattr(
        novelty,
        "enumerate_lexical_terms",
        lambda reports, cfg: _fixed_lexical_evidence(["alpha", "beta", "gamma"]),
    )
    monkeypatch.setattr(novelty, "read_miss_candidates", lambda reports, cfg: [])
    monkeypatch.setattr(
        novelty,
        "score_document_frequency",
        lambda terms, cfg: {"alpha": 5, "beta": 5, "gamma": 5},
    )

    config = Config(corpus_dir=tmp_path, salience_threshold=1, mine_max_candidates=2)

    first = [c.term for c in mine_candidates(config, _empty_reader(), reports=[REPORT])]
    second = [c.term for c in mine_candidates(config, _empty_reader(), reports=[REPORT])]

    assert len(first) == 2
    assert first == second


def test_mine_candidates_output_ordered_by_term_not_by_frequency_rank(
    monkeypatch, tmp_path
) -> None:
    """Scenario: "Ordering is not treated as a novelty ranking" -- candidates
    are returned sorted by term, never reordered by document frequency; DF
    is consulted only as the floor/ceiling cost bound, never as a rank. The
    fixed frequencies below are deliberately anti-correlated with term
    order (highest frequency on the alphabetically-last term) so a
    frequency-ranked output would be detectably different from a
    term-sorted one."""
    monkeypatch.setattr(novelty, "load_spacy_pipeline", _raise_model_unavailable)
    monkeypatch.setattr(
        novelty,
        "enumerate_lexical_terms",
        lambda reports, cfg: _fixed_lexical_evidence(["zeta", "alpha", "mu"]),
    )
    monkeypatch.setattr(novelty, "read_miss_candidates", lambda reports, cfg: [])
    monkeypatch.setattr(
        novelty,
        "score_document_frequency",
        lambda terms, cfg: {"zeta": 100, "alpha": 10, "mu": 1},
    )

    config = Config(corpus_dir=tmp_path, salience_threshold=0, mine_max_candidates=100)

    candidates = mine_candidates(config, _empty_reader(), reports=[REPORT])

    assert [c.term for c in candidates] == ["alpha", "mu", "zeta"]
