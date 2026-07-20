## Context

This change lands **first** in the trust sequence (ground-demo → `provenance-model` → `shacl-validation`): make the data real before layering provenance and the write-time gate. Today grounding reaches a salt only via the hand-curated seed's `skos:closeMatch` edge (`internal/agent/sparql.go:26-29,50-53`), and the seed (`ontology/example-flibe.ttl`) also hand-curates `msr:hasRole`/`msr:usedIn` and `msrd:MSRE` — fabricated facts that violate Principle 3. This change has **no functional dependency on `provenance-model`**: grounding needs only the salt + measurement (loader) and the `mention → linksTo → salt` edge (linker). It does leave an interim provenance gap that `provenance-model` closes — see D7.

Verified facts (live clone of `openmsr/msr-archive`; the corpus is gitignored, so none of this is visible from committed artifacts):

- **A real composed mention exists and already links to the salt.** `ORNL-TM-2316` OCR contains `"LiF-BeF, (66-34 mole %)"` (lines 225, 370, 1335). The OCR-robust linker (chunk 6.1) resolves it and emits `msr:Mention → msr:linksTo → msrd:salt-BeF2-LiF-34.0-66.0` — the salt the loader mints the density measurement for (2.413 − 4.88e-4·900 = 1.974 g/cm³). That `linksTo` is the honest, provenanced edge connecting a document's name for the salt to the salt individual.
- **`skos:closeMatch` between a salt and a concept is a SKOS abuse.** SKOS mapping properties have domain/range `skos:Concept`; a `msr:MoltenSalt` individual is not a concept. The seed's `salt skos:closeMatch voc:flibe` would, under inference or a SHACL shape (chunk 13), wrongly type the salt as a `skos:Concept`. It must not be reproduced.
- **The nickname "FLiBe" is not in the curated docs.** They write `"LiF-BeF2"` / the OCR `"LiF-BeF,"` and abbreviate it `"L;B"` (`ORNL-TM-2316:370`); `grep -iw flibe` over the 11 curated docs returns nothing. So "FLiBe" is *vocab* knowledge, not document text — grounding cannot lean on it appearing in real text.
- **The linker classifies by layer.** A composed formula links to the salt *individual* (layer 3, `linker.py:336-341`); a bare name links to the *concept* (layer 2). So the honest salt link is only produced for composed forms.
- **The vocab seeds NER independently of the A-Box** (`graph_reader.py:38-68`); deleting `example-flibe.ttl` does not break linking, and the loader re-asserts the salt catalog `known_iris` needs.
- **Roles/reactor are real but unextracted.** `ORNL-TM-2316:371`: the 66-34 melt "has been used in the MSRE as the coolant and as [flush]" — real facts, but only unbuilt chunk-7 relation extraction can derive them.

## Goals / Non-Goals

**Goals:**

- Delete `example-flibe.ttl` entirely; the graph is populated only by real-data writers.
- Re-ground the agent on the real `msr:Mention → msr:linksTo → salt` edge; drop `skos:closeMatch`-to-a-salt entirely.
- Keep the FLiBe density demo (question + 1.974 g/cm³) working, grounded through the real `ORNL-TM-2316` mention, with the grounding itself traceable to that document.
- Rework seed-dependent tests, specs, and docs.

**Non-Goals:**

- **No hand-curated data** — nothing replaces the seed by hand; no synthetic `closeMatch`, roles, or reactor.
- **No roles/reactor** — deferred to chunk-7 relation extraction.
- **No linker change** — the `linksTo` edge already exists; this change consumes it.

## Decisions

### D1 — Delete the A-Box; keep TBox + vocab

Remove `ontology/example-flibe.ttl` and drop it from `cmd/loader/seed.go`'s `seedFiles`. `make load-seed` loads only `msr.ttl → urn:msr:ontology` and `vocab.ttl → urn:msr:vocab`; `urn:msr:data` is populated exclusively by `loader nist` and the extraction pipeline. **Alternative rejected:** keep a minimal seed — any hand-authored A-Box is fabricated data (Principle 3).

### D2 — Ground via `msr:linksTo` from real mentions; no `skos:closeMatch`-to-a-salt

The agent resolves a salt reference by matching a real `msr:Mention`'s `msr:surfaceForm` and following `msr:linksTo` to the `msr:MoltenSalt` individual, then reading its measurement. This uses the honest edge the linker already emits, keeps every grounding traceable to a specific document mention (maximally on-theme for a traceability POC), and **eliminates the `skos:closeMatch`-to-a-salt abuse** rather than propagating it. The `sparql_query` tool description (`internal/agent/sparql.go`) and the agent's grounding guidance change from the closeMatch recipe to the linksTo recipe. Property-side grounding does **not** use `skos:closeMatch` either: `voc:density skos:closeMatch msr:density` is the *same* SKOS range abuse (`msr:density` is a `msr:PhysicalProperty`, not a `skos:Concept`), so it is dropped with all the rest (see D6); properties resolve by `rdfs:label`, not a concept hop. **Alternatives rejected:** (a) derive a `salt skos:closeMatch concept` in the linker — reproduces the SKOS abuse and adds a workaround edge for a link that already exists; (b) a new typed `msr:denotedByTerm` property — an extra hop and a new predicate for no gain over the existing `linksTo`.

### D3 — Grounding query shape and surface-form matching

The reworked grounding query, schematically:
```
?m a msr:Mention ; msr:surfaceForm ?sf ; msr:linksTo ?salt .
?salt a msr:MoltenSalt ; <measurement joins> .
FILTER( <?sf matches the user's salt reference> )
```
Because OCR surface forms are noisy (`"LiF-BeF, (66-34 mole %)"`), the match must be **tolerant** — component-token + composition-digit containment rather than exact string equality — and the demo question already carries a matchable form ("the LiF-BeF₂ 66-34 mol% melt"). The exact matching predicate (SPARQL `CONTAINS`/`REGEX` over normalized tokens, and whether to normalize the query term through `formula.normalize_salt_span`) is tuned against the real `mentions.jsonl` produced by a live `link` run (task gate). **Fallback if surface-form matching proves unreliable:** match the salt by its loader-provided clean `rdfs:label` and require a `linksTo` Mention as the grounding *evidence*/provenance — still no `closeMatch`, still document-traceable. The salt is keyed on its composition; the vocab labels (including "FLiBe") are already in the agent's schema prompt, so the agent maps whatever name the user uses to the composition when it writes the query — no special nickname handling is needed.

### D4 — The demo graph is built by the full real pipeline

With no seed A-Box, grounding data exists only after `load-nist` + `ingest` + `link`. So:
- `make demo-density` and the end-to-end acceptance presuppose that full build (link's disambiguation may need `DEEPSEEK_API_KEY`; the composed-salt layer-3 match itself is deterministic, no LLM).
- The guarded `MSR_LINK_INTEGRATION=1` test (`extraction/tests/test_link_integration.py:185-211`), which already asserts a composed mention `msr:linksTo msrd:salt-BeF2-LiF-34.0-66.0`, is the authoritative end-to-end check.
- Go unit tests feeding **canned** SPARQL bindings (`internal/agent/acceptance_test.go`, `cmd/server/chat_sse_test.go`) keep their fixtures (they never touched a live graph) but update them to the linksTo-shaped grounding + real-mention provenance (answer stays 1.974); they remain fast and offline.
- Seed-loading Go integration tests (`internal/graph/seed_integration_test.go`, `nist_loader_integration_test.go`) are reworked: no seed-only `hasRole`/`usedIn`/measurement assertions; the measurement comes from `loader nist`; the grounding-link assertion moves to the guarded link-pipeline test.

### D5 — Roles/reactor deferred, honestly

`msrd:MSRE`, `msr:hasRole`, `msr:usedIn` are removed with the seed and not reintroduced. The demo does not need them. `ORNL-TM-2316:371` shows the coolant + MSRE-usage facts are real and present in text, so chunk-7 relation extraction can derive them later (with provenance); until then, specs/docs claiming the demo shows salt roles are softened.

### D6 — Eliminate `skos:closeMatch` from grounding and the TBox; ground properties by label; drop the orphaned role/reactor layer

Grounding uses no `skos:closeMatch` at all. Salts resolve via `Mention.surfaceForm → msr:linksTo → salt` (D2); **properties resolve by matching the query term against a `msr:PhysicalProperty`'s own `rdfs:label`** (`"density"`, `"viscosity"`, … already in `msr.ttl`) — no concept hop. The salt↔concept and property-term↔concept `skos:closeMatch` links were the *same* SKOS range abuse (its domain/range is `skos:Concept`; neither a `MoltenSalt` individual nor a `msr:PhysicalProperty` is one), so both go. With grounding label/mention-based, **every `skos:closeMatch` is now unused and is removed — the forward links in `msr.ttl` (OWL-term→SKOS-concept) *and* the reverse links in `vocab.ttl` (SKOS-concept→OWL-term)**; they are the same abusive alignment asserted in opposite directions (and several `vocab.ttl` links would otherwise dangle at the role/reactor TBox terms removed below). If explicit alignment is wanted later, a correctly-typed property — not `closeMatch` — can be introduced. The **role/reactor TBox layer** (`msr:SaltRole`/`FuelSalt`/`CoolantSalt`/`FlushSalt`/`hasRole`, `msr:MoltenSaltReactor`/`usedIn`) was populated only by the deleted seed and is unused until chunk-7 relation extraction; by the project's "defer capabilities without a real source" principle it is removed now and reintroduced in chunk-7 with the real data that populates it. The vocab (`vocab.ttl`) keeps its role/reactor **concepts** (their `prefLabel`/`altLabel` seed NER for chunk-7); only the now-unused `closeMatch` triples on them are dropped. **No special demo path:** grounding is data-driven; illustrative examples in tool descriptions stay neutral, and it is acceptable that some queries do not ground perfectly — real data over a demo that hinges on special-casing. **Alternative rejected:** re-type the `closeMatch` links to a proper alignment predicate now — unnecessary churn, since grounding no longer needs any cross-layer edge.

### D7 — Lands first; interim provenance gap closed by `provenance-model`

Because this change ships before `provenance-model`, the interim graph is *real and groundable* but *not yet fully provenanced*: the loader still emits `prov:wasDerivedFrom msrd:nist-srd27`, but the `Dataset` node (+DOI) and the generation `Activity` trail do not exist until `provenance-model`. `msrd:nist-srd27` is therefore a bare, dangling IRI in the interim — harmless (RDF has no referential integrity, and grounding never reads it). This change does **not** touch loader/extraction provenance; it only deletes the seed, reworks grounding, and trims the TBox. (A measurement↔document `msr:citedIn` edge is **not** part of either change's provenance: NIST SRD-27 carries no per-row citation, so an always-true `citedIn` awaits real citation extraction in chunk 7 — document-traceability for the demo comes from the grounding `msr:Mention`'s `msr:inDocument`, not from `citedIn`.) **Alternative rejected:** move the `Dataset`-node/DOI emission into this change to avoid the dangling IRI — it blurs the clean grounding-vs-provenance split and duplicates work `provenance-model` owns; the dangling IRI is not worth it.

## Risks / Trade-offs

- **Surface-form matching robustness** (D3) → OCR noise makes exact matching fail. Mitigation: tolerant token/composition matching, tuned against real `mentions.jsonl`; documented fallback to salt-label matching with `linksTo` as provenance. The live `link` run is a task gate before finalizing the query.
- **Linker LLM dependency** → `link`'s disambiguation may need `DEEPSEEK_API_KEY`. Mitigation: the density grounding path (layer-3 composed match) is deterministic; document the build order.
- **Demo now depends on the extraction pipeline having run** → heavier precondition than a static seed. Mitigation: that is the point (real data); keep agent unit tests fixture-based so they stay offline.

## Migration Plan

No data migration (POC data disposable). Deploy after `provenance-model`. Reproduce the demo: `make up && make load-nist && make ingest && make link && make demo-density`. Rollback: restore `example-flibe.ttl` + its `seedFiles` entry and revert the `sparql.go` grounding recipe (git revert).

## Open Questions

- **Exact surface-form match predicate** — `CONTAINS` on component tokens vs. normalizing the query term through `formula.normalize_salt_span` vs. the salt-label fallback. Settle against the real `mentions.jsonl` from a live `link` run (task 1).
