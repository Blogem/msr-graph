# Tasks — Persist layer-5 disambiguation across runs

## 1. Cache module

- [x] 1.1 New `msr_extraction/disambig_cache.py`: `known_iris_hash(known_iris)`
      (SHA-256 over sorted IRIs), `load_cache(path, expected_hash)` (returns
      `{surface: (status, target_iri)}` iff file present/parseable/hash
      matches, else `{}` — never raises), `save_cache(path, hash, entries)`
      (writes the JSON shape from design D1, creating parent dirs).

## 2. Config

- [x] 2.1 Add `Config.disambig_cache_path` property (corpus_dir /
      `disambiguation-cache.json`) and `Config.disambig_cache_refresh: bool`
      (env `MSR_DISAMBIG_REFRESH`, truthy parse).

## 3. Wire into the link command

- [x] 3.1 In `cli._cmd_link` (client present): compute the known-IRI hash,
      load+seed the cache unless refresh, and after the report loop write the
      merged cache back. Re-validate seeded `linked` entries against the live
      `known_iris`. Log seeded/written counts.
- [x] 3.2 Forward `MSR_DISAMBIG_REFRESH` through the Compose extraction env.

## 4. Tests

- [x] 4.1 `test_disambig_cache.py`: hash stable & order-independent; save→load
      round-trip; `{}` on missing file, corrupt JSON, and hash mismatch.
- [x] 4.2 `test_cli_link.py`: first run writes the cache; a second run with the
      same known-IRI set + counting fake makes **zero** model calls; refresh
      forces re-resolve; a changed known-IRI set is a cache miss and rewrites
      with the new hash.

## 5. Validation

- [x] 5.1 `cd extraction && uv run --extra test python -m pytest` green.
- [x] 5.2 `openspec validate persist-disambiguation-cache --strict` passes.
- [x] 5.3 Rebuild the extraction image; run `make link` twice; confirm the
      second run makes no DeepSeek calls and still writes the same mentions
      (manual walkthrough step).
