"""Shared mining datamodel.

Dataclass contract shared by every module in the ontology-mining pipeline
(lexical/miss candidate discovery, novelty scoring, triage, proposal
bundling, and instance auto-accept). :class:`Candidate` is the output of
lexical/miss candidate discovery; each carries zero or more
:class:`Evidence` items (the reviewer-facing sentence spans from the
curated ~12-report set). Triage (design.md D3) confirms a `kind` for a
candidate and, for `property`/`class`/`relation` kinds, an LLM-asserted
:class:`Placement` (design.md D6) recording broader-class/quantityKind/
canonicalUnit/domain/range claims — reviewer-verifiable, never
dereferenced against the live QUDT/INIS catalogs. :class:`TriagedCandidate`
bundles a candidate with its confirmed kind and placement; this is the
shared input every downstream module (novelty, proposals, auto_accept)
builds against, so its field names and types are the integration
contract between them.

Deliberately stdlib-only (no third-party imports) so this module has zero
import-time dependencies, mirroring ``provenance.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Triage kinds a candidate can be confirmed as (design.md D3).
KIND_PROPERTY = "property"
KIND_CLASS = "class"
KIND_INSTANCE = "instance"
KIND_RELATION = "relation"

#: The complete set of valid :attr:`TriagedCandidate.kind` values.
VALID_KINDS = frozenset({KIND_PROPERTY, KIND_CLASS, KIND_INSTANCE, KIND_RELATION})

_SLUG_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def term_slug(term: str) -> str:
    """Return the deterministic slug for ``term`` used across proposal/auto-accept IRIs.

    Lower-cases ``term``, replaces every run of non-alphanumeric characters
    with a single hyphen, and strips any leading/trailing hyphen. This is
    the single source of the slugging rule shared by
    ``msrd:proposal-{kind}-{term-slug}`` (design.md D5) and the
    auto-accept instance IRI minting scheme, so the two modules can never
    drift into different slug forms for the same term.
    """
    lowered = term.lower()
    collapsed = _SLUG_NON_ALNUM_RE.sub("-", lowered)
    return collapsed.strip("-")


@dataclass(frozen=True)
class Evidence:
    """One reviewer-facing evidence sentence for a candidate.

    Sourced only from the curated ~12-report set, where
    ``segments.jsonl``/``normalized.txt`` offsets and ``msr:Document``
    nodes exist (design.md D2).
    """

    #: Curated report id, e.g. ``"ORNL-TM-2316"``.
    report: str
    #: Full IRI of the source ``msr:Document``, e.g.
    #: ``"https://w3id.org/msr-kg/data#ORNL-TM-2316"``.
    document_iri: str
    #: The evidence sentence shown to the reviewer.
    sentence_text: str
    #: Start offset into that report's ``normalized.txt``.
    start_offset: int
    #: End offset into that report's ``normalized.txt``.
    end_offset: int


@dataclass(frozen=True)
class Candidate:
    """A candidate term surviving lexical/miss discovery and novelty scoring."""

    #: Normalized/case-folded surface term, e.g. ``"solubility"``.
    term: str
    #: Discovery source: ``"lexical"`` or ``"miss"``.
    source: str
    #: Curated-set evidence items (may be empty until attached).
    evidence: tuple[Evidence, ...]
    #: Document frequency over the 637-doc corpus (set by the scorer).
    doc_frequency: int = 0
    #: Original surface form (for miss-sourced salt-formula spans).
    surface_form: str = ""


@dataclass(frozen=True)
class Placement:
    """LLM-asserted placement claims for a triaged candidate (design.md D6).

    Every field is a claim the classifier proposed, not a verified fact —
    reviewer-verifiable, never dereferenced against the live QUDT/INIS
    catalogs. Only the fields relevant to the candidate's confirmed
    ``kind`` are expected to be set; the rest stay at their defaults.
    """

    #: For ``kind=class`` — the LLM-claimed broader class.
    broader_class: str | None = None
    #: For ``kind=property`` — a concrete ``qk:`` IRI if the model asserted
    #: one, else ``None``.
    quantity_kind: str | None = None
    #: For ``kind=property`` — a concrete ``unit:`` IRI if asserted, else
    #: ``None`` (left unset when ambiguous, per design.md D6).
    canonical_unit: str | None = None
    #: For ``kind=relation`` — the claimed domain class.
    domain: str | None = None
    #: For ``kind=relation`` — the claimed range class.
    range_: str | None = None
    #: QUDT/INIS reference strings — reviewer-verifiable claims, never
    #: dereferenced.
    external_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class TriagedCandidate:
    """A candidate with its confirmed kind and asserted placement.

    The shared input every downstream mining module (novelty, proposals,
    auto_accept) builds against.
    """

    candidate: Candidate
    #: One of :data:`VALID_KINDS`.
    kind: str
    placement: Placement
