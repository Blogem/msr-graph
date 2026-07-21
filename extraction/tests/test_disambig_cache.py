"""Tests for the cross-run disambiguation cache (persist-disambiguation-cache).

Covers the hash key (stable, order-independent), save->load round-trip, and
the best-effort load paths (missing file, corrupt JSON, hash mismatch) that
must yield an empty cache without raising.
"""

from __future__ import annotations

from msr_extraction import disambig_cache

IRIS = {"https://w3id.org/msr-kg/data#salt-A", "https://w3id.org/msr-kg/vocab#density"}

ENTRIES = {
    "LiF-BeF2": ("linked", "https://w3id.org/msr-kg/data#salt-A"),
    "NaCl-KCl": ("novel", None),
}


def test_known_iris_hash_is_stable_and_order_independent() -> None:
    a = disambig_cache.known_iris_hash({"z", "a", "m"})
    b = disambig_cache.known_iris_hash({"m", "z", "a"})
    assert a == b
    assert a != disambig_cache.known_iris_hash({"z", "a"})


def test_save_then_load_round_trips_entries(tmp_path) -> None:
    path = tmp_path / "cache.json"
    h = disambig_cache.known_iris_hash(IRIS)
    disambig_cache.save_cache(path, h, ENTRIES)

    loaded = disambig_cache.load_cache(path, h)
    assert loaded == ENTRIES


def test_load_returns_empty_on_missing_file(tmp_path) -> None:
    assert disambig_cache.load_cache(tmp_path / "nope.json", "anyhash") == {}


def test_load_returns_empty_on_corrupt_json(tmp_path) -> None:
    path = tmp_path / "cache.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert disambig_cache.load_cache(path, "anyhash") == {}


def test_load_returns_empty_on_hash_mismatch(tmp_path) -> None:
    path = tmp_path / "cache.json"
    disambig_cache.save_cache(path, "hash-when-written", ENTRIES)
    assert disambig_cache.load_cache(path, "different-hash") == {}


def test_load_drops_malformed_entries(tmp_path) -> None:
    path = tmp_path / "cache.json"
    h = "h"
    # Hand-write a store mixing a valid entry with malformed ones.
    path.write_text(
        '{"known_iris_hash": "h", "entries": {'
        '"good": {"status": "novel", "target_iri": null}, '
        '"bad_status": {"status": "maybe", "target_iri": null}, '
        '"bad_target": {"status": "linked", "target_iri": 42}}}',
        encoding="utf-8",
    )
    loaded = disambig_cache.load_cache(path, h)
    assert loaded == {"good": ("novel", None)}


def test_save_creates_parent_directories(tmp_path) -> None:
    path = tmp_path / "nested" / "dir" / "cache.json"
    disambig_cache.save_cache(path, "h", ENTRIES)
    assert path.exists()
