# Persist layer-5 disambiguation across runs

## Why

`make link`'s cost is dominated by the layer-5 DeepSeek calls. Today the
per-surface disambiguation cache is in-memory only (built in `cli._cmd_link`,
discarded when the run ends), so every run re-asks the model about the same
surfaces — even when nothing changed. Re-running the pipeline (a common
loop while iterating on other stages) pays the full LLM cost again.

The layer-5 outcomes are pure `surface → (status, target_iri)` mappings, so
they can be persisted and reused. The subtlety is that most outcomes are
`novel` ("the model couldn't link this"), and those must be cached too or
there is no saving — but a `novel` (or a `linked`) decision can go stale if
the set of linkable entities later changes (e.g. new salts loaded). The
cache therefore has to invalidate exactly when the linkable-entity set
changes.

## What Changes

- Persist the run's layer-5 disambiguation outcomes to a JSON file under the
  corpus dir (`data/corpus/disambiguation-cache.json`), tagged with a hash
  of the run's **known-IRI set** (the set that seeds the matcher and
  validates links).
- At the start of a `link` run, load the cache **only if** its stored hash
  matches the current known-IRI set; otherwise start empty (auto-invalidate).
  The concurrent pre-warm then seeds from it, so only surfaces **not** already
  cached are sent to DeepSeek. On an unchanged graph + corpus, the second run
  makes **zero** model calls.
- At the end of the run, write the merged cache back (loaded entries plus any
  newly-resolved surfaces).
- A refresh switch (`MSR_DISAMBIG_REFRESH=1`) ignores any existing cache on
  load and forces a full re-resolve (the fresh results are still written
  back).

## Non-goals

- Persisting anything about layers 2-4 (they are deterministic and cheap).
- Caching across *different* known-IRI sets (the hash intentionally
  invalidates then).
- Changing the surface-only cache key, the concurrency, or the batched
  writes (all unchanged from `scale-mention-linking`).

## Impact

- Affected spec: `llm-disambiguation` (adds a cross-run persistence
  requirement).
- Affected code: new `extraction/src/msr_extraction/disambig_cache.py`;
  `cli._cmd_link` (load/seed/save); `config.py` (cache path + refresh flag).
- Affected tests: new `test_disambig_cache.py`; `test_cli_link.py`
  (second-run-zero-calls, refresh, invalidation).
- Cache file lives under the gitignored `data/corpus/`; it is never
  committed and the pipeline works with or without it present.
