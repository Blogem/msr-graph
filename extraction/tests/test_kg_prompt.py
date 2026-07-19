"""Tests for the cached KG-schema prompt builder (design.md D6, task 10.6).

A small fake reader (``read_known_entities``/``read_version``, counting
calls) stands in for :class:`msr_extraction.graph_reader.GraphReader` —
these tests are hermetic, no httpx/GraphDB involved.
"""

from __future__ import annotations

from dataclasses import dataclass

from msr_extraction.graph_reader import KnownEntity
from msr_extraction.kg_prompt import KGSchemaPromptCache, build_prefix


@dataclass
class FakeReader:
    """A fake reader tracking how many times its methods are called."""

    entities: list[KnownEntity]
    version: str | None = "v1"
    read_known_entities_calls: int = 0
    read_version_calls: int = 0

    def read_known_entities(self) -> list[KnownEntity]:
        self.read_known_entities_calls += 1
        return list(self.entities)

    def read_version(self) -> str | None:
        self.read_version_calls += 1
        return self.version


_CONCEPT_A = KnownEntity(
    target_iri="https://w3id.org/msr-kg/vocab#alpha",
    labels=("alpha", "Alpha compound"),
    kind="concept",
)
_CONCEPT_B = KnownEntity(
    target_iri="https://w3id.org/msr-kg/vocab#beta",
    labels=("beta",),
    kind="concept",
)
_CLASS_A = KnownEntity(
    target_iri="https://w3id.org/msr-kg/ontology#MoltenSalt",
    labels=("MoltenSalt",),
    kind="class",
)
_SALT_A = KnownEntity(
    target_iri="https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0",
    labels=("LiF-BeF2 (34.0-66.0)",),
    kind="salt",
)


def test_build_prefix_is_byte_identical_across_repeated_calls() -> None:
    reader = FakeReader(entities=[_CONCEPT_A, _CONCEPT_B, _CLASS_A, _SALT_A])

    first = build_prefix(reader)
    second = build_prefix(reader)

    assert first == second
    assert isinstance(first, str)


def test_build_prefix_normalizes_in_memory_ordering() -> None:
    ordered_reader = FakeReader(entities=[_CONCEPT_A, _CONCEPT_B, _CLASS_A, _SALT_A])
    shuffled_reader = FakeReader(entities=[_SALT_A, _CLASS_A, _CONCEPT_B, _CONCEPT_A])

    assert build_prefix(ordered_reader) == build_prefix(shuffled_reader)


def test_build_prefix_groups_by_fixed_kind_order_then_target_iri() -> None:
    # Entities deliberately out of both kind-group and IRI order.
    reader = FakeReader(entities=[_SALT_A, _CONCEPT_B, _CLASS_A, _CONCEPT_A])

    prefix = build_prefix(reader)
    lines = prefix.splitlines()

    kinds = [line.split("\t", 1)[0] for line in lines]
    assert kinds == ["concept", "concept", "class", "salt"]

    concept_iris = [line.split("\t")[1] for line in lines if line.startswith("concept")]
    assert concept_iris == sorted(concept_iris)
    assert concept_iris == [_CONCEPT_A.target_iri, _CONCEPT_B.target_iri]


def test_build_prefix_sorts_labels_within_an_entity() -> None:
    reader = FakeReader(entities=[_CONCEPT_A])

    prefix = build_prefix(reader)

    label_field = prefix.strip().split("\t")[2]
    assert label_field == "|".join(sorted(_CONCEPT_A.labels))


def test_build_prefix_excludes_mention_shaped_instance_data() -> None:
    # The reader (as documented) only ever returns concept/class/salt
    # entities — never mention/measurement instances. Prove the prefix
    # can't surface a mention-shaped IRI even when checked explicitly.
    reader = FakeReader(entities=[_CONCEPT_A, _CONCEPT_B, _CLASS_A, _SALT_A])

    prefix = build_prefix(reader)

    assert "mention-ORNL-TM-2316-10-18" not in prefix


def test_cache_reuses_prefix_without_rebuilding_when_version_unchanged() -> None:
    reader = FakeReader(entities=[_CONCEPT_A, _CONCEPT_B], version="v1")
    cache = KGSchemaPromptCache()

    first = cache.get(reader)
    second = cache.get(reader)

    assert first == second
    assert reader.read_known_entities_calls == 1
    assert reader.read_version_calls == 2


def test_cache_rebuilds_when_version_changes() -> None:
    reader = FakeReader(entities=[_CONCEPT_A], version="v1")
    cache = KGSchemaPromptCache()

    first = cache.get(reader)
    assert reader.read_known_entities_calls == 1

    reader.version = "v2"
    reader.entities = [_CONCEPT_A, _CONCEPT_B]
    second = cache.get(reader)

    assert reader.read_known_entities_calls == 2
    assert second != first
    assert _CONCEPT_B.target_iri in second


def test_cache_starts_empty_and_builds_on_first_get() -> None:
    reader = FakeReader(entities=[_CONCEPT_A], version=None)
    cache = KGSchemaPromptCache()

    prefix = cache.get(reader)

    assert reader.read_known_entities_calls == 1
    assert _CONCEPT_A.target_iri in prefix
