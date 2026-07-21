"""Sentence-selection tests (chunk 7, task 8.2).

Pins ``select_sentences``: only segments carrying at least one chunk-6
``status:"linked"`` mention are selected for relation extraction (the
relation-extraction spec's "Extraction is scoped to sentences carrying
linked mentions" requirement); a segment whose only mention is
``status:"novel"`` -- or with no mention at all -- is excluded, and never
triggers a Flash call downstream.

Builds a tiny ``segments.jsonl``/``mentions.jsonl`` pair under ``tmp_path``
via a ``Config`` pointed at ``tmp_path`` as ``corpus_dir``, following the
chunk-5/6 on-disk artifact schema already established by
``linker.Segment``/``linker.MentionRecord`` (see
``msr_extraction/linker.py``).

Written pass-1 against the pinned ``msr_extraction.relations`` API; the
module does not exist yet in this worktree (concurrent coder work), so
this file is expected to error at collection until pass 2 merges it.
"""

from __future__ import annotations

import json
from pathlib import Path

from msr_extraction.config import Config
from msr_extraction.relations import select_sentences

REPORT = "ORNL-TM-2316"

SALT_IRI = "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"

LINKED_SEG_TEXT = "FLiBe served as the primary coolant salt in the MSRE."
NOVEL_ONLY_SEG_TEXT = "An unrelated sentence mentioning only a novel, unlinked term."


def _write_jsonl(path: Path, objs: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for obj in objs:
            fh.write(json.dumps(obj))
            fh.write("\n")


def _build_corpus(tmp_path: Path) -> Config:
    config = Config(corpus_dir=tmp_path)

    segments = [
        {
            "report": REPORT,
            "index": 0,
            "text": LINKED_SEG_TEXT,
            "char_start": 0,
            "char_end": len(LINKED_SEG_TEXT),
        },
        {
            "report": REPORT,
            "index": 1,
            "text": NOVEL_ONLY_SEG_TEXT,
            "char_start": len(LINKED_SEG_TEXT) + 1,
            "char_end": len(LINKED_SEG_TEXT) + 1 + len(NOVEL_ONLY_SEG_TEXT),
        },
    ]
    mentions = [
        {
            "report": REPORT,
            "seg_index": 0,
            "char_start": 0,
            "char_end": 5,
            "surface_form": "FLiBe",
            "status": "linked",
            "target_iri": SALT_IRI,
            "target_kind": "salt",
            "layer": 2,
            "score": None,
        },
        {
            "report": REPORT,
            "seg_index": 1,
            "char_start": 0,
            "char_end": 5,
            "surface_form": "novel",
            "status": "novel",
            "target_iri": None,
            "target_kind": None,
            "layer": 5,
            "score": None,
        },
    ]

    _write_jsonl(config.segments_path(REPORT), segments)
    _write_jsonl(config.mentions_path(REPORT), mentions)
    return config


def test_only_the_linked_mention_bearing_segment_is_selected(tmp_path: Path) -> None:
    config = _build_corpus(tmp_path)

    selected = select_sentences(REPORT, config)

    assert len(selected) == 1
    assert selected[0].text == LINKED_SEG_TEXT


def test_selected_sentence_carries_its_linked_mention(tmp_path: Path) -> None:
    config = _build_corpus(tmp_path)

    selected = select_sentences(REPORT, config)

    linked_mentions = selected[0].linked_mentions
    assert len(linked_mentions) == 1
    assert linked_mentions[0].surface_form == "FLiBe"
    assert linked_mentions[0].target_iri == SALT_IRI


def test_novel_only_segment_is_excluded(tmp_path: Path) -> None:
    config = _build_corpus(tmp_path)

    selected = select_sentences(REPORT, config)

    assert all(sentence.text != NOVEL_ONLY_SEG_TEXT for sentence in selected)
