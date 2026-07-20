"""Cross-run persistence for layer-5 disambiguation outcomes (persist-disambiguation-cache).

The layer-5 Flash outcomes are pure ``surface -> (status, target_iri)``
mappings, so they can be saved after a run and reused on the next one to skip
the DeepSeek calls entirely. The store is tagged with a hash of the run's
**known-IRI set** — the exact set that seeds the matcher and validates every
link — so it is reused only while the set of linkable entities is unchanged;
loading new salts/concepts changes the hash and invalidates the store,
giving previously-``novel`` surfaces another chance to link (design D2).

All load paths are best-effort: a missing, unreadable, or hash-mismatched
store yields an empty cache and never raises — the cache is an optimization,
not a correctness dependency.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# One outcome: (status, target_iri) where status is "linked" | "novel" and
# target_iri is set iff "linked". Mirrors the in-memory disambiguation cache.
Outcome = "tuple[str, str | None]"


def known_iris_hash(known_iris: set[str]) -> str:
    """Return a stable, order-independent SHA-256 hex digest of the IRI set."""
    joined = "\n".join(sorted(known_iris))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def load_cache(path: Path, expected_hash: str) -> dict[str, tuple[str, str | None]]:
    """Return the persisted ``surface -> (status, target_iri)`` map, or ``{}``.

    Returns ``{}`` (never raises) when the file is absent, unreadable, not
    valid JSON, structurally unexpected, or tagged with a hash other than
    ``expected_hash`` (design D2/D3).
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        return {}
    try:
        doc = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("disambig-cache: %s is not valid JSON; ignoring", path)
        return {}
    if not isinstance(doc, dict) or doc.get("known_iris_hash") != expected_hash:
        return {}
    entries = doc.get("entries")
    if not isinstance(entries, dict):
        return {}
    out: dict[str, tuple[str, str | None]] = {}
    for surface, rec in entries.items():
        if not isinstance(surface, str) or not isinstance(rec, dict):
            continue
        status = rec.get("status")
        target_iri = rec.get("target_iri")
        if status not in ("linked", "novel"):
            continue
        if target_iri is not None and not isinstance(target_iri, str):
            continue
        out[surface] = (status, target_iri)
    return out


def save_cache(
    path: Path, iris_hash: str, entries: dict[str, tuple[str, str | None]]
) -> None:
    """Write the ``surface -> (status, target_iri)`` map tagged with ``iris_hash``.

    Creates parent directories as needed. Entries are sorted by surface for
    deterministic, diff-friendly output.
    """
    doc = {
        "known_iris_hash": iris_hash,
        "entries": {
            surface: {"status": status, "target_iri": target_iri}
            for surface, (status, target_iri) in sorted(entries.items())
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
