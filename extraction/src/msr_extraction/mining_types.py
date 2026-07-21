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

#: The explicit "not a genuine novel ontology concept" triage verdict
#: (design.md D4/refine-mine-salience) -- an OCR fragment, an acronym, a
#: proper noun that slipped candidate enumeration, or generic boilerplate.
#: Deliberately NOT a member of :data:`VALID_KINDS`: it is a terminal
#: drop-the-candidate verdict, not a routable kind a downstream module
#: (proposals/auto_accept) ever builds a bundle for.
KIND_REJECT = "reject"

#: The complete set of valid, *routable* :attr:`TriagedCandidate.kind`
#: values -- excludes :data:`KIND_REJECT`, which is a distinct terminal
#: verdict handled separately by callers (see ``triage.classify``).
VALID_KINDS = frozenset({KIND_PROPERTY, KIND_CLASS, KIND_INSTANCE, KIND_RELATION})

_SLUG_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

#: CURIE prefixes a placement value is allowed to already carry (design.md
#: D6/D7's `msr:`/`voc:` core+vocab namespaces, plus `msrd:` for the rare
#: case a placement points at a data-graph individual). Any other prefix
#: (including no prefix at all combined with punctuation) is unsafe.
_SAFE_CURIE_PREFIXES = frozenset({"msr", "msrd", "voc"})

#: A CURIE local name: starts with a letter, then letters/digits/`_`/`-`.
_CURIE_LOCAL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")

#: A bare local name (no prefix, no punctuation): starts with a letter,
#: then letters/digits/`_` only -- deliberately narrower than the CURIE
#: local-name pattern (no `-`) since a bare value is auto-prefixed
#: `msr:{value}` and Turtle prefixed names never use `-` internally in this
#: ontology's own naming convention.
_BARE_LOCAL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

#: Characters that are never allowed inside a full-IRI placement value, even
#: though the IRI-position hostname/path syntax is otherwise permissive.
#: Mirrors the RFC 3987 `<>"{}|\^\`` production plus backtick.
_FULL_IRI_UNSAFE_CHARS = frozenset('<>"{}|\\^`')


def safe_type_ref(value: str | None) -> str | None:
    """Normalize an LLM-asserted placement value into a SPARQL-safe term, or ``None``.

    Every ``Placement.broader_class``/``.domain``/``.range_`` value is an
    unverified string lifted straight from the DeepSeek triage JSON reply
    (``triage._build_placement`` only checks "non-empty str") and is spliced
    directly into CURIE/IRI *term* position in a SPARQL ``INSERT DATA``
    (``a msr:{broader}``, ``rdfs:domain msr:{domain}``, ...) -- a position
    ``proposals._escape_literal`` does not protect, since that helper only
    escapes *literal* position. This is the single validation choke point
    every such value must pass through before it reaches that position:

    - a full IRI (contains ``"://"``): returned bracketed (``"<IRI>"``) only
      if it contains no whitespace, no ASCII control character, and none of
      the characters in :data:`_FULL_IRI_UNSAFE_CHARS`; otherwise ``None``.
    - a CURIE ``"prefix:local"`` whose prefix is one of ``msr``/``msrd``/
      ``voc`` and whose local part matches ``^[A-Za-z][A-Za-z0-9_-]*$``:
      returned unchanged.
    - a bare local name matching ``^[A-Za-z][A-Za-z0-9_]*$``: returned as
      ``"msr:{value}"``.
    - anything else (punctuation, spaces, ``;``/``}``/``.``, newlines,
      empty/``None``, any other prefix, a malformed CURIE): ``None`` -- the
      caller must reject (proposal builders) or skip (the mine-runner
      individual path) rather than write it.
    """
    if not value:
        return None

    if "://" in value:
        if any(ch.isspace() for ch in value):
            return None
        if any(ord(ch) < 0x20 for ch in value):
            return None
        if any(ch in _FULL_IRI_UNSAFE_CHARS for ch in value):
            return None
        return f"<{value}>"

    if ":" in value:
        prefix, _, local = value.partition(":")
        if prefix in _SAFE_CURIE_PREFIXES and _CURIE_LOCAL_RE.fullmatch(local):
            return value
        return None

    if _BARE_LOCAL_RE.fullmatch(value):
        return f"msr:{value}"

    return None


def local_name(type_ref: str) -> str:
    """Return the local/trailing name of a :func:`safe_type_ref` output.

    Used to derive a reviewer-facing label or a companion relation name
    from an already-sanitized term without re-touching the raw LLM string:
    a bracketed full IRI (``"<...#Foo>"``/``"<.../Foo>"``) yields the part
    after the last ``#``/``/``; a CURIE (``"msr:Foo"``) yields the part
    after the ``:``; anything else (already a bare local name) is returned
    unchanged.
    """
    value = type_ref
    if value.startswith("<") and value.endswith(">"):
        inner = value[1:-1]
        for sep in ("#", "/"):
            if sep in inner:
                return inner.rsplit(sep, 1)[-1]
        return inner
    if ":" in value:
        return value.split(":", 1)[1]
    return value


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
    #: One of :data:`VALID_KINDS`, or :data:`KIND_REJECT` for a well-formed
    #: reject verdict (design.md D4) -- callers routing by kind MUST check
    #: for :data:`KIND_REJECT` before treating ``kind`` as routable.
    kind: str
    placement: Placement
