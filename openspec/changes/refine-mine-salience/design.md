# Design: refine-mine-salience

## Context

`mine-ontology-candidates` (chunk 8) is merged. Its `novelty-detection` capability enumerates
candidate terms from a lexical n-gram pass over the curated documents plus the chunk-6
salt-formula misses, excludes already-known terms, scores each by **document frequency** over the
full 637-document OCR corpus, and keeps everything at/above a fixed threshold
(`config.salience_threshold`, default 50). A recent perf fix replaced the O(terms × docs)
substring scan with an inverted n-gram-set intersection (≈3.7 h → 7 s), so scanning is no longer
the bottleneck.

The first real run then exposed a **selection** problem the fixture-scale tests could not:

- The lexical pass emits **252,085** candidate n-grams; **8,861** clear `df ≥ 50`.
- Document frequency does not rank novelty. Measured df on the real corpus:
  `molten salt` 423 · `graphite` 379 · `high temperature` 324 · `heat transfer` 318 ·
  `fuel salt` 308 · `solubility` **271**. The genuine novel targets are *less* frequent than
  common/already-modeled phrases, so raising the threshold drops `solubility` before the noise.
- The exclusion set (315 entries) matches only exact normalized ontology labels: it catches
  `moltensalt` and `fuel salt` but misses the `molten salt` space variant and every generic
  non-ontology term (`heat transfer`, `temperature`, `reactor`).

Net effect: a full `make mine` would triage ~8,861 candidates (thousands of Flash calls) and emit
thousands of proposals — unreviewable, and not surfacing the demo targets as anything special.
This change fixes candidate *selection* only; triage, proposal emission, instance auto-accept, and
provenance are unchanged and keep consuming the same `Candidate` list — now bounded and ranked.

## Goals / Non-Goals

**Goals:**

- Rank candidates by a **keyness** score that surfaces domain-novel terms above frequent
  generic/known ones, keeping `solubility` and `graphite` while demoting `molten salt` /
  `heat transfer` / `high temperature`.
- Bound the triaged set to a configurable **top-N** so triage fires a finite number of Flash
  calls and the reviewer gets a prioritized, finite queue.
- Harden exclusion so already-modeled terms (any spelling, incl. space variants) never reach
  scoring.
- Preserve determinism, idempotence, hermetic testability, and zero new third-party packages.

**Non-Goals:**

- No change to triage, proposal emission, instance auto-accept, provenance, or the
  `msr:ChangeProposal` staging contract (chunk-9's input shape is untouched).
- No statistical NLP / POS tagging / re-introduction of a spaCy model (chunk 6 dropped it) — the
  pass stays lexical.
- No learned/embedding-based novelty model — a transparent, deterministic keyness score is the
  POC scope; the design keeps the metric explainable to a reviewer.
- No dereferencing external vocabularies — the frequency baseline is vendored, like
  `qudt-units.json`.

## Decisions

### D1 — Keyness (weirdness ratio) replaces document frequency as the ranking key

Score each candidate by how much more prominent it is in the MSR corpus than in general English,
rather than by raw corpus frequency. Concretely, for a candidate term the score combines its
corpus document frequency with the **rarity of its constituent tokens in a vendored
general-English frequency baseline** — a term whose tokens are rare in general English but recur
across the corpus scores high (`solubility`, `graphite`, `fluoride`), while a term of common
English tokens scores low regardless of corpus frequency (`high temperature`, `heat transfer`).
Document frequency stays as a **floor/evidence input** (a candidate must still appear in enough
corpus docs to be worth proposing) but is no longer the sort key.

- _Alternative — within-corpus TF-IDF/IDF only:_ rejected. IDF downweights ubiquitous terms but
  `solubility` (43% of docs) still sits mid-pack against many domain phrases; without an external
  baseline it cannot tell "domain-rare-but-real" from "common English."
- _Alternative — curated-vs-corpus enrichment:_ rejected as the primary signal (it overfits to
  the hand-picked curated set), though it remains a reasonable future secondary factor.
- The exact combining formula (e.g. `df × log(1 / background_freq)`, with a smoothing floor for
  out-of-baseline tokens and an averaging rule for multi-token n-grams) is settled against the
  real-corpus targets at implementation and pinned by tests; it is a transparent arithmetic
  function, not a tuned model.

### D2 — Vendor a compact general-English frequency baseline; degrade gracefully

Commit a small general-English word-frequency list (a top-N unigram frequency table, a few KB to
low-MB, plain JSON/text) as a repo asset, mirroring `ontology/qudt-units.json`: referenced as
data, never dereferenced, cross-run stable. The scorer looks up each token's background frequency;
an out-of-list token is treated as maximally rare (a configurable floor), which is the desired
behavior for genuine domain jargon.

- **Graceful degradation:** if the baseline file is missing/unreadable, log a warning and fall
  back to the current document-frequency ranking, so the miner never hard-fails on a missing
  asset (same spirit as the empty-corpus fallback already in the scorer).
- _Alternative — pull a frequency package (wordfreq etc.):_ rejected; adds a third-party
  dependency and non-vendored data, against the project's vendoring convention.

### D3 — Hardened, normalization/substring-aware exclusion

Build the exclusion set from **all** known labels the core dataset exposes — SKOS
`prefLabel`/`altLabel`, ontology classes, physical properties, salts, and chunk-7's roles/reactors
— and match a candidate as excluded when its normalized form equals, or is a normalized
substring/superset token-sequence of, a known label. Normalization collapses case, whitespace, and
punctuation, so `molten salt` ≡ `MoltenSalt` and is excluded. This closes the space-variant gap
and drops already-modeled multiword terms before they consume a top-N slot.

- Exclusion still reads only the three core `FROM` graphs (never staging/proposal), preserving the
  chunk-8 rule that a still-pending proposal does not suppress re-detection while an
  approved-into-core term does.
- _Trade-off:_ substring/superset matching risks over-excluding a legitimately novel term that
  merely contains a known token (e.g. a novel `... salt` phrase). Mitigated by matching on
  normalized **token-sequence containment**, not raw substring, and by keeping the match
  conservative (a candidate is excluded only when a known label's full token sequence is present),
  so a novel compound is not dropped merely for sharing one token.

### D4 — Bounded top-N reviewable queue

After scoring and exclusion, sort candidates by keyness descending with a deterministic tie-break
(score, then document frequency, then term) and keep only the top-N (`config`, default ~50). This
bounds the triage fan-out (Flash calls) and the proposal count to a prioritized, reviewable set.
The miner logs how many candidates were scored, how many survived exclusion, and how many were
cut by the top-N (never a silent truncation).

- N is a config knob (env-overridable, test-pinned), not a magic literal, consistent with how
  `salience_threshold` is treated.
- _Alternative — no cap, rely on the threshold:_ rejected; the real corpus shows no threshold
  yields a reviewable count without dropping the targets (Context).

### D5 — Scope containment: selection only, contract preserved

`mine_candidates` is the only behavior that changes shape: enumerate → harden-exclude → score
(keyness) → top-N → attach evidence. It still returns a `list[Candidate]` with the same fields
(the keyness score can be carried alongside `doc_frequency`, which is retained for evidence and
the `msr:docFrequency` proposal field). Triage, proposal emission, auto-accept, and provenance are
untouched and see a smaller, better-ordered list.

## Risks / Trade-offs

- **Keyness formula mis-tuned drops a real target** → pin the formula against the real-corpus
  targets (`solubility`, `graphite` must land in the top-N; `molten salt`/`heat transfer` must
  not) in both unit tests (fixture baseline) and the guarded integration test; treat those as
  regression gates.
- **Hardened exclusion over-excludes a novel term** → conservative token-sequence containment
  (D3), not raw substring; covered by a test asserting a novel multiword term sharing one token
  with a known label is NOT excluded.
- **Vendored baseline drifts or is missing** → graceful fallback to df ranking with a logged
  warning (D2); the file is committed and cross-run stable.
- **Top-N hides a genuine candidate below the cut** → N is configurable and the run logs the
  cut count, so a reviewer can widen N; the POC bias is precision over recall.
- **Editing `novelty.py` again** touches recently-landed code → the change is additive to
  `mine_candidates` and keeps the fast inverted scan; existing novelty tests must stay green.

## Migration Plan

Additive on top of the merged chunk 8 + the DF-scan perf fix. Commit the vendored frequency file;
`novelty.py` gains keyness scoring, hardened exclusion, and the top-N cut; config gains the knobs.
`make mine` then triages ≤ N candidates. Rollback: revert this change — mine returns to the (fast
but unbounded) df-threshold behavior; nothing else in the pipeline depends on the ranking. No graph
migration: the change only affects which `Candidate`s are produced in a run, not any stored shape.

## Open Questions

All resolved for implementation:

- **Metric** — Resolved: keyness (weirdness ratio) against a vendored general-English baseline
  (D1), df retained as floor/evidence. Exact formula pinned against real-corpus targets at
  implementation.
- **Baseline source** — Resolved: vendor a compact frequency list as a committed asset with
  graceful fallback (D2); no package.
- **Bounding** — Resolved: configurable top-N with deterministic tie-break and logged cut (D4).
