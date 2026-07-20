# Proposal: refine-mine-salience

## Why

The first real end-to-end `make mine` over the 637-document corpus exposed that mine's
`novelty-detection` salience — raw document frequency — is not a novelty signal. It enumerates
~252k n-gram candidates and admits **~8,861** above the default `df ≥ 50` threshold (thousands
of Flash triage calls and thousands of proposals — not a reviewable queue), and it cannot
isolate the genuinely novel targets: measured document frequencies put common/already-modeled
phrases **above** the targets — `molten salt` 423, `graphite` 379, `high temperature` 324,
`heat transfer` 318, `fuel salt` 308, `solubility` **271**. So no threshold keeps `solubility`
without also admitting the noise. mine cannot be demo-run or reviewed until candidate selection
ranks domain-novel, not-yet-modeled terms above frequent generic ones and bounds the queue.

## What Changes

- **Replace pure document-frequency salience with a keyness (relative-frequency) score.** A
  candidate's score contrasts its corpus salience against how common its tokens are in general
  English (a "weirdness ratio"): domain terms (`solubility`, `graphite`, `fluoride`) rank high;
  ordinary English/report boilerplate (`temperature`, `high`, `transfer`, `figure`, `table`)
  ranks low. Document frequency remains an input (evidence/floor), not the ranking key.
- **Vendor a compact general-English word-frequency baseline** as a committed data file
  (mirroring the `ontology/qudt-units.json` vendoring pattern) — **no new third-party package**.
  Absence of the baseline degrades gracefully (falls back to the current df behavior with a
  logged warning) so the miner never hard-fails on a missing asset.
- **Harden the exclusion set** to normalization/substring-aware matching against **all** known
  labels — SKOS `prefLabel`/`altLabel`, ontology classes, salts, physical properties, and
  chunk-7's role/reactor layer — so an already-modeled term in any spelling is dropped
  (e.g. `molten salt` now excludes via `msr:MoltenSalt`, closing the space-variant gap).
- **Bound the reviewable queue to a top-N cut.** After scoring and exclusion, keep only the
  top-N candidates by keyness (a config knob, deterministic tie-break), so triage fires a
  bounded number of Flash calls and the reviewer receives a prioritized, finite set.
- **Keep the already-landed fast inverted document-frequency scan** (the n-gram-set
  intersection). N-gram-size restriction stays available as a secondary lever but is not the
  primary fix.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `novelty-detection`: the salience requirement changes from "score by document frequency over
  the full corpus, keep candidates at/above a threshold" to "rank by a keyness score
  (corpus salience contrasted against a vendored general-English baseline), drop already-modeled
  terms via hardened exclusion, and keep only the top-N by score." The candidate-enumeration and
  curated-evidence requirements are unchanged.

## Impact

- **Code**: `extraction/src/msr_extraction/novelty.py` — the scorer and exclusion set; the
  `mine_candidates` umbrella gains the keyness step + top-N cut. No change to
  `triage.py` / `proposals.py` / `auto_accept.py` / `mine_runner.py` provenance/write paths
  (they consume the same `Candidate` list, now bounded and better-ranked).
- **Data**: a new vendored general-English frequency file (small, committed; e.g. under
  `ontology/` or `extraction/`), consistent with `qudt-units.json`.
- **Config**: new knobs for the top-N cap and any keyness parameters (injectable, env-overridable,
  test-pinned), alongside the existing `salience_threshold`.
- **Dependencies**: none added — pure-Python scoring over a vendored list; reuses the merged
  DF-scan and the chunk-6 `GraphReader`.
- **Depends on**: the merged `mine-ontology-candidates` (novelty/triage/proposals/auto-accept +
  the inverted DF scan) and chunk-7's role/reactor labels (now part of the exclusion surface).
- **Downstream unchanged**: chunk-9 governance still consumes the same `msr:ChangeProposal`
  staging contract — this change only improves *which* candidates reach it, not the shape.
- **Acceptance**: on the real 637-doc corpus, `solubility` and `graphite` land in the top-N while
  `molten salt` / `heat transfer` / `high temperature` do not; total triaged candidates ≤ N; the
  demo still yields the solubility (property) and graphite (class) proposals. Gated by hermetic
  unit tests, a guarded integration test, and a real end-to-end run.
