"""Candidate triage: cheap context signals + a stubbed-in-tests Flash classifier.

Each candidate surviving lexical/miss discovery and novelty scoring is
triaged into exactly one primary kind — ``property``, ``class``,
``instance``, or ``relation`` (design.md D3). A cheap, lexical/co-occurrence
context signal (:func:`signal_kind`) proposes a kind first — chunk 6's
``spacy.blank`` pipeline has no parser, so there is no dependency-parse
S-V-O extraction here, only regex-based surface patterns. DeepSeek V4 Flash
(:func:`classify`) then confirms the kind and proposes a placement (broader
class, quantityKind, canonicalUnit, domain/range) grounded by the
candidate's evidence, reusing the chunk-6 ``FlashClient``/``Completer``
protocol and the chunk-6 KG-schema prompt builder
(``kg_prompt.KGSchemaPromptCache``, imported not re-derived) verbatim.

As in chunk 6 (D5), the call uses DeepSeek JSON output mode, which
guarantees syntactically valid JSON but not field-level structure, so the
parsed object is always validated app-side (shape check only — the
QUDT/INIS-allowlist guard lives downstream in ``proposals.py``, not here).
Malformed or schema-violating output drops the candidate rather than
emitting a malformed proposal; this module mirrors ``disambiguation.py``'s
never-raise robustness.

The client is injected via the :class:`~msr_extraction.disambiguation.Completer`
protocol and is stubbed in every test — this module never contacts a live
model under test.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from msr_extraction.disambiguation import Completer
from msr_extraction.mining_types import KIND_REJECT, VALID_KINDS, Placement, TriagedCandidate

if TYPE_CHECKING:
    from msr_extraction.mining_types import Candidate

# -- Context signals (design.md D3) — lexical/co-occurrence only, no parser --

# A numeric value followed (or preceded) by a recognized physical unit,
# within a short window — mirrors curated.py's SOLUBILITY_RE window/unit
# set, generalized beyond "solubility" to any property-bearing candidate.
_NUMBER_TOKEN = r"\d[\d.,]*"
_UNIT_TOKEN = (
    r"(?:mole\s?%|wt\s?%|mol\s?%|atoms?\s?%|ppm|g/cm\w*|mg/|moles?/|mol/|"
    r"m?pa\b|°?c\b|°?k\b|kj/|cal/|×?10\s*-?\d|x\s?10)"
)
_PROPERTY_RE = re.compile(
    rf"{_NUMBER_TOKEN}\s*{_UNIT_TOKEN}",
    re.IGNORECASE,
)

# A compound-formula-shaped surface: an element symbol (capital + optional
# lowercase) immediately followed by a digit, e.g. "BeF2", "LiF-BeF2". No
# leading word-boundary anchor — concatenated element symbols in a formula
# (e.g. the "F2" in "BeF2") directly follow the previous element's letters,
# so anchoring on a boundary would never match real formula surfaces.
_FORMULA_RE = re.compile(r"[A-Z][a-z]?\d")

# Named-reactor surfaces (MSRE, INOR-8-era report vocabulary) — a small,
# readable allowlist rather than a general NER pass.
_REACTOR_RE = re.compile(
    r"\b(?:MSRE|MSBR|ARE|reactor)\b",
    re.IGNORECASE,
)

# Material / moderator / "constructed of X" context.
_CLASS_RE = re.compile(
    r"graphite.{0,60}?moderat\w*"
    r"|moderat\w*.{0,60}?graphite"
    r"|\bmoderator\b"
    r"|constructed\s+of\b"
    r"|\bmoderated\b",
    re.IGNORECASE | re.DOTALL,
)

# A predicate-like frame linking the candidate to a known entity, e.g.
# "graphite-moderated", "moderated by graphite".
_RELATION_RE = re.compile(
    r"\w+-moderated\b|moderated\s+by\s+\w+",
    re.IGNORECASE,
)


def signal_kind(candidate: Candidate) -> str | None:
    """Propose a cheap, lexical context-signal kind for ``candidate``, or ``None``.

    Scans the candidate's evidence sentence text (case-insensitive) for
    small, readable regexes:

    - a numeric value co-occurring with a recognized physical unit ->
      ``"property"``;
    - a compound-formula-shaped surface or a named-reactor surface ->
      ``"instance"`` (miss-sourced candidates, ``source == "miss"``,
      default to ``"instance"`` since they are salt-formula spans by
      construction);
    - material/"constructed of X"/moderator context -> ``"class"``;
    - a predicate-like frame co-occurring with a known entity (e.g.
      "graphite-moderated") -> ``"relation"``.

    Returns the best single guess, checked in
    property -> instance -> class -> relation priority order (the order the
    signals are listed above), or ``None`` when no signal fires. This is a
    hint for :func:`classify`, not a final decision — the Flash classifier
    confirms or overrides it.
    """
    text = " ".join(evidence.sentence_text for evidence in candidate.evidence)

    if _PROPERTY_RE.search(text):
        return "property"

    if _FORMULA_RE.search(text) or _REACTOR_RE.search(text) or candidate.source == "miss":
        return "instance"

    if _CLASS_RE.search(text):
        return "class"

    if _RELATION_RE.search(text):
        return "relation"

    return None


def _build_user_prompt(candidate: Candidate, signal: str | None) -> str:
    """Build the per-candidate user prompt appended to the cached KG-schema prefix.

    Includes the literal word "json" (DeepSeek's JSON output mode requires
    it to appear somewhere in the prompt) and presents the candidate term,
    the cheap context-signal hint, and its evidence sentences. Instructs
    the model to return the explicit ``"reject"`` kind (design.md D4,
    refine-mine-salience) for a candidate that is NOT a genuine novel
    ontology concept — candidate enumeration is precision-limited on noisy
    OCR, so the classifier is the semantic filter of last resort.
    """
    sentences = "\n".join(
        f'- "{evidence.sentence_text}"' for evidence in candidate.evidence
    )
    signal_line = signal if signal is not None else "unclear"
    return (
        "Triage the following candidate term against the knowledge graph "
        "schema above and classify it into exactly one primary kind, or "
        "reject it if it is not a genuine novel ontology concept.\n\n"
        f'Candidate term: "{candidate.term}"\n'
        f"Context-signal hint: {signal_line}\n"
        f"Evidence sentences:\n{sentences}\n\n"
        "Respond with a single json object with this shape:\n"
        '{"kind":"property|class|instance|relation|reject",'
        '"broaderClass":"<iri-or-label>?",'
        '"quantityKind":"<qk IRI>?",'
        '"canonicalUnit":"<unit IRI>?",'
        '"domain":"?","range":"?",'
        '"externalRefs":["..."]}\n\n'
        "Only fields relevant to the confirmed kind need be set; leave the "
        "rest unset. In particular, LEAVE canonicalUnit and quantityKind "
        "UNSET whenever the unit is ambiguous or not confidently known — "
        "do not guess a unit. Return \"kind\":\"reject\" (leaving every "
        "other field unset) if the candidate term is an OCR fragment, an "
        "acronym, a proper noun (a person, organization, or place name "
        "that slipped candidate enumeration), or generic boilerplate — "
        "i.e. not a real, novel ontology concept. Return only the json "
        "object, no other text."
    )


def _optional_str(value: object) -> str | None:
    """Return ``value`` if it is a non-empty ``str``, else ``None``."""
    if isinstance(value, str) and value:
        return value
    return None


def _build_placement(parsed: dict) -> Placement:
    """Build a :class:`Placement` from the optional fields of ``parsed``.

    Keeps only ``str`` values; fields that are missing, ``None``, or of the
    wrong type stay at the ``Placement`` default (``None``/``()``).
    ``externalRefs`` becomes a tuple of the ``str`` entries in the list
    (non-str entries are dropped); a non-list value is treated as absent.
    """
    external_refs_raw = parsed.get("externalRefs")
    external_refs: tuple[str, ...] = ()
    if isinstance(external_refs_raw, list):
        external_refs = tuple(
            item for item in external_refs_raw if isinstance(item, str)
        )

    return Placement(
        broader_class=_optional_str(parsed.get("broaderClass")),
        quantity_kind=_optional_str(parsed.get("quantityKind")),
        canonical_unit=_optional_str(parsed.get("canonicalUnit")),
        domain=_optional_str(parsed.get("domain")),
        range_=_optional_str(parsed.get("range")),
        external_refs=external_refs,
    )


def classify(
    candidate: Candidate,
    signal: str | None,
    prompt_prefix: str,
    client: Completer,
) -> TriagedCandidate | None:
    """Confirm ``candidate``'s kind and proposed placement via Flash.

    Builds a user prompt from ``candidate``/``signal``, calls
    ``client.complete(prompt_prefix, user_prompt)``, and validates the
    result app-side (shape check only — the QUDT/INIS-allowlist guard
    lives downstream in ``proposals.py``, not here). There are exactly
    three outcomes (design.md D4, refine-mine-salience):

    - malformed JSON, a non-dict payload, any exception raised by the
      client, or a missing/non-string/unrecognized ``kind`` (one that is
      neither in :data:`~msr_extraction.mining_types.VALID_KINDS` nor
      :data:`~msr_extraction.mining_types.KIND_REJECT`) -> ``None`` (a
      malformed drop — the caller cannot distinguish *why* it was
      dropped, only that no proposal should be emitted);
    - a well-formed explicit reject verdict (``kind == KIND_REJECT``) ->
      a :class:`TriagedCandidate` with ``kind=KIND_REJECT`` and a default
      (empty) :class:`Placement` — distinct from ``None`` so callers can
      count/log it separately from a malformed drop, even though neither
      outcome ever reaches a routable kind;
    - otherwise (``kind`` in ``VALID_KINDS``), build a :class:`Placement`
      from the optional fields and return a routable
      :class:`TriagedCandidate`.

    Never raises: any anomaly drops the candidate rather than emitting a
    malformed proposal (design.md D3, mirroring
    :func:`msr_extraction.disambiguation.disambiguate`'s never-raise
    style). Does not dereference any external ref.
    """
    user_prompt = _build_user_prompt(candidate, signal)

    try:
        raw = client.complete(prompt_prefix, user_prompt)
    except Exception:
        return None

    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None

    if not isinstance(parsed, dict):
        return None

    kind = parsed.get("kind")
    if not isinstance(kind, str) or (kind not in VALID_KINDS and kind != KIND_REJECT):
        return None

    if kind == KIND_REJECT:
        return TriagedCandidate(candidate=candidate, kind=KIND_REJECT, placement=Placement())

    placement = _build_placement(parsed)
    return TriagedCandidate(candidate=candidate, kind=kind, placement=placement)


def triage_candidate(
    candidate: Candidate,
    prompt_prefix: str,
    client: Completer,
) -> TriagedCandidate | None:
    """Triage ``candidate`` end-to-end: cheap signal, then Flash confirmation.

    Computes :func:`signal_kind` and delegates to :func:`classify`,
    propagating whichever of the three outcomes it returns unchanged: a
    routable :class:`TriagedCandidate` (``kind`` in
    :data:`~msr_extraction.mining_types.VALID_KINDS`), a reject
    :class:`TriagedCandidate` (``kind ==``
    :data:`~msr_extraction.mining_types.KIND_REJECT`), or ``None`` (a
    malformed drop).
    """
    signal = signal_kind(candidate)
    return classify(candidate, signal, prompt_prefix, client)
