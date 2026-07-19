"""Layered, precision-biased linking pipeline over segmented text (chunk 6, D2/D4/D5/D7).

Consumes chunk-5's ``data/corpus/{report#}/segments.jsonl`` and links every
recognized span to a known vocab concept, ontology class, or loaded salt
individual -- or, when no layer settles it, records it as ``novel`` (the
miss output chunk 8 mines). Layer 1 (OCR normalization) is chunk 5's
pre-pass over ``normalized.txt``; this module owns layers 2-5:

2. **Expanded exact matching** -- :func:`msr_extraction.seeding.build_matcher`
   (the caller seeds this once per run; :func:`link_segment` just calls
   ``matcher.match``).
3. **Chemical-formula normalizer** -- salt-shaped candidate spans (see
   :func:`_find_formula_candidates`) are handed to
   :func:`msr_extraction.formula.normalize_salt_span`; a resulting CURIE
   that is in the run's known-IRI set links to the composed salt
   individual (never a fabricated one -- ``normalize_salt_span`` itself
   refuses to guess a composition, and this layer additionally refuses to
   link to a canonical IRI the graph hasn't actually loaded).
4. **Bounded rapidfuzz fallback** -- :func:`fuzzy_link`, applied only to the
   same formula-shaped candidate spans layers 2-3 left unresolved; a high
   threshold and a minimum token length (both configuration values, see
   ``Config.fuzzy_threshold``/``fuzzy_min_token_length``) keep it a
   long-tail fallback, never a primary path -- and it only ever links to an
   *existing* label, never inventing a novelty candidate itself.
5. **Flash disambiguation** -- remaining unresolved candidate spans go to an
   injected ``disambiguator`` callable (the CLI wires this to
   :func:`msr_extraction.disambiguation.disambiguate`); no disambiguator
   (or a "novel"/rejected result) records the span as ``novel``.

Overlap precedence is mostly "already resolved wins, never re-emit a
duplicate" (see :func:`link_segment`'s ``_is_free`` helper; design.md D2:
"the resolving layer is recorded per span") -- with one deliberate
exception: a **successful** layer-3 composed-salt match supersedes an
overlapping layer-2 exact match (never the reverse, and never a *bare*,
unresolved formula candidate), since a vocab concept's altLabel set
commonly includes the bare chemical formula itself (e.g. `voc:flibe`'s
`"LiF-BeF2"` altLabel) -- without this exception a composed mention like
`"LiF-BeF2 (66-34 mol%)"` would resolve to the concept via its exact-match
sub-span rather than the loaded salt individual, contradicting design.md
D3's "a mention carrying a composition resolves to the specific
`msrd:salt-...` individual."

Only stdlib + the pure ``msr_extraction.formula`` module (itself stdlib-only)
are imported at module level; ``rapidfuzz`` is deferred into
:func:`fuzzy_link` so this module -- and anything that merely imports it,
including ``cli.py`` -- stays importable with zero third-party dependencies.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from msr_extraction import formula

if TYPE_CHECKING:
    from msr_extraction.config import Config
    from msr_extraction.graph_reader import KnownEntity
    from msr_extraction.seeding import SeededMatcher

logger = logging.getLogger(__name__)

MSRD = "https://w3id.org/msr-kg/data#"

# A disambiguator callable: (surface, sentence) -> (status, target_iri).
# ``status`` is "linked" or "novel"; ``target_iri`` is set iff "linked".
# Matches the shape of `msr_extraction.disambiguation.disambiguate`'s
# validated result, unpacked into a plain tuple so this module never has to
# import `disambiguation` (which would otherwise be harmless, but the
# narrower dependency keeps the layering exactly D5's "injected" contract).
Disambiguator = Callable[[str, str], "tuple[str, str | None]"]

LAYER_EXACT = 2
LAYER_FORMULA = 3
LAYER_FUZZY = 4
LAYER_FLASH = 5

# --- Formula-candidate span regex -------------------------------------------
#
# Finds salt-shaped spans in raw segment text for layers 3-5 to attempt, in
# addition to (and independent of) whatever the seeded exact matcher (layer
# 2) already recognizes. Deliberately permissive on what counts as a
# "formula token" -- false positives cost nothing here, since layer 3 only
# links when `formula.normalize_salt_span` produces a CURIE *and* that CURIE
# expands to an IRI already in the run's known-IRI set (a structurally
# formula-shaped but unloaded string, e.g. an alloy designation, simply
# falls through to the fuzzy/Flash/novel path like any other unresolved
# span -- it never gets a free pass on precision).
#
# - `_ELEMENT_UNIT`: one capitalized letter, an optional lowercase letter,
#   and optional digits (ASCII or Unicode subscript) -- e.g. "Li", "F",
#   "Be", "F2", "F₂".
# - `_FORMULA_TOKEN`: 1-4 such units back to back (an optional leading
#   stoichiometric coefficient), e.g. "LiF", "BeF2", "ZrF4".
# - separators: "-", the middle dot, bullet, and dot-operator characters
#   `formula.py` already treats as salt separators.
# - an optional trailing inline composition group, e.g. "(66-34 mol%)" or
#   "66-34 mol%" -- mirrors `formula._INLINE_COMPOSITION_RE` loosely; the
#   authoritative parse of it is left to `normalize_salt_span` itself.
_DIGITS = "0-9₀-₉"
_ELEMENT_UNIT = rf"[A-Z][a-z]?[{_DIGITS}]*"
_FORMULA_TOKEN = rf"\d*(?:{_ELEMENT_UNIT}){{1,4}}"
_FORMULA_SEP = r"\s*[-·•⋅]\s*"
_COMPOSITION_TAIL = (
    r"\(?\s*\d+(?:\.\d+)?(?:\s*-\s*\d+(?:\.\d+)?)+\s*mol\s*%\s*\)?"
)
_FORMULA_CANDIDATE_RE = re.compile(
    rf"{_FORMULA_TOKEN}(?:{_FORMULA_SEP}{_FORMULA_TOKEN})+(?:\s*{_COMPOSITION_TAIL})?"
)

_WORD_RE = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class Segment:
    """One sentence from the chunk-5 ``segments.jsonl`` artifact."""

    report: str
    index: int
    text: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class MentionRecord:
    """One recognized span's classification (design.md D7's mention/miss artifact)."""

    report: str
    seg_index: int
    char_start: int
    char_end: int
    surface_form: str
    status: str  # "linked" | "novel"
    target_iri: str | None  # full IRI, set iff status == "linked"
    target_kind: str | None  # "concept" | "class" | "salt", set iff linked
    layer: int  # 2 exact | 3 formula | 4 fuzzy | 5 flash ; novel -> 5
    score: float | None  # set for layer 4 (fuzzy score); None otherwise


def expand_curie(curie: str) -> str:
    """Expand an ``msrd:`` CURIE (as returned by ``formula.normalize_salt_span``)
    to its full IRI; pass a full IRI (or anything else) through unchanged."""
    if curie.startswith(formula.MSRD_PREFIX):
        return MSRD + curie[len(formula.MSRD_PREFIX) :]
    return curie


def _known_labels(known_entities: list[KnownEntity]) -> list[tuple[str, str, str]]:
    """Flatten `known_entities` into ``(label, target_iri, kind)`` triples,
    one per label -- the shape `fuzzy_link` matches against."""
    return [
        (label, entity.target_iri, entity.kind)
        for entity in known_entities
        for label in entity.labels
    ]


def fuzzy_link(
    surface: str,
    known_labels: list[tuple[str, str, str]],
    threshold: float,
    min_token_length: int,
) -> tuple[str, str, float] | None:
    """Bounded rapidfuzz fallback (design.md D4): the long tail only.

    Finds the best-scoring `known_labels` entry for `surface` and returns
    ``(target_iri, kind, score)`` iff the best score is >= `threshold` *and*
    `surface` contains at least one token of length >= `min_token_length`;
    otherwise returns ``None``. Links only to an existing label -- it never
    invents a target, so an over-eager fuzzy hit costs linking precision,
    never novelty-queue pollution (design.md D4/D10).

    `rapidfuzz` is imported here, not at module level, so this module (and
    anything merely importing it, notably `cli.py`) stays importable with
    zero third-party dependencies.
    """
    if not known_labels:
        return None

    tokens = _WORD_RE.findall(surface)
    if not tokens or max(len(tok) for tok in tokens) < min_token_length:
        return None

    from rapidfuzz import fuzz, process

    labels = [label for label, _, _ in known_labels]
    best = process.extractOne(surface, labels, scorer=fuzz.WRatio)
    if best is None:
        return None
    _matched_label, score, index = best
    if score < threshold:
        return None

    _label, target_iri, kind = known_labels[index]
    return (target_iri, kind, float(score))


def _find_formula_candidates(text: str) -> list[tuple[int, int, str]]:
    """Find salt-shaped candidate spans in `text` (see module docstring).

    Returns ``(start, end, surface)`` triples, char offsets local to
    `text` (not yet shifted by a segment's `char_start`).
    """
    return [(m.start(), m.end(), m.group(0)) for m in _FORMULA_CANDIDATE_RE.finditer(text)]


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def link_segment(
    seg: Segment,
    matcher: SeededMatcher,
    known_entities: list[KnownEntity],
    known_iris: set[str],
    config: Config,
    *,
    prompt_prefix: str = "",
    disambiguator: Disambiguator | None = None,
) -> list[MentionRecord]:
    """Link every span in one segment, ordered layers 2 -> 5, precision-biased.

    Offsets on the returned records are absolute (``seg.char_start`` plus
    the local match offset), matching chunk 5's `segments.jsonl` offset
    convention. Results are returned sorted by ``(char_start, char_end)``.

    Overlap precedence is *not* simply "earliest layer wins": a
    **successful layer-3 composed-salt match** (the formula normalizer
    produced a CURIE that expands into `known_iris`) is structurally more
    specific than a layer-2 exact match it overlaps, and supersedes it --
    dropping the overlapped layer-2 record in favor of the salt individual
    (design.md D3's "Salt mention resolves to the loaded individual"
    scenario: e.g. the vocab's `voc:flibe` concept commonly carries a bare
    `"LiF-BeF2"` altLabel, so layer 2 alone would otherwise resolve a
    *composed* `"LiF-BeF2 (66-34 mol%)"` mention to the concept, never the
    individual, since its exact-match sub-span is found first). A *bare*
    formula mention (layer 3 finds no composition, so `normalize_salt_span`
    returns `None`) does **not** supersede anything -- the layer-2 concept
    match stands, preserving D3's bare-formula-to-concept rule.

    Every other overlap (layer 4/5 candidates against anything already
    resolved, including the layer-3 salt spans themselves) keeps the
    simple "already resolved wins, never re-emit a duplicate" rule.

    ``prompt_prefix`` is accepted for interface symmetry with the layer-5
    Flash call (built once per run via `KGSchemaPromptCache` and threaded
    through by the caller into `disambiguator`'s closure); this function
    never uses it directly since `disambiguator` already carries whatever
    context it needs.
    """
    resolved: list[MentionRecord] = []

    def _is_free(start: int, end: int) -> bool:
        return not any(_overlaps(start, end, r.char_start, r.char_end) for r in resolved)

    # Formula-shaped candidate spans, evaluated once up front so layer 3's
    # successful salt resolutions are known *before* layer 2 is applied --
    # this is what lets a composed match supersede an overlapping exact
    # match rather than merely losing an "earliest layer wins" tie.
    candidates: list[tuple[int, int, str, str | None]] = []
    for local_start, local_end, surface in _find_formula_candidates(seg.text):
        start = seg.char_start + local_start
        end = seg.char_start + local_end
        salt_target_iri: str | None = None
        curie = formula.normalize_salt_span(surface)
        if curie is not None:
            expanded = expand_curie(curie)
            if expanded in known_iris:
                salt_target_iri = expanded
        candidates.append((start, end, surface, salt_target_iri))

    salt_spans = [(start, end) for start, end, _surface, salt_iri in candidates if salt_iri is not None]

    def _overlaps_a_salt_span(start: int, end: int) -> bool:
        return any(_overlaps(start, end, s_start, s_end) for s_start, s_end in salt_spans)

    # Layer 2: expanded exact matching (already seeded by the caller) --
    # skipping any span a successful layer-3 salt match overlaps.
    for m in matcher.match(seg.text):
        start = seg.char_start + m.start
        end = seg.char_start + m.end
        if _overlaps_a_salt_span(start, end):
            continue
        if not _is_free(start, end):
            continue
        resolved.append(
            MentionRecord(
                report=seg.report,
                seg_index=seg.index,
                char_start=start,
                char_end=end,
                surface_form=m.surface,
                status="linked",
                target_iri=m.target_iri,
                target_kind=m.kind,
                layer=LAYER_EXACT,
                score=None,
            )
        )

    # Layer 3: emit the successful composed-salt matches.
    for start, end, surface, salt_iri in candidates:
        if salt_iri is None:
            continue
        if not _is_free(start, end):
            continue
        resolved.append(
            MentionRecord(
                report=seg.report,
                seg_index=seg.index,
                char_start=start,
                char_end=end,
                surface_form=surface,
                status="linked",
                target_iri=salt_iri,
                target_kind="salt",
                layer=LAYER_FORMULA,
                score=None,
            )
        )

    # Layers 4-5: whatever candidate spans are still unresolved (bare
    # formulas the formula normalizer couldn't compose, or composed
    # candidates whose canonical IRI isn't in this run's known-IRI set).
    known_labels = _known_labels(known_entities)
    kind_by_iri = {entity.target_iri: entity.kind for entity in known_entities}

    for start, end, surface, _salt_iri in candidates:
        if not _is_free(start, end):
            continue

        # Layer 4: bounded rapidfuzz fallback.
        fuzzy_result = fuzzy_link(
            surface, known_labels, config.fuzzy_threshold, config.fuzzy_min_token_length
        )
        if fuzzy_result is not None:
            target_iri, kind, score = fuzzy_result
            resolved.append(
                MentionRecord(
                    report=seg.report,
                    seg_index=seg.index,
                    char_start=start,
                    char_end=end,
                    surface_form=surface,
                    status="linked",
                    target_iri=target_iri,
                    target_kind=kind,
                    layer=LAYER_FUZZY,
                    score=score,
                )
            )
            continue

        # Layer 5: Flash disambiguation (or novel, with no disambiguator).
        status, target_iri = ("novel", None)
        if disambiguator is not None:
            status, target_iri = disambiguator(surface, seg.text)

        if status == "linked" and target_iri is not None and target_iri in known_iris:
            resolved.append(
                MentionRecord(
                    report=seg.report,
                    seg_index=seg.index,
                    char_start=start,
                    char_end=end,
                    surface_form=surface,
                    status="linked",
                    target_iri=target_iri,
                    target_kind=kind_by_iri.get(target_iri),
                    layer=LAYER_FLASH,
                    score=None,
                )
            )
        else:
            resolved.append(
                MentionRecord(
                    report=seg.report,
                    seg_index=seg.index,
                    char_start=start,
                    char_end=end,
                    surface_form=surface,
                    status="novel",
                    target_iri=None,
                    target_kind=None,
                    layer=LAYER_FLASH,
                    score=None,
                )
            )

    resolved.sort(key=lambda r: (r.char_start, r.char_end))
    return resolved


def _read_segments(report: str, config: Config) -> list[Segment]:
    """Read `config.segments_path(report)` JSONL into `Segment` objects,
    in file order (which is already sentence/report order)."""
    segments: list[Segment] = []
    with config.segments_path(report).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            segments.append(
                Segment(
                    report=obj["report"],
                    index=obj["index"],
                    text=obj["text"],
                    char_start=obj["char_start"],
                    char_end=obj["char_end"],
                )
            )
    return segments


def link_report(
    report: str,
    config: Config,
    matcher: SeededMatcher,
    known_entities: list[KnownEntity],
    known_iris: set[str],
    *,
    prompt_prefix: str = "",
    disambiguator: Disambiguator | None = None,
) -> list[MentionRecord]:
    """Link every segment of `report`'s `segments.jsonl`, report-ordered."""
    records: list[MentionRecord] = []
    for seg in _read_segments(report, config):
        records.extend(
            link_segment(
                seg,
                matcher,
                known_entities,
                known_iris,
                config,
                prompt_prefix=prompt_prefix,
                disambiguator=disambiguator,
            )
        )
    return records


def write_mentions_jsonl(report: str, records: list[MentionRecord], config: Config) -> None:
    """Write `config.mentions_path(report)`: one JSON object per record.

    Deterministic: `records` are already sorted (per segment, and callers
    concatenate segments in report order via `link_report`), so re-running
    over the same inputs produces byte-identical output (design.md D7's
    "regenerated wholesale per run"). UTF-8, ``ensure_ascii=False``, one
    object per line, keys in the artifact's documented order.
    """
    path = config.mentions_path(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            obj = {
                "report": record.report,
                "seg_index": record.seg_index,
                "char_start": record.char_start,
                "char_end": record.char_end,
                "surface_form": record.surface_form,
                "status": record.status,
                "target_iri": record.target_iri,
                "target_kind": record.target_kind,
                "layer": record.layer,
                "score": record.score,
            }
            fh.write(json.dumps(obj, ensure_ascii=False))
            fh.write("\n")
