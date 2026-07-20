# Tasks: refine-mine-salience

## 1. Vendored general-English baseline

- [ ] 1.1 Vendor a compact general-English unigram word-frequency baseline as a committed repo asset (small JSON/text, a few KB–low-MB), mirroring the `ontology/qudt-units.json` vendoring pattern (referenced as data, never downloaded/dereferenced); document its source and format in a header/comment
- [ ] 1.2 Add a loader for the baseline (pure-Python, stdlib only, no new package): parse the file into a `token -> background frequency/rank` map; on a missing/unreadable/malformed file, return an empty/None baseline and log a warning (graceful degradation, design D2)

## 2. Config knobs

- [ ] 2.1 Extend the config module with the top-N cap (`mine_top_n`, default ~50) and any keyness parameters (e.g. out-of-baseline rarity floor) plus the baseline file path; env-overridable and injectable for tests, alongside the existing `salience_threshold`

## 3. Keyness scoring (`novelty-detection`)

- [ ] 3.1 Implement the keyness scorer: combine a candidate's corpus document frequency (from the existing inverted n-gram-set scan, retained) with the rarity of its constituent tokens in the vendored baseline into a transparent, deterministic score; treat an out-of-baseline token as maximally rare (configurable floor); define the multi-token n-gram combining rule (design D1)
- [ ] 3.2 Pin the exact combining formula against the real-corpus targets: `solubility` and `graphite` must outrank `molten salt` / `heat transfer` / `high temperature`; keep document frequency as a floor/evidence input, not the sort key
- [ ] 3.3 Fall back to document-frequency ranking (current behavior) with a logged warning when the baseline is absent (design D2)

## 4. Hardened exclusion (`novelty-detection`)

- [ ] 4.1 Build the exclusion set from ALL core labels — SKOS `prefLabel`/`altLabel`, ontology classes, physical properties, salts, and chunk-7 role/reactor labels — read only through the three core `FROM` graphs via the chunk-6 `GraphReader` (staging/proposal graphs still excluded)
- [ ] 4.2 Make exclusion normalization/token-sequence-aware: collapse case/whitespace/separators so `molten salt` ≡ `MoltenSalt` is excluded, and match on normalized token-sequence containment (a known label's full token sequence present in a candidate) so a candidate sharing only a single token with a known label is NOT excluded (design D3)

## 5. Bounded top-N + umbrella wiring (`novelty-detection`)

- [ ] 5.1 Update `mine_candidates`: enumerate → hardened-exclude → keyness-score → sort by score (deterministic tie-break: score, then document frequency, then term) → keep top-N → attach curated evidence; return the same `list[Candidate]` shape (carry the keyness score alongside `doc_frequency`, which is retained for the `msr:docFrequency` proposal field)
- [ ] 5.2 Log a run line with counts scored / excluded / cut-by-top-N (never a silent truncation); confirm triage/proposals/auto-accept/provenance are unchanged and consume the smaller, ranked list

## 6. Tests

- [ ] 6.1 Baseline-loader tests: a well-formed file parses to the expected token→frequency map; a missing/unreadable/malformed file returns empty/None and logs a warning (no raise)
- [ ] 6.2 Keyness-scorer tests (fixture baseline + fixture corpus): a domain-rare term outranks a higher-document-frequency common term; out-of-baseline token uses the rarity floor; multi-token n-gram combining is deterministic; missing baseline falls back to document-frequency ranking
- [ ] 6.3 Hardened-exclusion tests: a spelling/spacing variant of a known label is excluded (`molten salt` vs `MoltenSalt`); a known role/reactor label (chunk-7) is excluded; a novel multiword term sharing a single token with a known label is NOT excluded; a term present only in `urn:msr:staging` is NOT excluded (three `FROM` graphs injected)
- [ ] 6.4 Top-N / `mine_candidates` tests: with more than N survivors only the top-N by score are returned; ordering is deterministic; the cut count is logged; `doc_frequency` is still populated on returned candidates
- [ ] 6.5 Guarded integration test (opt-in `GRAPHDB_REQUIRED`, real 637-doc corpus): after a real candidate run, `solubility` and `graphite` are in the top-N while `molten salt` / `heat transfer` / `high temperature` are not, and the total triaged candidate count ≤ N; recreate a SHACL-enabled `msr` via REST if needed, not `docker compose down -v`

## 7. Manual acceptance run

- [ ] 7.1 Full real end-to-end `make mine` on the bootstrapped stack (this is the deferred mine 9.1 check, now expected to pass): confirm a bounded, prioritized set of proposals in `urn:msr:staging` led by `solubility` (property) and `graphite` (class) with correct evidence, at least one provenance-complete `msr:autoAccepted` instance in `urn:msr:data`, run lineage in `urn:msr:provenance`, and that generic terms (`molten salt`, `heat transfer`) are absent from the queue; the change is done only after this manual verification passes
