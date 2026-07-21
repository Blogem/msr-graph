# Proposal: mine-ontology-candidates

## Why

The NER core (chunk 6) links known MSR entities to the schema, but every span it *cannot*
settle — the "miss" output — is currently discarded. The self-evolving-ontology demo (the
POC's headline behaviour) needs those misses turned into **reviewable change proposals**:
genuinely novel concepts (the corpus's `solubility` and `graphite`), detected from text,
scored by corpus salience, triaged into a change kind, and packaged with evidence into
staging where chunk 9's governance API can serve them for human approval. This change lands
the detection half of the evolution loop — the *propose*, before chunk 9's *dispose* — and
defines the `msr:ChangeProposal` mini-schema that is the chunk-9 contract. It gates M4
(knowledge grows from text) and, transitively, M5–M6.

## What Changes

- **Novelty miner over the curated text + the chunk-6 misses**: enumerate candidate terms
  from a lexical term pass over the curated documents' text (chunk 6's rules-only
  `spacy.blank` linker never surfaces plain novel terms like `solubility`/`graphite`, so the
  miner cannot rely on its miss output alone) **plus** the `status:"novel"` salt-formula spans
  from `data/corpus/{report#}/mentions.jsonl` (instance-kind candidates); exclude anything
  already linked by chunk 6 or resolvable in the core dataset; and **score each candidate by
  document frequency over all 637 OCR texts** (the chunk-5 LFS-skip clone in
  `data/corpus/msr-archive/`, a cheap text scan) — keeping only candidates above a salience
  threshold. Evidence sentences (text + `msr:citedIn` doc + span offsets) come from the
  curated ~12.
- **Triage into a change kind via DeepSeek V4 Flash**: classify each surviving candidate
  into `property` / `class` / `instance` / `relation` using context signals plus a Flash
  classifier (injected OpenAI-compatible client, **stubbed in every test**) on the reused
  chunk-6 cached KG-schema prompt. The classifier also proposes placement (broader class,
  `quantityKind`, `canonicalUnit`) — presented as **LLM-asserted, reviewer-verified**
  claims, not ground truth.
- **`msr:ChangeProposal` mini-schema (the chunk-9 contract)**: a small governance
  vocabulary added to the seed ontology (`msr:ChangeProposal` with `msr:kind`,
  `msr:reviewStatus`, `msr:term`, `msr:docFrequency`, evidence, and a link to its proposal
  graph), plus the two-graph staging data model — `ChangeProposal` resources →
  `urn:msr:staging`, the proposed triples → `urn:msr:proposal/{id}`.
- **Emit TBox-affecting candidates as proposals**: write the `ChangeProposal` resource +
  its proposed triples with **deterministic proposal IRIs** so re-runs are idempotent;
  `solubility` becomes a property proposal (unit left as a reviewer decision — the corpus is
  unit-ambiguous), `graphite` becomes one **class + relation bundle** (a `Moderator` class,
  a `moderatedBy` object property, and the `graphite` individual typed by that proposed
  `Moderator` — a mixed TBox + instance bundle; the concrete reactor→moderator *instance* edge
  is **not** hand-asserted, because `msr:MoltenSaltReactor`/`msrd:MSRE` were removed with the
  seed and are chunk-7 relation-extraction work — see design D7). Any concrete `qk:`/`unit:` IRI
  a proposal asserts MUST
  come from chunk 2's vendored QUDT allowlist (`ontology/qudt-units.json`), else the proposal
  is rejected.
- **Instance-kind candidates bypass staging**: a new specific salt/compound under
  an *existing* class is written **directly to `urn:msr:data`** flagged `msr:autoAccepted`,
  **provenance-complete** (`prov:wasGeneratedBy msrd:activity-mine` + `prov:wasDerivedFrom` its
  source `msr:Document`, per the merged `provenance-model` contract), never staged — *unless* it
  depends on proposed schema (e.g. `graphite` needs the proposed `Moderator` class), in which
  case it rides inside that proposal's bundle and reaches `urn:msr:data` only on approval.
- **Born provenance-complete (the merged trust contract)**: `mine` is a pipeline under
  `provenance-model`, so it types the stable `msrd:activity-mine` once in `urn:msr:data` and
  appends a per-run `prov:Activity` node (`urn:msr:run:mine/<ts>`) plus one `prov:wasGeneratedBy`
  generation edge per asserted fact into the append-only `urn:msr:provenance` graph — the
  two-activity pattern the NIST loader and extraction already use. Nothing is hand-provenanced;
  every derivation root is a real document.
- **Staging invisibility**: proposals live in `urn:msr:staging` / `urn:msr:proposal/{id}`,
  so the core-dataset client (and the analysis agent) never see them — verified by test.
- **A `mine` CLI stage + `make mine` target**: a one-shot Compose run, sibling to chunk 6's
  `link`, ordered after it.

## Capabilities

### New Capabilities

- `novelty-detection`: enumerate salient candidate terms from a lexical pass over the curated
  text plus the chunk-6 salt-formula misses, exclude already-linked/already-known terms, and
  score them by document frequency over the full 637-doc OCR corpus against a salience
  threshold; attach curated-set evidence sentences with document citations and span offsets.
- `candidate-triage`: classify each surviving candidate into `property`/`class`/`instance`/
  `relation` via context signals + a DeepSeek V4 Flash classifier (injected, stubbed) on the
  reused chunk-6 KG-schema prompt, and propose placement/grounding as reviewer-verifiable
  claims.
- `change-proposal-schema`: the `msr:ChangeProposal` mini-schema added to the seed ontology
  (kind, review status, term, doc frequency, evidence, proposal-graph link) and the
  `urn:msr:staging` + `urn:msr:proposal/{id}` two-graph data model — the contract chunk 9
  reads.
- `proposal-staging`: emit TBox-affecting candidates as a `ChangeProposal` resource in
  `urn:msr:staging` plus their proposed triples in `urn:msr:proposal/{id}` with deterministic
  IRIs (idempotent re-runs); validate any asserted `qk:`/`unit:` IRI against the vendored
  QUDT allowlist (reject on miss); keep proposals invisible to the core dataset.
- `instance-auto-accept`: write instance-kind candidates directly to `urn:msr:data` flagged
  `msr:autoAccepted`, provenance-complete (`prov:wasGeneratedBy` the mine activity +
  `prov:wasDerivedFrom` the source document, with per-run lineage in `urn:msr:provenance`),
  except individuals that depend on proposed schema, which ride their proposal's bundle
  (carrying the same provenance edges) instead of auto-accepting.

### Modified Capabilities

None. This change reads through the existing `core-dataset-access` contract, consumes the
chunk-6 miss artifact + KG-schema prompt builder and the chunk-2 QUDT allowlist + salt
catalog, and grows the `container-stack` `extraction` image additively — without changing
those specs' requirements.

## Impact

- **New code**: novelty-mining modules in `extraction/src/msr_extraction/` (lexical
  term-candidate pass over the curated text, chunk-6 miss reader, document-frequency scorer
  over the 637-doc corpus, triage classifier reusing `disambiguation.FlashClient`, proposal
  builder + QUDT-allowlist validator, staging/proposal-graph writer, instance auto-accept
  writer, a provenance writer (stable `msrd:activity-mine` typing in `urn:msr:data` + per-run
  activity/lineage into `urn:msr:provenance`), a `mine` CLI subcommand) plus a `pytest` suite
  under `extraction/tests/`.
- **Ontology**: `ontology/msr.ttl` gains the `msr:ChangeProposal` governance vocabulary
  (loaded into `urn:msr:ontology` by the existing `make load-seed` graph-replace `PUT`) —
  additive, self-contained, following chunk 6's mention-TBox precedent.
- **Stores**: `urn:msr:staging` gains `msr:ChangeProposal` resources; `urn:msr:proposal/{id}`
  graphs gain proposed triples; `urn:msr:data` gains `msr:autoAccepted` individuals (each with
  `prov:wasGeneratedBy`/`prov:wasDerivedFrom`) plus the stable `msrd:activity-mine` typing;
  `urn:msr:provenance` gains this run's `prov:Activity` node and one generation edge per
  auto-accepted fact (append-only). No SQLite writes (text-derived *values* are chunk 7).
- **Dependencies**: reuses the chunk-6 injected OpenAI-compatible DeepSeek client and config
  (`DEEPSEEK_BASE_URL`, `LLM_MODEL_EXTRACT`); adds a salience threshold config knob. No new
  third-party packages beyond chunk 6's.
- **Make targets**: `make mine` (one-shot Compose run) added additively to the root
  `Makefile`, ordered after `make link`.
- **Reuses (does not author)**: the chunk-6 `kg_prompt.KGSchemaPromptCache` prompt builder,
  the chunk-6 `graph_reader.GraphReader` core-dataset reader, the chunk-6
  `disambiguation.FlashClient` (`Completer`), the chunk-5 `sparql.SparqlClient` UPDATE helper,
  and the chunk-2 `ontology/qudt-units.json` allowlist.
- **Depends on**: chunk 1 (`bootstrap-graph-infra` — stores, `urn:msr:staging`, core-dataset
  contract), chunk 6 (`ner-entity-linking` — the miss artifact, the KG-schema prompt builder,
  the graph reader), and the merged **trust foundation** — `ground-demo-in-real-docs` (the
  hand-curated seed A-Box is gone; `urn:msr:data` is real-writer-only and additive) and
  `provenance-model` / `provenance-run-lineage` (the PROV-O TBox, the `msrd:activity-<pipeline>`
  two-activity pattern, and the `urn:msr:provenance` graph this stage writes into), and
  `shacl-validation` (the commit-time gate every `mine` write to `urn:msr:data` must pass — its
  `CatalogIndividualProvenanceShape` enforces exactly the provenance the auto-accepted individuals
  carry, so they are born-valid). Transitively
  relies on chunk 2's salt catalog + QUDT allowlist and chunk 5's corpus, both reached through
  chunk 6. **Downstream**: produces the staging records chunk 9's governance API serves and
  promotes.
