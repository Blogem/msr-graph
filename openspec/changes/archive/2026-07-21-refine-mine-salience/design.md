# Design: refine-mine-salience

## Context

`mine-ontology-candidates` (chunk 8) is merged, including a perf fix that made the
document-frequency scan fast (inverted n-gram-set intersection, ≈3.7 h → 7 s). The first real
`make mine` then exposed that mine's *selection* is broken, and a POC established exactly how far
statistics can and cannot go. All numbers below are measured on the real 637-document OCR corpus.

**Baseline (current mine):** the lexical unigram/bigram/trigram pass emits **252,085** candidates;
**8,861** clear `df ≥ 50`. Document frequency does not rank novelty — measured df:
`molten salt` 423 · `graphite` 379 · `high temperature` 324 · `heat transfer` 318 ·
`fuel salt` 308 · `solubility` **271** — so the genuine targets are *less* frequent than
common/known phrases.

**POC — spaCy shaping (validated win):** `en_core_web_sm` `doc.noun_chunks`, content-noun tokens,
NER-filtered, over the curated docs → **23,306** candidates (10×), concept-shaped; NER removed
much real OCR noise (`Union Carbide Corporation`, `Oak Ridge`, author names); targets retained
(`solubility`, `graphite`, `moderator`, `eutectic`); ~96 s one-shot.

**POC — statistical novelty ranking (disproven):** spaCy-shaped + hardened-exclude + keyness
(weirdness ratio vs a general-English baseline) still ranks **OCR noise at the top** — acronyms
(`ornl`, `usaec`, `aec`), OCR fragments (`tion`, `ments`, `ture`, `dwg`), and NER-missed surnames
(`trauger`, `bettis`, `swartout`, `grimes`); the real targets land at ranks **33 (graphite), 152
(solubility), 164 (eutectic), 271 (moderator)**. An in-vocabulary band-pass did not fix it
(surnames/fragments have moderate web-frequency). Conclusion: on OCR of this quality, "rare +
frequent" cannot separate novel concepts from garbage; the discriminator is semantic.

**Hardened exclusion (validated):** matching candidates against all core labels correctly drops
already-modeled terms (`density`, `viscosity`, `corrosion`).

The pipeline already contains the semantic discriminator: the Flash **triage** step. So this
design confines candidate selection to what statistics *can* do — **shape** (spaCy) + **exclude**
(hardened) + **coarse-bound** (DF floor + hard ceiling) — and makes the **LLM triage + chunk-9
human review** the precision mechanism, by giving triage the ability to *reject* non-concepts.

## Goals / Non-Goals

**Goals:**

- Enumerate concept-shaped candidates via spaCy noun-chunks, dropping proper nouns/entities and
  the n-gram explosion, while keeping the chunk-6 salt-formula misses.
- Harden exclusion so already-modeled terms (any spelling, incl. camelCase/space variants) never
  reach triage.
- Bound the triage fan-out with a DF floor + a hard max-candidates ceiling — a **cost** bound, not
  a novelty rank.
- Let Flash triage reject non-concepts (OCR fragments, acronyms, missed proper nouns, generic
  boilerplate) so the LLM is the precision filter; chunk-9 review is final.
- Preserve determinism (spaCy/Flash are deterministic in eval; runaway cap is DF-sorted +
  logged), the `msr:ChangeProposal` staging contract, and the provenance/write paths.

**Non-Goals:**

- **No statistical novelty score (keyness/weirdness/TF-IDF).** The POC disproved it on this OCR;
  building it would be effort spent on a dead end.
- No embedding/BERT novelty model in this change (documented as a future experiment; the POC
  suggests semantic scoring on OCR is hard and the LLM already does the job).
- No change to proposal emission, instance auto-accept, provenance, or the chunk-9 contract.
- No re-OCR / corpus cleanup (out of scope; the miner tolerates OCR noise by letting triage
  reject it).

## Decisions

### D1 — spaCy noun-chunk enumeration replaces the n-gram pass

Load `en_core_web_sm` and enumerate candidates from `doc.noun_chunks` over each curated document:
keep content tokens (alphabetic, non-stopword, length ≥ 3) that are **not** part of a dropped
entity (`PERSON`, `ORG`, `GPE`, `LOC`, `FAC`, `NORP`, `DATE`, `TIME`, `CARDINAL`, `ORDINAL`,
`MONEY`, `PERCENT`, `QUANTITY`), lemmatize, and form the candidate from 1–3 surviving tokens. The
chunk-6 `status:"novel"` salt-formula misses remain instance-kind candidates as before.

- This deliberately lifts chunk 6's "rules-only, no statistical model" stance — that was for NER
  *linking*, where rules sufficed; for candidate *mining*, POS + noun-chunks + NER are exactly the
  useful signals, and the model is deterministic at inference.
- _Alternative — keep n-grams + filter:_ rejected; the POC shows n-grams explode to 252k and
  carry the noise noun-chunking avoids.
- Cost: ~96 s to process the ~12 curated docs one-shot (use `nlp.pipe`, disable unused components
  where safe). Acceptable for a one-shot stage.

### D2 — Hardened, normalization/token-sequence-aware exclusion

Build the exclusion set from **all** core labels the `GraphReader` exposes — SKOS
`prefLabel`/`altLabel`, ontology class labels, physical-property labels, salt labels, and
chunk-7's role/reactor labels — read only through the three core `FROM` graphs (staging/proposal
never consulted). Normalize both sides by casefolding, splitting camelCase, and collapsing
whitespace/separators, then exclude a candidate when a known label's full normalized token
sequence is present in the candidate's (so `molten salt` ≡ `MoltenSalt` excludes, while a novel
term merely sharing one token with a known label is kept). Retains the chunk-8 rule that a
still-pending proposal does not suppress re-detection.

### D3 — Document frequency is a coarse cost floor + hard ceiling, never a rank

Keep the fast inverted DF scan. Use `salience_threshold` as a low floor to drop rare OCR one-offs,
and add a configurable **`mine_max_candidates`** ceiling: after shaping + exclusion + floor, if
more candidates remain than the ceiling, keep the top-`max_candidates` by DF (deterministic
tie-break) purely as a runaway guard, and **log the count cut**. This bounds triage cost; it is
explicitly *not* a novelty ranking (the POC showed DF order is meaningless for novelty), so the
ceiling is set generously (bounded by what the parallelized triage can afford), not tuned to
surface targets.

- _Why DF-sort the ceiling if DF isn't a novelty signal?_ Only to make the runaway guard
  deterministic and bias toward corpus-recurrent terms if a hard cut is ever hit; in normal
  operation the floor + exclusion keep the set under the ceiling and everything is triaged.

### D4 — Triage gains a reject/not-a-concept verdict (the precision mechanism)

Extend the `candidate-triage` classifier so Flash may return an explicit **reject** verdict
("not a genuine novel ontology concept") in addition to `property`/`class`/`instance`/`relation`.
The prompt instructs the model to reject OCR fragments, acronyms, proper nouns (people, orgs,
places), and generic boilerplate. App-side validation treats a reject (and, as today, malformed
output) as "drop the candidate — emit no proposal." This is what removes the noise that shaping +
exclusion cannot (a noun-chunk like `laboratory` or an OCR-surname the NER missed). The reject is
recorded in the run summary counts.

- _Alternative — a cheap lexical noise filter (dictionary/real-word check) before triage:_
  rejected as the primary mechanism (the POC's in-vocab band-pass leaked surnames/fragments with
  moderate web-frequency); may be added later as a cheap pre-cut, but the LLM reject is the
  reliable filter and it already runs.

### D5 — `en_core_web_sm` pinned as a model wheel; deterministic; graceful absence

Pin the model as a wheel URL in `extraction/pyproject.toml`
(`en_core_web_sm-3.8.x`, matching `spacy==3.8.7`) so builds are reproducible and no runtime
download occurs. spaCy inference is deterministic (no sampling), preserving mine's determinism
guarantee. If the model fails to load, log a clear error and fall back to the existing n-gram
enumeration so the stage degrades rather than hard-fails (mirrors the empty-corpus/absent-baseline
fallback pattern already in the miner).

## Risks / Trade-offs

- **Triage cost rises** (LLM is now the filter over a few-thousand-candidate set) → bounded by the
  DF floor + `mine_max_candidates` ceiling and the already-parallelized triage fan-out; the run
  summary logs candidate/triaged/rejected counts so cost is visible.
- **Flash over-rejects a real novel concept, or under-rejects noise** → the reject is a
  reviewer-visible verdict, not a hard delete of evidence; chunk-9 review is the backstop, and the
  reject prompt/threshold is tuned against the real-corpus targets (solubility/graphite must
  survive; `ornl`/`trauger`/`laboratory` must be rejected) as a regression gate.
- **OCR-fragmented text defeats spaCy NER** (surnames leak as noun-chunks) → accepted; those leak
  to triage and are rejected there (D4), which is the whole point of the LLM-as-filter split.
- **Model dependency / image size** (`en_core_web_sm` ≈ 12 MB) → small, pinned, build-time; no GPU;
  spaCy already a dependency.
- **Determinism** → spaCy and Flash are deterministic in eval; the ceiling cut is DF-sorted +
  logged; no randomness introduced.

## Migration Plan

Additive on merged chunk 8 + the DF-scan perf fix. Pin `en_core_web_sm`; rework `novelty.py`
enumeration (spaCy) + exclusion (hardened) + DF floor/ceiling; extend `triage.py` with the reject
verdict; `mine_runner` drops rejected candidates and logs the counts. Bootstrap order unchanged
(`… → link → extract → mine`). Rollback: revert this change — mine returns to the (fast but
unbounded/unshaped) n-gram+DF behavior; the graph shape and downstream contract are untouched
(the change only affects which `Candidate`s a run produces). No graph migration.

## Open Questions

All resolved for implementation (informed by the POC):

- **Statistical novelty score?** Resolved: no — disproven on this OCR (Context/D3). Selection is
  shape + exclude + coarse-bound only.
- **Where does precision come from?** Resolved: the Flash triage reject verdict + chunk-9 review
  (D4), not a candidate score.
- **Model dependency?** Resolved: pin `en_core_web_sm` as a wheel, deterministic, with graceful
  fallback to n-gram enumeration (D5).
- **Embedding/BERT novelty?** Deferred as a future experiment; not in this change.
