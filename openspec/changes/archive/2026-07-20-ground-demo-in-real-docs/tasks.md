## 1. Confirm the real evidence end-to-end (gate)

- [x] 1.1 Run the real pipeline (`make up && make load-nist && make ingest && make link`; `link` disambiguation may need `DEEPSEEK_API_KEY`) and confirm `data/corpus/ORNL-TM-2316/mentions.jsonl` contains a layer-3 mention of `"LiF-BeF, (66-34 mole %)"` with `msr:linksTo msrd:salt-BeF2-LiF-34.0-66.0` — VERIFIED against the live `localhost:7200` GraphDB (loader run directly, no Docker/license; link run without `DEEPSEEK` since the composed match is deterministic layer-3): 3 layer-3 mentions of `'LiF-BeF, (66-34 mole %)'` link to `salt-BeF2-LiF-34.0-66.0`
- [x] 1.2 Capture the exact `surfaceForm` strings the linker writes for that mention (and any other salt mentions), to tune the grounding-query match in §2 — VERIFIED: `'LiF-BeF, (66-34 mole %)'` (matches design exactly); sibling melts `'LiF-BeF, (63-37 mole %'`, `'LiF-BeF, (64-36 mole %'`, `'NaF-ZrF, (53-47 mole %'`. The tolerant matcher's `66`/`34` digit filter distinguishes the target from the siblings

## 2. Rework agent grounding (linksTo for salts, rdfs:label for properties; no closeMatch)

- [x] 2.1 Rewrite the grounding recipe in the `sparql_query` tool description (`internal/agent/sparql.go`): ground a salt by matching a `msr:Mention.surfaceForm` and following `msr:linksTo` to the `msr:MoltenSalt`; ground a property by matching the query term against `?p a msr:PhysicalProperty ; rdfs:label ?l`. Remove the `concept → skos:closeMatch → salt/property` recipe and the FLiBe/density worked example (keep any example neutral/illustrative — no special-casing)
- [x] 2.2 Make the salt surface-form match tolerant of OCR noise (component-token + composition-digit containment, informed by §1.2); optionally expand the query term through a vocab `prefLabel`/`altLabel` synonym before matching
- [x] 2.3 Update the agent's grounding guidance (`internal/agent/prompt.go` / `SystemInstructions`) to describe the linksTo (salt) + rdfs:label (property) grounding and to surface the matched `msr:Mention` (with `msr:inDocument`) as the grounding evidence
- [x] 2.4 Confirm no `skos:closeMatch` is required or traversed anywhere in grounding (salt or property)
- [x] 2.5 Update `internal/agent/sparql_test.go` / `prompt_test.go` for the new recipe

## 2b. Trim the TBox (`ontology/msr.ttl`)

- [x] 2b.1 Remove every `skos:closeMatch` from **both** `msr.ttl` (forward, OWL-term→SKOS-concept) **and** `vocab.ttl` (reverse, SKOS-concept→OWL-term) — all now unused by grounding and all the same range abuse (targets are `msr:` OWL terms, not `skos:Concept`s); several `vocab.ttl` links would also dangle at the role/reactor terms removed in 2b.2. Keep each `msr:PhysicalProperty`'s `rdfs:label`, and keep the vocab concepts themselves (their `prefLabel`/`altLabel` seed NER) — drop only their `closeMatch` triples
- [x] 2b.2 Remove the orphaned role/reactor layer: `msr:SaltRole`, `msr:FuelSalt`/`CoolantSalt`/`FlushSalt`, `msr:hasRole`, `msr:MoltenSaltReactor`, `msr:usedIn` (populated only by the deleted seed; return in chunk-7). Keep the corresponding vocab concepts in `vocab.ttl` for NER seeding
- [x] 2b.3 Bump `owl:versionInfo` for the TBox change; confirm `make load-seed` still loads a valid ontology and the prompt builder (`prompt.go`) — which does not read `closeMatch` — is unaffected

## 3. Delete the hand-curated seed

- [x] 3.1 Remove `ontology/example-flibe.ttl`
- [x] 3.2 Drop it from `cmd/loader/seed.go`'s `seedFiles` so `make load-seed` loads only `msr.ttl` → `urn:msr:ontology` and `vocab.ttl` → `urn:msr:vocab`, never writing `urn:msr:data`
- [x] 3.3 Update loader comments referencing the seed's `hasRole`/`usedIn`/`closeMatch` coexistence (`cmd/loader/nist.go`)

## 4. Rework seed-dependent Go tests

- [x] 4.1 `internal/graph/seed_integration_test.go`: `load-seed` no longer exposes a FLiBe measurement; move the "measurement present" assertion to run after `loader nist`
- [x] 4.2 `internal/graph/nist_loader_integration_test.go`: drop assertions that seed-only `hasRole`/`usedIn`/`MSRE` edges survive the load (they no longer exist); keep additive-load and provenance assertions
- [x] 4.3 Ensure the guarded `MSR_LINK_INTEGRATION=1` test (`extraction/tests/test_link_integration.py`) asserts the composed mention `msr:linksTo msrd:salt-BeF2-LiF-34.0-66.0` — the authoritative real grounding-edge check
- [x] 4.4 Update the canned-binding fixtures in `internal/agent/acceptance_test.go` and `cmd/server/chat_sse_test.go` to the linksTo-shaped grounding + real-mention provenance (answer stays 1.974); keep them offline/fast

## 5. Update specs, docs, and the demo path

- [x] 5.1 Update `docs/DATA_SCOPE.md`, `docs/ONTOLOGY.md`, `docs/ARCHITECTURE.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/VOCABULARY.md`, `README.md` to: remove `example-flibe.ttl` from the bootstrap contract, describe the real-pipeline build order (`load-nist` → `ingest` → `link`), describe grounding via `msr:linksTo`, and remove `skos:closeMatch` from the ontology/vocab descriptions (friendly names like "FLiBe" come from vocab `prefLabel`/`altLabel`, not `closeMatch`; keep DIAMOND alignment, which is `rdfs:seeAlso` and stays)
- [x] 5.2 Soften any claim that the demo shows salt roles / reactor association (deferred to chunk-7); note the coolant/MSRE usage is real in `ORNL-TM-2316` but not yet extracted
- [x] 5.3 Add the `document-graph` spec delta: reconcile the two seed-referencing requirements for seed removal — the `msr:Document` write is additive over real-data-writer triples (not a seed A-Box), and `msrd:ORNL-TM-2316` is written by the loader/ingest rather than "already typed in the seed A-Box"
- [x] 5.4 Add the `salt-canonicalization` spec delta: reword the "matching the seed A-Box" IRI-minting phrasing to reference the deterministic minting contract itself (no behavior change; the seed A-Box no longer exists to match)
- [x] 5.5 Confirm `make demo-density` works end-to-end after a full real build, returning ≈ 1.974 g·cm⁻³ with grounding traced to `ORNL-TM-2316` — VERIFIED via the worktree server (`go run ./cmd/server` on :8090, keyed from `.env`, against the live GraphDB + real sandbox): agent grounded through the real mention → `linksTo` → salt, `run_python` computed 1.9738 g/cm³

## 6. Validation

- [x] 6.1 `go test ./...` and the extraction pytest suite green (offline unit tests; guarded integration tests documented)
- [x] 6.2 `openspec validate ground-demo-in-real-docs --strict` passes
- [x] 6.3 Manual acceptance: full build + `make demo-density`, inspect the trace — grounding resolves via a real `msr:Mention`/`msr:linksTo` and the provenance names `ORNL-TM-2316`; no `skos:closeMatch`-to-a-salt anywhere — VERIFIED: trace shows sparql grounding via surfaceForm `"LiF-BeF, (66-34 mole %)"` → `linksTo` → `salt-BeF2-LiF-34.0-66.0`, provenance `ontology_version=0.2.0` + real dataLocator, `run_python` → 1.9738; 0 `skos:closeMatch` triples repo-wide
