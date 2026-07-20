# Cache layer-5 disambiguation by surface form

## Why

The linker's layer-5 Flash disambiguation (`msr_extraction.disambiguation`)
is correctly gated — a span only reaches DeepSeek after expanded exact
matching, the formula normalizer, and the bounded fuzzy fallback all fail on
it (`linker.link_segment`). But the disambiguator callable the CLI wires up
(`cli._cmd_link`) has **no result memoization**: every unresolved
formula-shaped candidate span issues its own model call, even when the same
surface form has already been resolved earlier in the run.

On the real ORNL OCR corpus a large fraction of formula-shaped spans do not
resolve locally, and the same surface (e.g. an OCR-mangled `"BeF,"`) recurs
across many segments and reports. Each recurrence is currently a fresh,
redundant DeepSeek call that recomputes an answer already known — the same
`(status, target_iri)` every time, since within a run the known-IRI set and
KG-schema prompt prefix are fixed. This makes the `link` step slow and
needlessly chatty against the model API.

## What Changes

- Memoize layer-5 disambiguation outcomes keyed on the **mention surface
  form**, in memory, for the duration of a single `link` run. A repeated
  surface reuses the first outcome instead of calling the model again.
- The cache lives in `cli._cmd_link`'s disambiguator closure (shared across
  every report processed in the run); `linker` and `disambiguation` are
  unchanged.
- No persistence across runs and no new configuration.

## Semantic narrowing (deliberate)

Keying on surface alone means only the **first** occurrence's sentence
context reaches the model; later identical surfaces reuse that outcome. This
is safe for this layer because layer-5 candidates are restricted to
formula-shaped spans (`linker._find_formula_candidates`), where the chemical
composition — not the surrounding sentence — determines identity. Every
reused outcome is still subject to the unchanged known-IRI validation in
`disambiguation.disambiguate`, so the cache can never introduce a link to an
IRI the graph has not loaded.

## Impact

- Affected spec: `llm-disambiguation` (adds a memoization requirement).
- Affected code: `extraction/src/msr_extraction/cli.py` (`_cmd_link`).
- Affected tests: `extraction/tests/test_cli_link.py` (dedup assertion).
- No change to the graph output, the mention schema, or SHACL behavior.
