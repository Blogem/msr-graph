# Tasks — Scale mention linking

## 1. Configuration

- [x] 1.1 Add `Config.mention_write_batch_size: int = 500` and
      `Config.disambig_concurrency: int = 8`; read both in `from_env`
      (`MSR_MENTION_WRITE_BATCH_SIZE`, `MSR_DISAMBIG_CONCURRENCY`).

## 2. Batched mention writes

- [x] 2.1 In `mentions.write_mentions`, split the ordered mentions into
      batches of `batch_size` (new keyword arg, default a module constant):
      send one `urn:msr:data` `INSERT DATA` per batch, then one
      `urn:msr:provenance` `INSERT DATA` per batch. Empty input still sends
      nothing. Reject `batch_size < 1`.
- [x] 2.2 In `cli._cmd_link`, pass `config.mention_write_batch_size` to
      `write_mentions`.

## 3. Concurrent layer-5 disambiguation (pre-warm)

- [x] 3.1 In `cli._cmd_link`, add a per-report pre-warm: collect distinct
      not-yet-cached layer-5 surfaces via a collector disambiguator, resolve
      them concurrently with a `ThreadPoolExecutor(max_workers=
      config.disambig_concurrency)` into the shared per-run cache, then run
      the real link pass against the warm cache.
- [x] 3.2 Keep `linker.py` and `disambiguation.py` unchanged; the caching
      disambiguator keeps the surface-only key and known-IRI safety net.
- [x] 3.3 Log per-report pre-warm stats (distinct surfaces resolved,
      concurrency used).

## 4. Tests

- [x] 4.1 `test_mentions.py`: batching splits into `ceil(n/batch_size)`
      data updates; every mention IRI appears in exactly one data update and
      one provenance update; empty input sends zero updates; `batch_size < 1`
      raises. Existing single-mention call-shape tests still pass.
- [x] 4.2 `test_cli_link.py`: dedup still holds under the two-pass flow (one
      model call per distinct unresolved surface); a fake returning a link
      yields a `linked` mention record (pre-warm result flows through); a
      fake tracking in-flight concurrency confirms >1 call runs at once.

## 5. Validation

- [x] 5.1 `cd extraction && uv run --extra test python -m pytest` green.
- [x] 5.2 `openspec validate scale-mention-linking --strict` passes.
- [ ] 5.3 Rebuild the extraction image and re-run `make link`; confirm it
      completes over the full corpus (including `NSRDS-NBS-61-p4`) with no
      `500`, and visibly faster (manual walkthrough step).
