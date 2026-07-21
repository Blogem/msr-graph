# Tasks: refine-mine-salience

## 1. spaCy model dependency

- [x] 1.1 Pin the `en_core_web_sm` spaCy model (matching `spacy==3.8.7`, i.e. `en_core_web_sm-3.8.x`) as a wheel-URL dependency in `extraction/pyproject.toml`; confirm the extraction image builds with it (build-time download, no runtime fetch) and inference needs no GPU
- [x] 1.2 Add a lazily-loaded, injectable spaCy pipeline accessor (deferred import so the module stays importable without the model); on load failure log a clear error and signal fallback to the n-gram pass (design D5)

## 2. Config knobs

- [x] 2.1 Extend the config module: repurpose `salience_threshold` as the low document-frequency floor, add `mine_max_candidates` (the hard runaway ceiling) and the spaCy model name; injectable, env-overridable, test-pinned

## 3. spaCy noun-chunk enumeration (`novelty-detection`)

- [x] 3.1 Implement the spaCy noun-chunk candidate pass over the curated `normalized.txt`: `doc.noun_chunks` → keep content tokens (alphabetic, non-stopword, len ≥ 3) not in a dropped-entity type (`PERSON`/`ORG`/`GPE`/`LOC`/`FAC`/`NORP`/`DATE`/`TIME`/`CARDINAL`/`ORDINAL`/`MONEY`/`PERCENT`/`QUANTITY`), lemmatize, form 1–3-token candidates; use `nlp.pipe` and disable unused components where safe (perf); retain surface form + document + offsets
- [x] 3.2 Keep the chunk-6 `status:"novel"` salt-formula misses as instance-kind candidates (unchanged reader); no chunk-6 linker re-run
- [x] 3.3 Fall back to the prior n-gram enumeration (with a logged error) when the spaCy model is unavailable (design D5)

## 4. Hardened exclusion (`novelty-detection`)

- [x] 4.1 Build the exclusion set from ALL core labels — SKOS `prefLabel`/`altLabel`, ontology classes, physical properties, salts, and chunk-7 role/reactor labels — read only through the three core `FROM` graphs via `GraphReader` (staging/proposal excluded)
- [x] 4.2 Normalize both candidate and known labels (casefold, split camelCase, collapse whitespace/separators) and exclude on token-sequence containment (a known label's full token sequence present in the candidate); a candidate sharing only a single token with a known label is NOT excluded (design D2)

## 5. Coarse cost bound (`novelty-detection`)

- [x] 5.1 Update `mine_candidates`: enumerate (spaCy) → harden-exclude → apply the document-frequency floor → if over `mine_max_candidates`, keep top-N by document frequency (deterministic tie-break) as a runaway guard and log the count cut → attach curated evidence; return the same `Candidate` list shape (`doc_frequency` retained for the `msr:docFrequency` proposal field). Remove/never add any keyness/weirdness ranking
- [x] 5.2 Log a run line: candidates enumerated / excluded / below-floor / cut-by-ceiling (never a silent truncation)

## 6. Triage reject verdict (`candidate-triage`)

- [x] 6.1 Extend the triage classifier: add an explicit `reject` (not-a-concept) verdict alongside the four kinds; update the prompt to instruct rejection of OCR fragments, acronyms, proper nouns (person/org/place), and generic boilerplate; keep the injected/stubbed `Completer` contract
- [x] 6.2 Update app-side validation: a well-formed `reject` verdict drops the candidate and is counted as rejected (distinct from a malformed-output drop); an unrecognized/missing kind still drops as malformed
- [x] 6.3 Wire `mine_runner` to drop rejected candidates and include a `rejected` (and `dropped-malformed`) count in the run summary; proposals/auto-accept/provenance paths unchanged

## 7. Tests

- [x] 7.1 spaCy-enumeration tests (small fixture text, real `en_core_web_sm` or a stubbed pipeline): a noun-phrase concept is enumerated; a `PERSON`/`ORG`/`GPE` proper noun is dropped; a `status:"novel"` miss becomes an instance candidate; model-unavailable falls back to n-gram enumeration
- [x] 7.2 Hardened-exclusion tests: a camelCase/spacing variant of a known label is excluded (`molten salt` vs `MoltenSalt`); a chunk-7 role/reactor label is excluded; a seed property label (`density`/`viscosity`) is excluded; a novel multiword term sharing a single token with a known label is NOT excluded; a staging-only term is NOT excluded (three `FROM` graphs injected)
- [x] 7.3 Cost-bound tests: candidates below the floor are dropped; when survivors exceed `mine_max_candidates` the set is capped (deterministic) and the cut count logged; no keyness/ranking is computed
- [x] 7.4 Triage-reject tests (stubbed Flash): a `reject` verdict → candidate dropped, counted rejected, no proposal; a valid kind → proposal as before; malformed JSON → dropped as malformed (distinct count)
- [x] 7.5 Guarded integration test (opt-in `GRAPHDB_REQUIRED`, real 637-doc corpus + stubbed classifier that rejects noise and classifies the targets): after a run, the emitted proposal set is bounded (≤ ceiling), includes `solubility` (property) and `graphite` (class) with evidence, and excludes already-modeled terms and NER/reject-filtered noise; recreate a SHACL-enabled `msr` via REST if needed, not `docker compose down -v`

## 8. Manual acceptance run

- [ ] 8.1 Full real end-to-end `make mine` on the bootstrapped stack (with DeepSeek configured; this is the deferred mine 9.1 check): confirm a bounded, reviewable set of `msr:ChangeProposal`s in `urn:msr:staging` including `solubility` (property) and `graphite` (class) with correct evidence; confirm OCR fragments / acronyms / author names / already-modeled terms are absent (rejected or excluded); confirm at least one provenance-complete `msr:autoAccepted` instance in `urn:msr:data`, run lineage in `urn:msr:provenance`, and core-dataset invisibility of the proposals; record the candidate/triaged/rejected counts. The change is done only after this manual verification passes
