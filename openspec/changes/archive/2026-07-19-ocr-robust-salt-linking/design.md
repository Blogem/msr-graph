# Design: ocr-robust-salt-linking

## Context

Chunk 6 (`ner-entity-linking`) shipped a layered, precision-biased linker (exact → formula normalizer → bounded fuzzy → Flash) and a formula normalizer that maps salt mentions to the loader-minted `msrd:salt-{formula}-{composition}` IRIs. Its automated precision gate (≥ 0.90) passed on a **synthetic** gold fixture. But the manual acceptance run (chunk-6 task 11.1) over the **real** `data/corpus/ORNL-TM-2316/normalized.txt` produced `layer3=0`: not one mention linked to any of the 185 loaded `MoltenSalt` individuals.

The cause is corpus OCR that the synthetic fixture never modeled:

- Subscript digits are OCR'd as commas/periods: `BeF2`→`BeF,`, `ThF4`→`ThF,`, `UF4`→`UF,` — e.g. `"LiF-BeF,-ThF,-UF, (65-28-5-1-1 mole %)"`, `"LiF-BeF, (66-34 mole %)"`.
- Compositions are written `mol %` (528×, spaced) or `mole %` (160×), overwhelmingly rather than the clean `mol%` (19×) — corpus-wide counts.
- A no-DeepSeek `link` run over all 11 curated documents confirmed the failure is **universal**: `layer3=0` in every document (not an ORNL-TM-2316 quirk). The salt forms span binary through quaternary and multiple compounds (`LiF-BeF,`, `LiF-BeF,-ThF,`, `LiF-UF,`, `NaF-ZrF,`, plus `BeF,`/`UF,`/`ThF,`/`ZrF,`/`PuF,`/`KF,`/`NaF,` comma-subscript compounds), so both the reconstruction and the test fixtures must be catalog-anchored and multi-document, not single-example.

So exact-match against `voc:flibe`'s `"LiF-BeF2"` altLabel fails (`"LiF-BeF,"` ≠ `"LiF-BeF2"`), the formula normalizer fails (its candidate regex/parse want real subscript digits and a `mol%` tail), and the bounded fuzzy layer is disqualified by `fuzzy_min_token_length = 4` (the tokens `LiF`/`BeF` are 3 chars). Concepts/compounds still link (`LiF`→lithium-fluorides, `viscosity`, `MSRE`), and Flash even recovered a couple of garbled forms — but the salt catalog is unused.

This change makes chunk-6 matching robust to those OCR forms **without** loosening precision, so the M3 anchor (`LiF-BeF2` → the loaded salt individual) actually resolves on the real corpus. Bound by the same cross-cutting contracts as chunk 6 (`docs/ARCHITECTURE.md` → Matching & OCR robustness; the shared `testdata/salt-canonicalization.json` drift guard, unchanged).

## Goals / Non-Goals

**Goals:**

- On the real ORNL-TM-2316 OCR, a composed salt mention (`"LiF-BeF, (66-34 mole %)"`) resolves to the loader-minted salt individual (`msrd:salt-BeF2-LiF-34.0-66.0`), i.e. `layer3 > 0`.
- OCR subscript forms of the known catalog compounds/salts (`BeF,`→BeF2, `ThF,`→ThF4, `UF,`→UF4, `ZrF,`→ZrF4) are matchable — for concept/compound links (layer 2) and as inputs the formula normalizer can canonicalize (layer 3).
- Composition tails accept `mole %` / `mol %` / `mol.%` as well as `mol%`.
- The bounded fuzzy fallback can consider short chemistry tokens without losing precision.
- The precision harness and matcher/linker/formula tests exercise **real-OCR-derived** salt forms, so the suite can no longer be green while the anchor fails.

**Non-Goals:**

- **No chunk-5 OCR re-normalization** — `normalized.txt`/`segments.jsonl` are consumed unchanged. Rewriting `"BeF,"`→`"BeF2"` globally in the corpus is rejected (D1).
- **No change to `testdata/salt-canonicalization.json`** — the Go/Python drift guard stays as-is; canonical forms and IRIs are unchanged, only the *surface parsing* becomes OCR-tolerant.
- **No new graph/schema/loader changes, no new runtime dependencies.**
- **No general OCR error-correction** — only the specific, catalog-anchored subscript-comma and `mole %` artifacts observed in the corpus.
- **No relation/measurement extraction** (still chunk 7); this change only makes salt *mentions* link.

## Decisions

### D1 — Restore subscripts at match time against the known catalog, not by rewriting the OCR

A comma is not always a dropped subscript (`"LiF, BeF, and ThF, will be..."` has real commas). Globally rewriting `"BeF,"`→`"BeF2"` in chunk-5 normalization would be ambiguous and could corrupt genuine prose. Instead, reconstruction happens **at match time and only against the graph's known catalog**: an OCR token is only "restored" to a compound if its comma/period-stripped root uniquely maps to a compound the catalog actually loaded, and a reconstructed salt only links if its minted IRI is already in the run's known-IRI set. This makes an over-eager restoration cost nothing — it can only ever match an entity that exists, never invent one.

- _Alternative — chunk-5 subscript normalization:_ rejected; lossy, ambiguous (comma vs. subscript), and it would move salt-matching knowledge into the OCR pre-pass, breaking the layer-1/layer-2+ separation.

### D2 — OCR-subscript variant generation from catalog formulas (seeds layer 2)

Pattern-variant generation gains OCR-subscript variants derived from the graph's known compound and `MoltenSalt` formula tokens: for a formula token ending in a subscript digit, emit the comma and period forms (`BeF2`→`BeF,`,`BeF.`; `ThF4`→`ThF,`,`ThF.`), and for multi-component salt formula labels emit the per-component comma/period forms (`LiF-BeF2`→`LiF-BeF,`). Generation stays a pure, deterministic function of the label (as today), fed into the spaCy `EntityRuler`. This gets compound/concept OCR forms (`BeF,`→beryllium-fluorides) matching at layer 2 and provides the surface forms the normalizer will canonicalize.

- _Alternative — a blanket "any trailing punctuation = subscript" tokenizer rule:_ rejected; not catalog-anchored, so it would fire on arbitrary punctuation. Deriving variants from known formulas keeps it bounded and testable (label → expected variants).

### D3 — OCR-tolerant formula normalization (layer 3)

`formula.normalize_salt_span` and the linker's salt-candidate detection are extended to:

- Treat a trailing comma/period on an element-fluoride token as a subscript placeholder, and resolve the token against the catalog compound set (`{LiF, BeF2, ThF4, UF4, ZrF4, KF, NaF, ...}`) — `"BeF,"`→`BeF2` when `BeF2` is a known compound; leave it unresolved otherwise.
- Accept `mole %`, `mol %`, `mol.%` (optional `e`, optional space/period before `%`) in the inline-composition tail, in addition to `mol%`.
- Canonicalize the reconstructed `(components, composition)` with the **unchanged** rule (byte-sort, lockstep reorder, one-decimal), producing the same canonical string + `msrd:salt-…` IRI as the clean form. `"LiF-BeF, (66-34 mole %)"` → `BeF2-LiF | 34.0-66.0` → `msrd:salt-BeF2-LiF-34.0-66.0`.

The shared `testdata/salt-canonicalization.json` continues to pass unchanged (it tests canonicalization of already-clean tokens; OCR parsing is an additional front-end).

### D4 — Salt individuals link via the normalizer, not the EntityRuler

Salt `rdfs:label`s are `"BeF2-LiF (34.0-66.0 mol%)"` — that string never appears in prose. So the salt *individual* link comes from D3 (normalizer reconstructing `"LiF-BeF, (66-34 mole %)"` → the IRI), while the OCR-variant EntityRuler seeding (D2) primarily serves concept/compound matches and bare-formula-to-concept (`voc:flibe`). This preserves chunk-6's precedence rule: a successful composed-salt (layer 3) supersedes an overlapping concept exact-match (layer 2).

### D5 — Fuzzy fallback eligible for short chemistry tokens

`fuzzy_min_token_length` currently disqualifies 3-char formula tokens (`LiF`,`BeF`,`KF`). Lower the effective minimum for the fuzzy layer (config knob, pinned by tests) so short chemistry tokens are eligible, keeping the high similarity threshold and existing-label-only rule so precision holds. This is the safety net for OCR forms D2/D3 don't structurally reconstruct.

- _Alternative — leave min-token-length, rely only on the normalizer:_ workable for the anchor, but the fuzzy net is what catches long-tail OCR mangling (`"LiF- Bn"` etc.), so keeping it available for short tokens is worth the tuned knob.

### D6 — Real-OCR test fixtures gate the change

Add fixtures derived verbatim from `data/corpus/ORNL-TM-2316/normalized.txt` salt forms (`"LiF-BeF, (66-34 mole %)"`, ternary/quaternary `"LiF-BeF,-ThF,-UF, (…mole %)"`, comma-subscript compounds) to the matcher/linker tests, the formula tests, and the **precision harness gold fixture**. The harness must include real-OCR composed-salt cases expecting the loaded salt IRIs, so it cannot be green while `layer3=0`. Re-run chunk-6 task 11.1 as the final gate.

## Risks / Trade-offs

- **Comma-as-subscript over-restoration corrupts a real comma** → restoration is catalog-anchored (D1): only tokens whose stripped root is a known compound are restored, and a salt links only if its minted IRI is in `known_iris`; a false restoration can't create a bad link, only (rarely) a correct one.
- **Broadening the composition tail to `mole %` captures stray numbers** → the tail is only parsed inside a formula-candidate span (a multi-component formula precedes it), not free-standing numbers.
- **Lowering the fuzzy min-token-length increases false links** → keep the high similarity threshold and existing-label-only rule; validate against the real-OCR precision harness (the ≥ 0.90 gate now includes real-OCR salt cases).
- **Divergence from the Go canonicalizer** → none: canonicalization is unchanged; only surface parsing is added ahead of it, and the shared fixture still passes.
- **Ternary/quaternary reconstruction** (`LiF-BeF,-ThF,-UF,`) is harder than binary → the catalog holds those individuals; tests cover ≥ 2 components, and any component that can't be catalog-resolved leaves the whole span unresolved (→ novel), never a partial/wrong link.

## Migration Plan

Additive chunk-6 code + tests on top of `ner-entity-linking`. Bootstrap/order unchanged (`make up → load-seed → load-nist → ingest → link`). After implementation: rebuild the extraction image, re-run `make link` over ORNL-TM-2316, confirm `layer3 > 0` and the anchor resolves to `msrd:salt-BeF2-LiF-34.0-66.0`, then re-run chunk-6 task 11.1. Sequencing: `ner-entity-linking` (which defines the capabilities this modifies) archives before or together with this change. Rollback: revert the chunk-6 matching commits; no data migration (mentions are re-derivable per run).

## Open Questions

- The exact fuzzy min-token value (D5) — tune against the real-OCR sample; start conservative.
- Whether to also handle subscripts dropped entirely with no comma (`"BeF"` with nothing) — out of scope unless the corpus shows it materially; the observed artifact is comma/period.
- Whether a few residual OCR salt forms are better left to the Flash layer than structurally reconstructed — measured against the precision harness at implementation.
