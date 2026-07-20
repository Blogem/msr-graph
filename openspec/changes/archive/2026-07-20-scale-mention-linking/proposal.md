# Scale mention linking: batched writes + concurrent disambiguation

## Why

Running `make link` on the full corpus surfaced two problems that make the
linking phase unusable on real, OCR-heavy documents:

1. **The mention writer does not batch its graph write.**
   `mentions.write_mentions` builds a single `INSERT DATA` containing *every*
   linked mention for a report and POSTs it in one request. On
   `NSRDS-NBS-61-p4` (3,821 linked mentions) that body exceeds GraphDB's
   Tomcat `maxPostSize`, so the endpoint rejects it with a generic HTTP
   `500` ("the size of the posted data was too big"), and the extraction
   pipeline dies with an unhandled `httpx.HTTPStatusError`. Report
   `ORNL-TM-2316` (280 mentions) succeeds only because its body is small.
   The linking phase therefore cannot complete on the real corpus at all.

2. **Layer-5 disambiguation runs strictly sequentially.**
   Each unresolved formula-shaped span is sent to DeepSeek one at a time and
   blocks on the network round-trip. Even with the per-surface cache
   (`cache-disambiguation-by-surface`), the first pass over the distinct
   unresolved surfaces is serial, so a corpus with hundreds of distinct
   unresolved surfaces takes many minutes. Measurement shows the linker's
   own scan of a 33k-segment document is ~2s, so the wall-clock is dominated
   entirely by sequential model latency, not local work.

## What Changes

- **Batch the mention writes.** `write_mentions` splits the report's
  ordered mentions into bounded batches and sends one `INSERT DATA` per
  batch to `urn:msr:data`, and likewise one per-run generation-edge
  `INSERT DATA` per batch to `urn:msr:provenance`. Batch size is a
  configurable `Config` field (`MSR_MENTION_WRITE_BATCH_SIZE`, default 500).
  Every batch is still additive set-semantics, so idempotency and
  determinism are unchanged; the only difference is the number of POSTs.
- **Resolve layer-5 disambiguation concurrently.** `cli._cmd_link` gains a
  per-report *pre-warm* pass: it collects the distinct unresolved layer-5
  surfaces (a cheap re-scan, no model calls), resolves them concurrently
  with a bounded thread pool (`MSR_DISAMBIG_CONCURRENCY`, default 8) into the
  per-surface cache, then runs the real link pass, which now hits a warm
  cache and issues no further model calls. `linker.py` and
  `disambiguation.py` are unchanged — the concurrency lives entirely in the
  CLI orchestration behind the existing injected-disambiguator seam.

## Non-goals

- Translating GraphDB SHACL/other `500`s into a typed error on the Python
  side (the Go loader does this; the Python writer still just raises). The
  batching fix removes the `maxPostSize` `500`; broader Python-side error
  typing is a separate follow-up.
- Changing which spans reach layer 5, the disambiguation prompt, or the
  known-IRI validation.

## Impact

- Affected specs: `mention-graph-writing` (batched write), `llm-disambiguation`
  (concurrent resolution).
- Affected code: `extraction/src/msr_extraction/mentions.py`,
  `extraction/src/msr_extraction/cli.py`,
  `extraction/src/msr_extraction/config.py`.
- Affected tests: `extraction/tests/test_mentions.py`,
  `extraction/tests/test_cli_link.py`.
- No change to graph content, mention schema, or SHACL behavior.
