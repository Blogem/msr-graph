"""spaCy matcher seeding from the known-entity set (task 3.4, design.md D1/D2).

Builds a fresh spaCy `EntityRuler` from the graph's known entities at the
start of every extraction run -- no pattern set is persisted between runs,
so a concept promoted into a core graph by the evolution loop (chunks 8->9)
is seeded on the very next run with no separate refresh signal
(specs/entity-ruler-seeding/spec.md, "Approved evolution concepts reach NER
on the next run").

This is layer 2 of the design.md D2 layered matcher ("expanded exact
matching"): every label's `variants.generate_variants()` expansion becomes a
cheap exact pattern rather than requiring fuzzy matching, and the ruler's
`phrase_matcher_attr="LOWER"` makes every pattern case-insensitive on top of
that.

Stdlib + `msr_extraction.variants`/`graph_reader` only at import time --
`import spacy` is deferred into `build_matcher` so this module (and anything
that merely imports it) never requires spaCy to be installed just to load.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from msr_extraction import variants

if TYPE_CHECKING:
    from msr_extraction.graph_reader import KnownEntity

# The single label every entity-ruler pattern is tagged with; the target IRI
# and kind travel separately via the pattern `id` (-> `ent.ent_id_`) and
# `target_index`, since spaCy entity labels are meant to be coarse types, not
# individual IRIs.
_ENTITY_LABEL = "MSR_ENTITY"


@dataclass(frozen=True)
class Match:
    """One recognized span, resolved to its known-entity target."""

    start: int  # char offset in the input text
    end: int  # char offset (exclusive)
    surface: str  # matched surface text
    target_iri: str
    kind: str  # "concept" | "class" | "salt"


@dataclass
class SeededMatcher:
    """A spaCy pipeline seeded with entity-ruler patterns, plus the IRI index.

    ``target_index`` maps an entity-ruler pattern ``id`` (== ``target_iri``,
    since patterns are minted with ``id=entity.target_iri``) to its
    ``(target_iri, kind)`` pair, letting :meth:`match` resolve a recognized
    span's ``ent.ent_id_`` back to the entity it came from.
    """

    target_index: dict[str, tuple[str, str]]
    _nlp: Any = field(repr=False)

    def match(self, text: str) -> list[Match]:
        """Run the pipeline over `text` and return the recognized matches.

        For each entity in ``doc.ents`` whose ``ent_id_`` is present in
        ``target_index`` (i.e. it came from a seeded pattern, not some other
        pipeline component), emits a :class:`Match` with the entity's
        char offsets (``ent.start_char``/``ent.end_char``), surface text
        (``ent.text``), and the resolved ``target_iri``/``kind``. Entities
        with no ``ent_id_`` (unset, or not one of ours) are ignored.

        Results are sorted by ``start`` offset for deterministic output --
        matching the entity-ruler's default overlap resolution (first/
        longest match wins per span), spaCy's ``doc.ents`` is already
        non-overlapping and start-ordered, so this sort is a determinism
        guarantee rather than a correction.
        """
        doc = self._nlp(text)
        results: list[Match] = []
        for ent in doc.ents:
            target = self.target_index.get(ent.ent_id_)
            if target is None:
                continue
            target_iri, kind = target
            results.append(
                Match(
                    start=ent.start_char,
                    end=ent.end_char,
                    surface=ent.text,
                    target_iri=target_iri,
                    kind=kind,
                )
            )
        results.sort(key=lambda m: m.start)
        return results


def build_matcher(known_entities: list[KnownEntity], *, nlp: Any = None) -> SeededMatcher:
    """Build a fresh :class:`SeededMatcher` from `known_entities`.

    Rebuilt from scratch on every call -- nothing is persisted or cached
    between calls (design.md D1: "rebuilt from the current graph each
    time"). Steps:

    - ``nlp = nlp or spacy.blank("en")`` (``import spacy`` deferred here) --
      a rules-first blank pipeline is sufficient for the curated known-entity
      set (design.md Open Questions: "EntityRuler alone vs. + a blank/
      statistical model"), and keeps matching deterministic (no statistical
      component in the loop).
    - Add an ``"entity_ruler"`` pipe configured with
      ``phrase_matcher_attr="LOWER"`` for case-insensitive matching on top of
      the generated variants.
    - Iterate ``known_entities`` sorted by ``target_iri`` (determinism even
      if the caller's list isn't pre-sorted); for each label, for each
      ``variants.generate_variants(label)`` variant, add a pattern
      ``{"label": "MSR_ENTITY", "pattern": variant, "id": entity.target_iri}``.
      Empty/whitespace-only variants (``generate_variants`` already excludes
      these) are skipped.
    - Record ``target_index[entity.target_iri] = (entity.target_iri, entity.kind)``.

    Note on overlap/ambiguity: if two entities' variants collide on the same
    surface text, or patterns for the same entity overlap in the text, the
    ``EntityRuler``'s default (``overwrite_ents=False``, longest-match-wins
    among non-overlapping candidates) resolution applies -- this module does
    not add custom conflict resolution on top of it.
    """
    if nlp is None:
        # deferred import: `import spacy` belongs inside this function body
        # so the module imports with zero third-party deps at load time.
        import spacy

        nlp = spacy.blank("en")

    ruler = nlp.add_pipe("entity_ruler", config={"phrase_matcher_attr": "LOWER"})

    target_index: dict[str, tuple[str, str]] = {}
    patterns: list[dict[str, str]] = []

    for entity in sorted(known_entities, key=lambda e: e.target_iri):
        for label in entity.labels:
            for variant in variants.generate_variants(label):
                if not variant:
                    continue
                patterns.append(
                    {"label": _ENTITY_LABEL, "pattern": variant, "id": entity.target_iri}
                )
        target_index[entity.target_iri] = (entity.target_iri, entity.kind)

    ruler.add_patterns(patterns)

    return SeededMatcher(target_index=target_index, _nlp=nlp)
