# Design — Scale mention linking

## D1 — Batched mention writes (`mentions.write_mentions`)

Split the report's `ordered` mentions into fixed-size batches and send one
`INSERT DATA` per batch:

- All `urn:msr:data` batches first (mention triples), then all
  `urn:msr:provenance` batches (per-run generation edges). Keeping data
  batches before provenance batches preserves the existing observable order
  (`calls[0]` is a `urn:msr:data` write, the trailing calls are
  `urn:msr:provenance`) so the single-mention tests that assert
  `calls[0]`/`calls[1]` still hold.
- Batch size is `Config.mention_write_batch_size` (env
  `MSR_MENTION_WRITE_BATCH_SIZE`, default **500**). Each mention block is a
  few hundred bytes, so 500 keeps a POST body well under ~300 KB — an order
  of magnitude below the Tomcat `maxPostSize` that 3,821 mentions
  (~1.9 MB in one POST) exceeded. `write_mentions` accepts a `batch_size`
  keyword so tests can force small batches; `_cmd_link` passes
  `config.mention_write_batch_size`.
- Additivity/idempotency unchanged: every batch is `INSERT DATA` with
  deterministic IRIs and no blank nodes, so the union of batches is
  identical to the old single write; re-running is still a set-semantics
  no-op. `write_mentions([])` still sends zero updates.

Rejected alternative: raising GraphDB's `maxPostSize` in the connector
config. That is a server-side band-aid that breaks again at a larger corpus
and is not portable across deployments; app-side chunking is the robust fix.

## D2 — Concurrent layer-5 disambiguation via a pre-warm pass

The bottleneck is sequential model latency. The injected-disambiguator seam
(`linker` calls `disambiguator(surface, sentence)` synchronously, span by
span) is kept intact; concurrency is added in `cli._cmd_link` as a per-report
pre-warm:

1. **Collect** — run `linker.link_report` once with a *collector*
   disambiguator that records each distinct not-yet-cached surface (with the
   first sentence seen) into a `pending` map and returns `("novel", None)` so
   linking proceeds. The records from this pass are discarded. This re-scan
   is cheap: measured ~2s for the 33k-segment document, versus minutes of
   serial model latency.
2. **Resolve concurrently** — submit each `pending` surface to a
   `ThreadPoolExecutor(max_workers=Config.disambig_concurrency)` (env
   `MSR_DISAMBIG_CONCURRENCY`, default **8**), calling the same
   `disambiguate(...)` unit, and store each `(status, target_iri)` into the
   shared per-run cache. Threads are correct here because the DeepSeek/openai
   client is blocking I/O (releases the GIL); `disambiguate` never raises.
3. **Real pass** — run `link_report` again with the caching disambiguator.
   Every layer-5 surface is now in the cache, so no model call is issued and
   the produced records/mentions are exactly what a warm sequential run
   would produce.

Determinism holds because *which* spans reach layer 5 depends only on layers
2-4 (cache-independent): both passes see the identical set of layer-5
surfaces, and both `linked` and `novel` outcomes produce a record and occupy
the span, so the collector's uniform `novel` return does not change span
occupancy relative to the real pass.

Cross-report sharing: the cache is closure-scoped to the whole `_cmd_link`
run, so a surface resolved while pre-warming report N is skipped by report
N+1's collector (`surface in _cache`) and reused directly.

The surface-only cache key and its known-IRI safety net are unchanged from
`cache-disambiguation-by-surface` (now archived); this change only changes
*when/how* the first resolution of each distinct surface happens (concurrent
pre-warm instead of lazy first-touch).

Rejected alternative: refactoring `link_segment`/`link_report` to collect and
resolve layer-5 candidates in a single scan. It is faster in theory (one
scan) but modifies the carefully-layered linker and its direct-call test
surface; given the scan is ~2s, the two-pass CLI-only approach is far lower
risk for negligible extra cost.

## D5 — Tunable, pooled, retrying concurrency

Three refinements make the concurrency both reachable and safe to raise:

- **Plumbing.** `MSR_DISAMBIG_CONCURRENCY` and `MSR_MENTION_WRITE_BATCH_SIZE`
  are forwarded through the Compose `extraction` service env (they were not
  before, so `make link` was pinned to the code default). Default concurrency
  is raised to 24.
- **Pooled client.** `FlashClient` builds its `openai` client once (lazily,
  under a lock) and reuses it across all concurrent calls. `openai.OpenAI` is
  thread-safe and pools HTTP connections, so N concurrent disambiguations
  share one bounded connection pool instead of each doing a fresh client
  construction + TLS handshake — which is what makes raising concurrency
  actually pay off rather than cause a connection storm.
- **Retry over silent-novel.** `disambiguate` swallows any exception to
  `("novel", None)`. Under higher concurrency a transient 429/5xx/timeout
  would therefore silently drop a real link. Setting the openai client's
  `max_retries` (default 5) makes the SDK retry those transient classes with
  exponential backoff, honoring `Retry-After`; only an exhausted budget falls
  through to novel. This trades a little latency under load for recall, not
  the other way around.

A reasonable ceiling on this workload is ~16–32; 24 is the default. Going
much higher yields diminishing returns (a bounded number of distinct surfaces
per run) and leans harder on the retry path.

## D3 — Configuration

Two new `Config` fields, both read in `from_env` with the documented
defaults, both int:

- `mention_write_batch_size` (`MSR_MENTION_WRITE_BATCH_SIZE`, default 500)
- `disambig_concurrency` (`MSR_DISAMBIG_CONCURRENCY`, default 8)

## D4 — Testing

- **Batching:** feed `write_mentions` more mentions than a small
  `batch_size` and assert (a) the number of `urn:msr:data` updates equals
  `ceil(n/batch_size)`, (b) every mention IRI appears in exactly one data
  update, (c) the provenance edges are likewise fully covered, (d) empty
  input still sends zero updates, (e) existing single-mention call-shape
  tests still pass.
- **Concurrency/pre-warm:** with a counting fake client, a segment repeating
  one unresolved surface plus a distinct one still yields exactly one model
  call per distinct surface (dedup holds under the two-pass flow), and a fake
  that returns a *link* for a surface produces a `linked` mention record in
  the output (pre-warm result flows into the real pass). A fake that records
  the max number of concurrently in-flight calls confirms the pool runs more
  than one at a time when several distinct surfaces are pending.
