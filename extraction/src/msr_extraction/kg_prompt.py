"""Cached, byte-stable KG-schema prompt builder (design.md D6, tasks 7.1/7.2).

Serializes the ontology TBox, SKOS vocab, and salt catalog — the entities
:meth:`msr_extraction.graph_reader.GraphReader.read_known_entities` surfaces
— into a deterministic, byte-stable string. This forms the cache-friendly
prefix prepended to every DeepSeek Flash disambiguation call (design.md D5):
identical graph state must yield an identical prefix so the model
provider's prefix-based context cache is never invalidated between runs,
and the prefix is rebuilt only when ``owl:versionInfo`` changes (approvals,
restores) — never otherwise.

Instance data (mentions, measurements, evidence) is never part of this
prefix: the reader this module consumes only ever returns TBox/vocab/salt
schema entities, never mention or measurement instances, so there is
nothing to exclude here beyond consuming that contract as given.

This module is owned by chunk 6 (``ner-entity-linking``) and imported
as-is by chunks 7 (relation extraction) and 8 (novelty triage) — it need
not match chunk 4's Go builder byte-for-byte, only be stable within
itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from msr_extraction.graph_reader import KnownEntity

# Fixed group order the prefix is serialized in — independent of the
# reader's internal iteration/collection order, so the byte-stable output
# never depends on dict/set ordering.
_KIND_ORDER = ("concept", "class", "salt")


class KnownEntityReader(Protocol):
    """The subset of :class:`~msr_extraction.graph_reader.GraphReader` this
    module depends on — kept narrow so a test fake needs only these two
    methods, not a full ``GraphReader``."""

    def read_known_entities(self) -> list[KnownEntity]:
        """Return the known TBox/vocab/salt entities (never instances)."""
        ...

    def read_version(self) -> str | None:
        """Return the current ``owl:versionInfo``, or ``None`` if absent."""
        ...


def _format_entity(entity: KnownEntity) -> str:
    """Render one entity as a single stable line.

    Labels are sorted so the line is identical regardless of the order the
    reader happened to merge/emit them in.
    """
    labels = "|".join(sorted(entity.labels))
    return f"{entity.kind}\t{entity.target_iri}\t{labels}"


def build_prefix(reader: KnownEntityReader) -> str:
    """Serialize the known-entity set into a byte-stable prefix string.

    Reads ``reader.read_known_entities()`` — concepts, ontology
    classes/properties, and the salt catalog (the TBox+vocab+salt schema;
    mention/measurement instances are never part of this set, since the
    reader never returns them) — groups by ``kind`` in the fixed order
    ``("concept", "class", "salt")``, sorts each group by ``target_iri``,
    and emits one line per entity via :func:`_format_entity`.

    The result is identical byte-for-byte across repeated calls over the
    same entity set, regardless of the collection's in-memory order: all
    ordering here is by explicit sort key, never by dict/set/list
    iteration order, and no timestamps or other run-varying data appear.
    """
    entities = reader.read_known_entities()
    grouped: dict[str, list[KnownEntity]] = {kind: [] for kind in _KIND_ORDER}
    for entity in entities:
        grouped.setdefault(entity.kind, []).append(entity)

    lines: list[str] = []
    for kind in _KIND_ORDER:
        for entity in sorted(grouped.get(kind, ()), key=lambda e: e.target_iri):
            lines.append(_format_entity(entity))

    # Any kind outside the fixed order (unexpected, but handled rather than
    # silently dropped) is appended last, sorted by kind then target_iri,
    # so the output stays fully deterministic even in that case.
    extra_kinds = sorted(set(grouped) - set(_KIND_ORDER))
    for kind in extra_kinds:
        for entity in sorted(grouped[kind], key=lambda e: e.target_iri):
            lines.append(_format_entity(entity))

    return "\n".join(lines) + ("\n" if lines else "")


class KGSchemaPromptCache:
    """Version-gated cache over :func:`build_prefix` (design.md D6, task 7.2).

    Rebuilds the prefix only when ``reader.read_version()`` differs from
    the cached version — invalidating exactly on an ontology version bump
    (approvals, restores) and never otherwise, so repeated calls within a
    run (or across runs at the same version) reuse the cached prefix
    without re-querying the known-entity set.
    """

    def __init__(self) -> None:
        """Start with an empty cache — the first :meth:`get` always builds."""
        self._version: str | None = None
        self._prefix: str | None = None
        self._has_cached = False

    def get(self, reader: KnownEntityReader) -> str:
        """Return the cached prefix, rebuilding only on a version change.

        Reads ``reader.read_version()`` first (one cheap query per the
        design). If it matches the cached version and a prefix is already
        cached, returns the cached prefix without calling
        :func:`build_prefix` again. Otherwise rebuilds via
        ``build_prefix(reader)``, stores ``(version, prefix)``, and
        returns the fresh prefix.
        """
        version = reader.read_version()
        if self._has_cached and version == self._version:
            assert self._prefix is not None
            return self._prefix

        prefix = build_prefix(reader)
        self._version = version
        self._prefix = prefix
        self._has_cached = True
        return prefix
