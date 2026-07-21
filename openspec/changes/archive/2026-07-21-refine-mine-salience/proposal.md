# Proposal: refine-mine-salience

## Why

The first real `make mine` over the 637-document corpus showed mine's `novelty-detection`
selection is broken: a lexical unigram/bigram/trigram pass emits ~252k candidates, ~8,861 clear
the `df ≥ 50` threshold (thousands of Flash calls + thousands of proposals), and document
frequency cannot rank novelty at all — generic/known phrases outrank the real targets
(`molten salt` 423 > `graphite` 379 > `heat transfer` 318 > `solubility` 271).

A hands-on POC then tested whether a statistical novelty score could fix this. The finding is
decisive: **it can't on this OCR.** Even with spaCy noun-chunk shaping + hardened exclusion + a
keyness (weirdness-ratio) score, the top of the ranking is dominated by OCR noise — acronyms
(`ornl`, `usaec`, `aec`), OCR word-fragments (`tion`, `ments`, `ture`, `dwg`), and author
surnames NER missed on line-fragmented text (`trauger`, `bettis`, `swartout`, `grimes`) — while
the real targets land at ranks 33–271. "Rare-in-English + frequent-in-corpus" describes OCR
garbage as well as it describes novel concepts; no threshold or formula separates them. Deciding
"`graphite` is a novel moderator" vs "`Trauger` is an author" is a **semantic** judgment that
frequency statistics fundamentally cannot make.

Two things the POC *did* validate: (1) spaCy noun-chunk extraction + NER filtering cuts candidates
252k → 23k, shapes them into concepts, and removes much proper-noun noise while keeping the
targets; (2) hardened exclusion correctly drops already-modeled terms (`density`, `viscosity`,
`corrosion`). The missing capability — semantic novelty judgment — already exists in the pipeline:
the Flash triage step. So this change makes candidate selection do only what statistics *can* do
(shape + exclude + coarse-bound) and lets the **LLM triage + human review (chunk 9)** be the
precision mechanism.

## What Changes

- **Replace the n-gram lexical pass with spaCy noun-chunk candidate extraction.** Load a
  statistical spaCy model (`en_core_web_sm`) and enumerate candidates from `doc.noun_chunks` over
  the curated documents: content-noun tokens only, lemmatized, with tokens belonging to
  `PERSON`/`ORG`/`GPE`/`DATE`/… entities dropped. Keep the chunk-6 salt-formula misses as
  instance candidates. (POC: 252k → 23k, concept-shaped, targets retained.) This lifts chunk 6's
  "stays lexical / no statistical model" constraint deliberately — that constraint was for
  rules-only *linking*, and does not serve candidate *mining*.
- **Harden exclusion.** Match candidates (normalization/token-sequence aware, incl. camelCase
  splitting so `molten salt` ≡ `MoltenSalt`) against **all** core labels — SKOS
  `prefLabel`/`altLabel`, ontology classes, physical properties, salts, and chunk-7's
  role/reactor layer — read only through the three core `FROM` graphs.
- **Keep document frequency only as a coarse cost floor, not a novelty rank.** Retain the
  already-landed fast inverted DF scan to drop rare OCR one-offs (configurable threshold) and add
  a configurable hard **max-candidates ceiling** (runaway guard, DF-sorted, logged) so the triage
  fan-out is bounded. **No keyness / weirdness scoring** — the POC disproved it; do not build it.
- **Make triage the semantic filter: add an explicit "reject / not-a-concept" verdict.** Extend
  the `candidate-triage` classifier so Flash can reject a candidate that is not a genuine novel
  ontology concept (OCR fragment, acronym, proper noun that slipped NER, generic boilerplate);
  rejected candidates emit no proposal. This is what actually removes the noise that survived the
  statistical stage.
- **Set honest expectations.** mine surfaces a bounded, concept-shaped, known-excluded candidate
  set; the LLM triage and chunk-9 human review provide precision. mine is candidate *generation*
  feeding governance, not an unsupervised oracle that ranks the demo targets to the top.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `novelty-detection`: candidate enumeration changes from an n-gram lexical pass to spaCy
  noun-chunk extraction (POS/NER-filtered, lemmatized); exclusion becomes normalization/
  token-sequence-aware over all core labels; salience changes from "keep at/above a DF threshold"
  to "DF as a coarse floor + a hard max-candidates ceiling" with **no** novelty ranking.
- `candidate-triage`: the classifier gains an explicit reject/not-a-concept verdict so the LLM
  filters non-concept candidates; a rejected candidate produces no proposal.

## Impact

- **Code**: `extraction/src/msr_extraction/novelty.py` (spaCy enumeration, hardened exclusion, DF
  floor + max-candidates cap) and `triage.py` (reject verdict + prompt/validation update).
  `proposals.py`/`auto_accept.py`/`mine_runner.py` provenance/write paths unchanged; `mine_runner`
  drops rejected candidates.
- **Dependency**: adds the `en_core_web_sm` spaCy model as a pinned wheel in
  `extraction/pyproject.toml` (spaCy itself is already present; the model is a build-time
  download, deterministic at inference). No other new package.
- **Config**: DF floor (existing `salience_threshold`, repurposed as a coarse floor),
  `mine_max_candidates` ceiling, spaCy model name — injectable, env-overridable, test-pinned.
- **Performance**: one-shot spaCy pass over the ~12 curated docs ≈ 90s (acceptable); triage
  fan-out bounded by the ceiling and already parallelized. More Flash calls than before (the LLM
  is now the filter), bounded by the ceiling.
- **Depends on**: merged `mine-ontology-candidates` + the DF-scan perf fix; chunk-7 role/reactor
  labels (now part of the exclusion surface). Downstream chunk-9 staging contract unchanged.
- **Acceptance**: on the real corpus, mine emits a bounded, reviewable proposal set in which
  `solubility` (property) and `graphite` (class) appear with correct evidence, while OCR
  fragments / acronyms / author names / already-modeled terms do not; validated by hermetic unit
  tests (stubbed Flash), a guarded integration test, and a real end-to-end run.
