# Design — Persist layer-5 disambiguation across runs

## D1 — Storage: a versioned JSON file under the corpus dir

`data/corpus/disambiguation-cache.json` (path = `config.disambig_cache_path`,
derived from `config.corpus_dir`). The corpus dir is the ./data bind mount,
so a file written by one `make link` container persists for the next run.
`data/corpus/` is gitignored, so the cache is never committed.

Shape:

```json
{
  "known_iris_hash": "<sha256 hex>",
  "entries": {
    "<surface form>": {"status": "linked", "target_iri": "<iri>"},
    "<surface form>": {"status": "novel",  "target_iri": null}
  }
}
```

`entries` mirrors the in-memory `dict[str, (status, target_iri)]` exactly.

## D2 — Invalidation key: hash of the known-IRI set

`known_iris_hash(known_iris)` = SHA-256 over the sorted known-IRI set (join
with `\n`). This set is precisely what seeds the matcher and validates every
link, so:

- a **new salt/concept loaded** → set changes → hash changes → cache
  discarded → previously-`novel` surfaces get another chance to link, and any
  now-invalid link is re-derived;
- an **unchanged graph** → hash matches → full reuse → zero model calls.

Keying on the ontology `owl:versionInfo` was rejected: loading new NIST salts
does not bump the ontology version, so it would fail to invalidate exactly
the case that matters. The known-IRI hash tracks the linkable set directly.

## D3 — Lifecycle in `cli._cmd_link` (client present only)

1. Compute `iris_hash` from `known_iris`.
2. Unless `config.disambig_cache_refresh`, `load_cache(path, iris_hash)` →
   returns the stored `entries` iff the file exists, parses, and its
   `known_iris_hash` equals `iris_hash`; otherwise `{}`. Any IO/JSON error or
   hash mismatch yields `{}` (never fatal — the cache is an optimization).
3. Seed `_disambig_cache` with the loaded entries; the pre-warm collector
   already skips surfaces `in _disambig_cache`, so seeded surfaces never reach
   DeepSeek.
4. After the report loop, `save_cache(path, iris_hash, _disambig_cache)`
   writes the merged map (seeded + newly resolved) with the current hash.

The disambiguation layer's validation is unchanged: a seeded `linked` entry
still carries an IRI that was in the known set when written, and because the
cache is only reused when the hash matches, that IRI is still valid. (A
belt-and-suspenders re-validation of seeded links against the live
`known_iris` is cheap and included, so a hand-edited cache cannot inject an
unknown IRI.)

## D4 — Config

- `disambig_cache_path` — property: `config.corpus_dir / "disambiguation-cache.json"`.
- `disambig_cache_refresh: bool = False` — env `MSR_DISAMBIG_REFRESH`
  (truthy = `1`/`true`/`yes`, case-insensitive). Forwarded through the Compose
  extraction env so `MSR_DISAMBIG_REFRESH=1 make link` forces a refresh.

## D5 — Testing

- `disambig_cache.py`: hash is stable and order-independent; save→load
  round-trips entries; load returns `{}` on missing file, corrupt JSON, and
  hash mismatch.
- `cli._cmd_link`: after a first run writes the cache, a second run with the
  same known-IRI set and a counting fake makes **zero** `complete` calls;
  `MSR_DISAMBIG_REFRESH` re-resolves despite a present cache; a changed
  known-IRI set is treated as a cache miss (re-resolves) and rewrites the
  file with the new hash.
