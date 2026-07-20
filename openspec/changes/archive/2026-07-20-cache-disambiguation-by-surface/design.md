# Design — Cache layer-5 disambiguation by surface form

## D1 — Cache location: the CLI disambiguator closure

The cache lives in `cli._cmd_link`, wrapping the `disambiguator` closure that
is already constructed once per run and threaded into every `link_report`
call. This is the narrowest correct seam:

- `linker.link_segment` stays a pure function of its inputs — it just calls
  the injected `disambiguator`; it does not learn about caching.
- `disambiguation.disambiguate` stays a single-call, side-effect-free unit,
  still stubbed directly in `test_disambiguation.py`.
- The cache scope is exactly one `link` invocation, because the closure (and
  its captured dict) is created inside `_cmd_link` and discarded when it
  returns.

Rejected alternative: an `@functools.lru_cache` on `disambiguate` itself.
`disambiguate` takes unhashable arguments (`known_iris: set`, the `client`),
and caching at that layer would leak state across runs within a process
(matters under test). The closure-local dict avoids both.

## D2 — Cache key: surface form only

Key = the span's `surface` string. Value = the `(status, target_iri)` tuple
the closure already returns.

The disambiguator signature is `(surface, sentence) -> (status, target_iri)`,
and the model prompt includes the sentence. Keying on surface alone
therefore narrows behavior: only the first occurrence's sentence reaches the
model. This is acceptable **only because** layer 5 sees exclusively
formula-shaped candidate spans (`linker._find_formula_candidates`'s regex),
for which composition is identity and sentence context is not the
disambiguator. The alternative key `(surface, sentence)` is provably
output-identical to today but only dedups within a single segment, which
misses the dominant cost (the same formula recurring across many
segments/reports) — so it is rejected in favor of the corpus-wide win.

Safety net unchanged: `disambiguate` still validates every returned link
against `known_iris`, so a cached outcome can never be a link to an unloaded
IRI. A `("novel", None)` outcome is cached too — a surface that could not be
resolved once will not be re-sent, which is the intended behavior.

## D3 — No persistence, no config

The cache is a plain in-memory `dict[str, tuple[str, str | None]]`. It is not
written to disk and not shared across runs. Re-running `make link` starts
with an empty cache, so a graph that gained new entities between runs is
re-disambiguated from scratch — no stale-cache invalidation problem to
manage.

## D4 — Testing

`test_cli_link.py` already drives `cli.main(["link"])` hermetically with a
fake Flash client. Extend it (or add a sibling test) with a fake client that
counts `complete` calls, feed a synthetic segment containing the **same
unresolved formula surface twice**, and assert the fake was called once for
that surface — proving the second occurrence hit the cache. A second surface
asserts distinct surfaces still each call once.
