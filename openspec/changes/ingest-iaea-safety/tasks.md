# Tasks: ingest-iaea-safety

> **Unblocked.** Chunks 6–9 + 12–13 have all landed on `main` (see `proposal.md` → Prerequisites);
> this change builds on those merged specs. Chunk 10 (frontend) is not a hard prerequisite. All tasks
> are unchecked; task wording below references the built specs by name.

## 1. Safety-source acquisition (`safety-source-acquisition`)

- [x] 1.1 Confirm `scripts/fetch-safety-sources.sh` (already added) populates the gitignored `data/safety/` cache with the four sources; make it idempotent (skip present files)
- [x] 1.2 Author the committed attributed manifest (source id, title, publisher, rights, `dcterms:source` URL, date, ingested section/page scope) in the extraction package; SRS-123 scoped to §2.1.2.5 / §3.2 / §5.1.8, the GIF/ORNL docs whole
- [x] 1.3 Implement `safety extract`: pypdf text extraction per cached PDF → `data/safety/{id}.txt`, honoring the manifest's section/page scope; add `pypdf` (+ `cryptography` for the encrypted IAEA PDF) to `pyproject.toml`
- [x] 1.4 Run the chunk-5 normalizer + segmenter over the extracted text → `data/safety/{id}/normalized.txt` + `segments.jsonl` (reuse, do not fork, the chunk-5 code)

## 2. Attributed Document nodes (`safety-source-acquisition`)

- [x] 2.1 Emit one `msr:Document` per source keyed by identifier (`msrd:PUB2027-SRS-123`, `msrd:GIF-Holcomb-MSR-safety`, `msrd:ORNL-TM-2006-12`, `msrd:ORNL-MSR-tech-safety`) with `rdfs:label`, `dcterms:identifier`, `dcterms:date`, `dcterms:publisher`, `dcterms:rights`, `dcterms:source`
- [x] 2.2 Attach the chunk-12 provenance edges (`prov:wasDerivedFrom`/`wasGeneratedBy`, per-run activity in `urn:msr:provenance`); deterministic IRIs, additive `INSERT DATA`, idempotent

## 3. Safety branch via the evolution loop (`safety-ontology-evolution`)

- [x] 3.1 Extend the built `novelty-detection` spaCy noun-chunk pass for the safety genre: relax the 1–3 content-token window / preserve the noun-chunk head phrase so prepositional safety concepts ("confinement of radioactive material", "removal of residual heat") survive as candidates; reuse unchanged the DF floor/ceiling, known/linked exclusion, and `msr:citedIn`+offset evidence capture
- [x] 3.2 Make the `candidate-triage` Flash classifier genre-aware: prompt it with the safety genre so it (a) does not reject domain-shaped safety phrases as boilerplate and (b) for `class`-kind safety concepts proposes a Safety broader-class placement, and for the two linking edges proposes `relation`-kind domain/range. Kinds (`property`/`class`/`instance`/`relation`), the `change-proposal-schema` mini-schema, `proposal-staging`, and `approval-typed-routing` are unchanged
- [ ] 3.3 Verify the three fundamental safety functions (confinement of radioactive material, control of reactivity, heat removal) surface as proposals with evidence from the ingested sources
- [ ] 3.4 Confirm `approval-typed-routing` routes the approved safety classes/relations into `urn:msr:ontology` (and individuals/edges into `urn:msr:data`) and `proposal-lifecycle` minor-bumps `owl:versionInfo` — no new engine code, since routing is by triple type and already handles TBox axioms + mixed bundles

## 4. Digital-thread linking (`safety-property-linking`)

- [x] 4.1 Extend the built `relation-extraction` stage (genre-aware, stubbed-Flash) to emit `msr:servedByProperty` (`SafetyFunction → PhysicalProperty`) **only** where a source sentence states the dependency; run linking extraction as a **second phase** after the safety branch is approved into core, so the closed-set validation resolves the (grown) safety subjects/targets
- [x] 4.2 Emit `msr:addressesFunction` (`Requirement → SafetyFunction`) where stated
- [x] 4.3 Write each edge's evidence via the chunk-7 `rdf:Statement` reification pattern (`salt-role-reactor-edges`): direct edge + a deterministic reification node carrying `msr:extractionConfidence`/`msr:extractionRationale` + the chunk-12 provenance edges; record every relation (written/skipped/rejected) in `relations.jsonl`; reject an edge whose property/function target IRI is not in core
- [x] 4.4 Extract optional `rdfs:seeAlso` from a `SafetyFunction`/`Requirement` to a named IAEA standard identifier **only** where the text names the standard
- [x] 4.5 Extract `msr:thresholdValue` / `msr:thresholdComparator` / `msr:thresholdUnit` on a `Requirement` only when the source states a numeric threshold (e.g. liquidus < 500 °C)

## 5. Provenance & SHACL (extends chunks 12–13)

- [ ] 5.1 Confirm safety documents/mentions/individuals/edge-reification-nodes carry the chunk-12 provenance edges (reuse the shared `provenance.py` writer; no new provenance model)
- [x] 5.2 Extend the `shacl-validation` catalogue Turtle (reserved shapes graph): add `SafetyFunction`/`Requirement` provenance shapes (`wasDerivedFrom` + `wasGeneratedBy`), a `servedByProperty`-target-must-be-`PhysicalProperty` shape, and an `addressesFunction`-target-must-be-`SafetyFunction` shape. **No new mention shape** — safety `Mention`s are already covered by the landed `Mention` shape. No threshold/satisfaction shape

## 6. Agent safety answers (`analysis-agent`)

- [ ] 6.1 Verify the KG-schema prompt rebuild on the post-approval version bump includes the Safety branch (chunk-4 mechanism; no hardcoded safety terms)
- [x] 6.2 Add SPARQL query patterns for the evidence-chain traversal and the evidence-gap (`FILTER NOT EXISTS`) query as agent-usable examples/tests
- [ ] 6.3 Verify requirement-satisfaction is computed in a sandbox script (threshold vs measurement → margin) and the answer carries the soft-criterion caveat; an ungrounded safety claim is stamped ungrounded

## 7. Extraction CLI & run model

- [ ] 7.1 Add the `safety` subcommand group (`fetch`, `extract`, `ingest` umbrella running extract → normalize/segment → documents → NER → relations → mine over the safety genre)
- [ ] 7.2 Add the `make ingest-safety` target (one-shot Compose run of the extraction container), additive to the root `Makefile`

## 8. Tests

- [ ] 8.1 pypdf extractor: a committed text-layer PDF fixture → expected text (offline)
- [ ] 8.2 Section-scoping: manifest-driven page/section selection picks the right span from a fixture
- [ ] 8.3 Multi-word candidate extraction: fixture safety sentences → expected noun-phrase candidates; single-token noise excluded
- [ ] 8.4 Genre-aware triage (stubbed-Flash): fixed classifications → proposal graphs validate against the chunk-8 mini-schema with the safety class kinds
- [ ] 8.5 Linking extraction (stubbed-Flash): fixture sentences → expected `servedByProperty` / `addressesFunction` edges, each with its `rdf:Statement` reification (confidence/rationale) + provenance + `relations.jsonl` record; a **co-mention without a stated dependency yields no edge**; unknown / not-yet-approved target IRI rejected
- [ ] 8.6 Threshold extraction: the liquidus-preference sentence → `thresholdValue 500` / `comparator lt` / unit; no-threshold sentence yields none
- [x] 8.7 Agent (stubbed LLM + fake pool): evidence-chain traversal returns the provenance chain; gap query returns the missing-measurement set; requirement-satisfaction computes 434 vs 500 margin in a sandbox script with the soft-criterion caveat; ungrounded safety claim stamped ungrounded
- [x] 8.8 SHACL (opt-in, GraphDB-required): safety individual missing `wasDerivedFrom` rejected; valid safety facts load
- [ ] 8.9 Guarded corpus integration (opt-in env flag): four safety `Document` nodes with attribution present; three fundamental safety functions surfaced as proposals; after approval `msrd:sf-heat-removal msr:servedByProperty msr:specificHeat` resolvable and traceable to a salt measurement; second run leaves `urn:msr:data` triple counts unchanged

## 9. Documentation

- [ ] 9.1 Update `docs/DATA_SCOPE.md` §4 from "stretch/deferred" to the finalized ingested set + section scope + attribution
- [ ] 9.2 Document `make ingest-safety`, the `data/safety/` layout, and the attribution/licensing rule in the README
- [ ] 9.3 Cross-link `docs/SAFETY_THREAD_SPIKE.md` (the grounded thread + stakeholder questions) as the realized-capability reference
