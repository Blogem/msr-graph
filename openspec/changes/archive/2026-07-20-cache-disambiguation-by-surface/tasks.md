# Tasks — Cache layer-5 disambiguation by surface form

## 1. Implementation

- [x] 1.1 In `cli._cmd_link`, back the `disambiguator` closure with an
      in-memory `dict[str, tuple[str, str | None]]` keyed on `surface`:
      return the cached outcome when present, otherwise call
      `disambiguate(...)`, store, and return. Cache is created per
      `_cmd_link` invocation (D1/D2/D3).
- [x] 1.2 Confirm the closure remains the sole caller of `disambiguate` and
      that `linker`/`disambiguation` are unchanged.

## 2. Tests

- [x] 2.1 In `extraction/tests/test_cli_link.py`, add a fake Flash client
      that records every `complete(...)` call. Drive `cli.main(["link"])`
      over a synthetic segment whose text contains the **same** unresolved
      formula surface twice; assert the fake recorded exactly **one** call
      for that surface (second occurrence served from cache).
- [x] 2.2 In the same test, include a **second, distinct** unresolved
      surface and assert it produced its own single call (distinct surfaces
      each call once — the cache does not collapse different surfaces).
- [x] 2.3 Assert the produced mentions/graph output is unchanged by caching
      (both occurrences still resolve to the same outcome), so memoization
      is transparent to downstream writing.

## 3. Validation

- [x] 3.1 `cd extraction && uv run --extra test python -m pytest` is green.
- [x] 3.2 `openspec validate cache-disambiguation-by-surface --strict` passes.
- [ ] 3.3 Rebuild the extraction image and re-run `make link`; confirm the
      DeepSeek call volume drops and mentions still land (manual walkthrough
      step).
