# Design: extract-property-relations

## Context

Chunks 1, 2, 3, 5, 4 (`grounded-analysis-agent`), and 6 (`ner-entity-linking`) are all
**merged to main and archived**; chunk 6's code lives in `extraction/` and is chunk 7's
direct upstream. Since this proposal was first drafted, the **trust quartet** also landed and
archived on main and is now authoritative for chunk 7: `ground-demo-in-real-docs` (removed the
hand-curated seed A-Box — the `example-flibe.ttl` salt/measurement duplicate, all
`skos:closeMatch`, **and the entire `msr:hasRole`/`msr:usedIn` role/reactor TBox layer**,
explicitly deferring the role/reactor layer's return to **chunk 7**), `provenance-model` (a
PROV-O slice + the requirement that **every** pipeline-asserted individual carry both
`prov:wasDerivedFrom` and `prov:wasGeneratedBy`), `provenance-run-lineage` (the shared
`urn:msr:provenance` run-lineage graph and the reusable `extraction/src/msr_extraction/provenance.py`
helper), and `shacl-validation` (RDF4J `ShaclSail` **enforcing those invariants at commit
time** on the `msr` repo, so a non-conforming write is rejected atomically — see D13). The
chunk-4 agent — now the synced `analysis-agent` main spec — is explicitly
**schema-generic** ("data added by later chunks becomes answerable with no agent code change")
and its `sql_query` reads `measurement_value` with no `source` filter, so chunk 7's
`source='document'` rows and text-derived `PropertyMeasurement` nodes are answerable through
the unchanged agent by construction. The fixed points this change builds on:

- **Chunk 2** landed the salt catalog in `urn:msr:data` (`MoltenSalt`/`Constituent`/
  `PropertyMeasurement` individuals), the `measurement_value` SQLite table, the vendored
  QUDT allowlist `ontology/qudt-units.json` (property→canonical-unit map + permitted
  `unit:`/`qk:` IRIs), and the `PropertyMeasurement` triple shape (`msr:ofSalt`,
  `msr:forProperty`, `msr:hasUnit`, `msr:equationForm`, `msr:validTempMin`/`Max`,
  `msr:dataLocator`, `prov:wasDerivedFrom`, `msr:citedIn`). NIST rows use `source='nist'`
  and locator `nist-srd27/{property}#{canonical-salt}`.
- **Chunk 6** produces, per curated document, `data/corpus/{report#}/mentions.jsonl` — one
  record per recognized span `{report, seg_index, char_start, char_end, surface_form,
status:"linked"|"novel", target_iri, target_kind, layer, score}` — and the matching
  `msr:Mention` triples in `urn:msr:data`. It also owns the reusable Python core-dataset
  **graph reader** (three-`FROM` injected, staging invisible) and the cached, version-gated
  **KG-schema prompt builder** (`kg-schema-prompt`), both explicitly built for chunks 7 and
  8 to import.
- **Chunk 5** landed `segments.jsonl` (`{report, index, text, char_start, char_end}`,
  offsets into `normalized.txt`), the curated-set list, the `Document` nodes
  (`msrd:{report#}`), and the Python `SparqlClient` (UPDATE-only) plus the `cli.py`
  subcommand dispatcher.
- **The trust quartet** (`ground-demo-in-real-docs` → `provenance-model` →
  `provenance-run-lineage` → `shacl-validation`) reshapes four of chunk 7's obligations:
  - **Generation provenance is mandatory.** The `provenance-model` main spec requires every
    pipeline-asserted individual — explicitly including `msr:PropertyMeasurement` — to carry
    **both** `prov:wasDerivedFrom` its source `prov:Entity` **and** `prov:wasGeneratedBy` a run
    `prov:Activity`, with a per-run generation edge into the append-only `urn:msr:provenance`
    graph and one stable `prov:wasGeneratedBy msrd:activity-extraction` edge in `urn:msr:data`.
    The extraction pipeline already implements this for mentions/documents via
    `provenance.py` (`write_stable_activity` / `write_activity` / `run_activity_iri`), wired
    into every `cli.py` subcommand — chunk 7 **reuses** it, it does not reinvent it (D12).
  - **`msr:citedIn` is chunk 7's to turn on.** Both the `provenance-model` and `analysis-agent`
    main specs leave `msr:citedIn` TBox-declared but **unused**, explicitly deferring the
    "measurement↔document citation edge" to **chunk-7 citation extraction** because no earlier
    writer can assert it truthfully (NIST SRD-27 carries no per-row citation). A text-derived
    measurement genuinely originates in the document its sentence came from, so chunk 7 is the
    first — and only — writer that can assert `msr:citedIn` without fabricating it; doing so
    fulfills that deferral rather than inventing a new predicate.
  - **The role/reactor OWL TBox no longer exists and chunk 7 reintroduces it.**
    `ground-demo-in-real-docs` removed `msr:SaltRole`/`FuelSalt`/`CoolantSalt`/`FlushSalt`/
    `msr:hasRole` and `msr:MoltenSaltReactor`/`msr:usedIn` from `msr.ttl`, and removed the
    `msrd:MSRE` individual with the seed A-Box, because they were populated *only* by the
    deleted seed. The role/reactor **SKOS concepts survive in `vocab.ttl`** (for NER seeding).
    Chunk 7 re-adds the OWL layer and populates it from real extraction (D9).
  - **SHACL enforces the invariants at commit time.** `shacl-validation` turned on RDF4J
    `ShaclSail` on the `msr` repo, so every chunk-7 `INSERT DATA` is validated atomically:
    `PropertyMeasurementShape` *requires* the seven properties chunk 7 emits (incl.
    `prov:wasGeneratedBy` — so D12 is now a hard runtime gate, not just spec text),
    `PropertyMeasurementUnitAllowlistShape` restricts `msr:hasUnit` to the same
    `qudt-units.json` allowlist chunk 7 maps against, and `ValidTemperatureRangeShape` forbids
    a half/inverted range. Chunk 7 conforms by construction and additionally surfaces a SHACL
    rejection legibly on the Python write path, per the spec's "Validation reports legible to
    writers" (which names extraction writers) — see D13.

This change reads the linked mentions + segment text and the graph's known entities, has
Flash extract relations from the sentences that carry linked mentions, validates every
extracted relation against the known schema, and writes text-derived measurements and
role/reactor edges into the same two stores chunk 4 already reads. It is bound by the
cross-cutting contracts in `docs/ARCHITECTURE.md` → _Runtime contracts_ and
`docs/IMPLEMENTATION_PLAN.md` → _Cross-cutting contracts_: DeepSeek V4 Flash only via an
injected client stubbed in every test; deterministic IRIs, no blank nodes, idempotent
re-runs; the SQLite runtime contract (journal `DELETE`, `busy_timeout`, no WAL sidecars);
coefficients live only in SQLite, meaning in the graph; and the `provenance-model` contract —
every asserted individual carries `prov:wasDerivedFrom` **and** `prov:wasGeneratedBy`, with
per-run lineage in `urn:msr:provenance` (D12).

## Goals / Non-Goals

**Goals:**

- Extract salt↔property↔value measurements and salt↔reactor↔role edges from curated
  sentences carrying chunk-6 linked mentions, using DeepSeek V4 Flash with the cached
  KG-schema prompt, an injected client stubbed in every test.
- Validate every extracted relation against the run's known-IRI set (salts,
  `PhysicalProperty`, `MoltenSaltReactor`, `SaltRole` individuals) and the QUDT allowlist;
  reject anything referencing an unknown IRI or unit — the LLM extracts, the app validates.
- Map extracted unit surface forms to canonical QUDT `unit:` IRIs via the chunk-2 vendored
  allowlist, and map the extracted correlation to a seed `msr:EquationForm` with
  coefficients `c0..c4` (Linear / Polynomial / Arrhenius / DiscretePoint), incl. the
  Arrhenius case `η = 0.084·exp(4340/T)`.
- Write each validated measurement to **both** stores consistently: a
  `msr:PropertyMeasurement` (with `msr:citedIn` the source `Document`) in `urn:msr:data`
  and a `measurement_value` row (`source='document'`, `doc_id` set, shared locator
  `doc/{report#}/{property}#{slug}`) in SQLite, deterministic and idempotent across both.
- Write validated `msr:hasRole` / `msr:usedIn` edges linking loaded salts to seed
  role/reactor individuals.
- Grow the chunk-4 agent's answer surface to text-derived facts with **no agent change**.

**Non-Goals:**

- **No novelty mining, salience scoring, triage, `ChangeProposal`, or staging writes** —
  chunk 8. A statement about a property _not_ in the seed schema (e.g. `solubility`) has no
  known property IRI to attach to, so chunk 7 rejects it; it re-surfaces as chunk 8's
  novelty candidate. Chunk 7 only ever writes to the **core** `urn:msr:data`.
- **No NER / linking / mention writing** — chunk 6. Chunk 7 consumes `mentions.jsonl` and
  the `msr:Mention` triples as-is; it does not re-link spans.
- **No new SQLite schema** — chunk 7 reuses the chunk-1/2 `measurement_value` table
  unchanged (the `uncertainty` column already exists). The graph-schema (TBox) changes are
  additive and confined to the seed ontology `ontology/msr.ttl`, loaded up front via
  `make load-seed` (D11, D9): (a) a small extraction-provenance vocabulary
  (`msr:extractionConfidence`, `msr:extractionRationale`; D11), and (b) the **reintroduced
  role/reactor OWL layer** that `ground-demo-in-real-docs` removed and deferred here —
  `msr:SaltRole` + the `FuelSalt`/`CoolantSalt`/`FlushSalt` individuals + `msr:hasRole`, and
  `msr:MoltenSaltReactor` + `msr:usedIn` (D9). RDF reification (`rdf:Statement`) of extracted
  role/reactor edges carries their extraction provenance. The `PropertyMeasurement` /
  `EquationForm` vocabulary and the existing PROV-O slice are unchanged. **No agent, loader, or
  SQLite-schema code change.**
- **No hand-curated data.** Chunk 7 does not resurrect the deleted seed A-Box. The reintroduced
  role/reactor layer is populated **only** from real extraction over the corpus (roles are a
  closed controlled vocabulary of *categories*, not empirical facts; reactor *individuals* are
  minted from grounded document mentions with full provenance — D9), never by hand.
- **No changes to the QUDT allowlist or the salt-canonicalization fixture** — both are
  chunk 2's; chunk 7 consumes them.
- **No Go changes** — chunk 7 is Python and writes SQLite directly (stdlib `sqlite3`) and
  the graph over HTTP; the Go loader/agent/store are untouched.
- **No agent changes** — chunk 4 is schema-generic; text-derived measurements become
  answerable purely because they land in the stores it already reads.
- **No re-derivation of the KG-schema prompt or the graph reader** — imported from chunk 6.

## Decisions

### D1 — One-shot `extract` stage; known-IRI set read from the **core dataset** at run start

The extraction package gains an `extract` subcommand (a one-shot Compose run, sibling to
chunk 5's `ingest` and chunk 6's `link`) that, per run: reads the current known schema from
the graph via chunk 6's core-dataset reader, builds the cached KG-schema prompt (chunk 6's
builder), iterates the curated documents' sentences that carry linked mentions, calls Flash,
validates, and writes both stores — and, exactly like chunk 6's `link`, generates one
`run_ts` and writes the stable + per-run provenance via the shared `provenance.py` helper
(D12). There is no long-running service; re-seeding the known-IRI set from the graph each run
is how approved evolution concepts (chunks 8→9) reach extraction, exactly as with NER.

- **Read the core dataset only.** The known-IRI set must include _approved_ concepts/salts
  but must not include pending proposals in `urn:msr:staging`/`urn:msr:proposal/{id}`.
  Chunk 7 reuses chunk 6's merged Python graph reader
  (`extraction/src/msr_extraction/graph_reader.py`, `GraphReader` — a `default-graph-uri`
  restriction to the three core graphs) rather than a new one — same enforcement, no
  duplication.
- **Extend the reader for role/property individuals (roles are a closed set; reactors are
  minted).** As merged, chunk 6's `GraphReader.read_known_entities()` exposes only
  `concept`/`class`/`salt` kinds (SKOS concepts, `owl:Class`, `PhysicalProperty` — tagged
  `class` — and `MoltenSalt` individuals). Chunk 7's validation additionally needs the set of
  the reintroduced `msr:SaltRole` individuals (`FuelSalt`/`CoolantSalt`/`FlushSalt` — a
  **closed** controlled vocabulary; D9) and must distinguish `PhysicalProperty` IRIs from
  other classes. Chunk 7 therefore adds **new reader methods** (e.g. `read_salt_roles()` and a
  property-specific accessor) rather than folding these into `read_known_entities()` — leaving
  chunk 6's NER seeding and the byte-stable KG-schema prompt prefix (built from
  `read_known_entities()` via `kg_prompt.KGSchemaPromptCache`) unchanged. **Reactors are the
  exception:** because `ground-demo-in-real-docs` removed all reactor individuals and chunk 7
  *mints* them from grounded extraction (D9), there is no closed reactor set to read or
  validate against — a reactor relation is admitted when the reactor reference is a chunk-6
  `linked` mention (to a surviving reactor `vocab.ttl` concept), and its individual is minted
  deterministically. The valid role/property IRIs also enrich the Flash context so the model
  maps to existing targets; app-side validation against these sets is the hard guarantee for
  roles and properties.
- _Alternative — a chunk-7-specific reader:_ rejected; chunk 6's reader already enforces the
  core-dataset restriction, so chunk 7 extends it additively rather than duplicating it.

### D2 — Flash relation extraction, sentence-scoped to linked mentions; the LLM extracts, the app validates

Relation extraction runs Flash over **only** sentences that carry ≥ 1 chunk-6 `linked`
mention, passing the sentence text (with its linked entities identified) on top of the
cached KG-schema prompt. The client is an **injected OpenAI-compatible interface**
(`DEEPSEEK_BASE_URL`, `LLM_MODEL_EXTRACT`, pinned to `deepseek-v4-flash`); **every test
uses a stub**. As in chunk 6's disambiguation layer, the call uses DeepSeek's JSON output
mode (`response_format={"type":"json_object"}`) — which guarantees syntactically valid JSON
but not field-level structure — so the layer **always** validates the parsed object
app-side. This is the plan's rules-vs-LLM resolution: the model proposes structured
relations, code decides what is admissible.

- **All relations in a sentence are extracted.** A single sentence can assert several
  relations (a salt's role _and_ its reactor, two properties of one salt, …); the Flash call
  returns a list of zero or more relations and each is validated (D3) and written
  independently, so a sentence packing multiple facts loses none of them.
- **Each relation carries an extraction confidence + rationale** (D11) — the model returns,
  per relation, how certain it is and why, used for a precision gate and full-trace review.
- _Why sentence-scoped to linked mentions:_ it bounds Flash calls to the curated ~12 docs'
  relevant sentences, anchors each relation on already-resolved IRIs (keeping precision
  high), and keeps novel-property sentences out of chunk 7 (they carry no linked property).
- _Alternative — a pure rules/pattern extractor:_ rejected per the plan; equation prose is
  too varied (`η = 0.084·exp(4340/T)`, "the density is 2.28 g/cm³ at 600°C", isotherm
  tables) for robust patterns, and the schema-constrained-plus-validated LLM path is the
  chosen risk trade-off.

### D3 — Validate every extracted IRI/unit against the known set; reject on a miss (reactors excepted — they are grounded + minted)

Each extracted relation is admitted only if its **closed-set** referents exist in the run's
known sets: the salt IRI is a loaded `MoltenSalt` individual, the property IRI is a seed
`msr:PhysicalProperty`, a role IRI is a seed `msr:SaltRole` (`FuelSalt`/`CoolantSalt`/
`FlushSalt`), and the unit resolves into the QUDT allowlist (D4). A relation naming anything
outside these closed sets is **rejected and never written** — for salts, properties, and
roles the model can only assert facts about known entities, never mint new ones.
Malformed/schema-violating JSON is dropped, never a silent write. Novel-property statements
(no known property IRI) fall through to chunk 8, consistent with chunk 6's "LLM-asserted,
reviewer-verified" principle.

**Reactors are the one open referent.** Because `ground-demo-in-real-docs` removed all reactor
individuals and deferred their return here, there is no closed reactor set to validate against;
instead a reactor relation is admitted only when the reactor reference is a chunk-6 `linked`
mention resolving to a surviving reactor concept in `vocab.ttl` (the grounding that keeps the
model from minting a reactor out of thin air), and chunk 7 then mints the reactor individual
deterministically with full provenance (D9). So the guarantee is uniform in spirit — nothing
is written that isn't anchored on real, already-linked corpus evidence — but its mechanism for
reactors is *grounded minting*, not closed-set rejection.

### D4 — Unit-string → QUDT mapping via the chunk-2 vendored allowlist

A dedicated mapper turns an extracted unit surface form (`cP`, `mPa·s`, `mN/m`, `g/cm³`,
`S/cm`, …) into the canonical QUDT `unit:` IRI. It is driven by the vendored
`ontology/qudt-units.json` (chunk 2 authored it as a tracked, cross-language-reusable file —
this is chunk 8's and chunk 7's reuse). The mapper (a) recognizes common surface forms per
property and (b) validates the resulting IRI against the allowlist; an unmappable surface
form or an IRI absent from the allowlist rejects the relation, mirroring chunk 2's
fail-loud unit guard. The property→canonical-unit map also lets the extractor cross-check
that an extracted unit is dimensionally consistent with the extracted property (e.g. a
`density` value quoted in `mPa·s` is rejected).

- _Why not re-vendor the allowlist:_ a second copy would drift; chunk 2's tracked file is
  the single source, read by both Go (chunk 2) and Python (chunks 7, 8).

### D5 — Equation-form + coefficient parsing into `c0..c4`

The extractor returns the correlation in a normalized structured shape (an equation-form
tag + ordered coefficients, or a single value+temperature point). Chunk 7 maps the tag to
a seed `msr:EquationForm` individual and places coefficients into `c0..c4`:

- `Linear` → `c0 + c1·T`; `Polynomial2/3` → higher terms; `Arrhenius` → `c0·exp(c1/T)`
  (e.g. `η = 0.084·exp(4340/T)` → `Arrhenius`, `c0=0.084`, `c1=4340`); `DiscretePoint` →
  a single measured value (`c0`) at a temperature (`c1`).
- The coefficient count MUST match the form (validated); a mismatch rejects the relation.
- `validTempMin`/`Max` are set from an extracted validity range when present; for a
  `DiscretePoint` both equal the single measurement temperature (mirroring chunk 2's
  isotherm handling). Coefficients live **only** in SQLite; the graph carries the form.
- **Both bounds or neither, `min ≤ max`.** The merged SHACL `ValidTemperatureRangeShape`
  (D13) rejects a half-populated or inverted range. Chunk 7 therefore writes `validTempMin`
  **and** `validTempMax` together or omits both — never just one — and orders them; a prose
  correlation with no stated validity range writes neither bound (allowed), and a lone stated
  bound is discarded (a half-range would fail validation at commit).

### D6 — Deterministic dual-store write, one shared locator

A validated measurement writes to both stores keyed by one deterministic locator
`doc/{report#}/{property}#{slug}`, where `{slug}` is the canonical salt form (matching the
NIST scheme `nist-srd27/{property}#{canonical-salt}`, but namespaced under `doc/{report#}`
so a text value never collides with a NIST row). The measurement IRI is minted
deterministically by slugging that locator (`msrd:m-doc-{report#}-{property}-{slug}`, `/`
and `#` and `|` → `-`), no blank nodes — so re-asserting is a set-semantics no-op. The
graph node carries `msr:ofSalt` (the loaded salt individual the mention resolved to),
`msr:forProperty`, `msr:hasUnit`, `msr:equationForm`, `msr:validTempMin`/`Max`,
`msr:dataLocator` (the shared locator), `prov:wasDerivedFrom` the source `Document`,
**`prov:wasGeneratedBy msrd:activity-extraction`** (the stable per-pipeline activity, from
`provenance.py`; D12), and **`msr:citedIn`** that `Document`; the SQLite row carries
`source='document'`, `doc_id` =
report#, the canonical `salt`, `property`, `equation_form`, `t_min`/`t_max`, `uncertainty`,
and `c0..c4`. The triple write is additive `INSERT DATA` via chunk 5's `SparqlClient`; the
SQLite write upserts on the `locator` primary key. The measurement's per-run generation edge
(`<measurement> prov:wasGeneratedBy <urn:msr:run:extraction/{run_ts}>`) is written to
`urn:msr:provenance`, not `urn:msr:data` (D12).

- _Salt must be a composed individual._ A measurement needs `msr:ofSalt` a specific loaded
  `MoltenSalt`. Chunk 6's normalizer resolves a bare formula (no composition) to the salt
  _concept_, not a composed individual — such a mention cannot anchor a composed
  measurement, so chunk 7 skips it (precision-biased; recorded in the run summary), rather
  than guessing a composition.

### D7 — Python SQLite writer honoring the runtime contract (not the Go helper)

The plan fixes chunk 7's SQLite writes as **Python stdlib `sqlite3`**. The chunk-1
`measurement-store` spec's connection helper is Go (`internal/store`) and unusable across
the language boundary, so chunk 7 adds a small Python connection helper that enforces the
same _runtime contract_: `PRAGMA journal_mode=DELETE` and a non-zero `busy_timeout` on
every connection, so no `-wal`/`-shm` sidecar is ever created next to the DB (WAL would
break the sandboxes' read-only directory mounts). This deliberately mirrors chunk 6's
precedent — replicating the Go core-dataset contract in a Python reader rather than sharing
the Go client — because it is pure, testable contract work and the language boundary keeps
Python self-contained. A test asserts no WAL sidecars appear after a write.

- _Why not shell out to the Go loader:_ rejected — it blurs the language boundary for a
  three-line pragma helper, and the extraction container is Python-only.

### D8 — Idempotency across both stores

Re-running `extract` MUST leave both stores' `urn:msr:data`/`measurement_value` content
unchanged: graph triples re-assert as a no-op via deterministic IRIs and no blank nodes (RDF
set semantics over additive `INSERT DATA`), and SQLite rows upsert on the `locator` primary
key (`INSERT … ON CONFLICT(locator) DO UPDATE`), so a second run neither duplicates a
measurement nor changes a row count. This is tested on both stores. The **`urn:msr:provenance`
audit graph is the one intentional exception** (D12, inherited from `provenance-run-lineage`):
each wall-clock run appends a fresh per-run `prov:Activity` node and one generation edge per
asserted fact, so it grows across runs by design — `urn:msr:data` and `measurement_value`
stay byte-stable.

### D9 — Salt role / reactor edges — chunk 7 reintroduces the removed TBox and populates it from real text

`ground-demo-in-real-docs` removed the `msr:hasRole`/`msr:usedIn` OWL layer from `msr.ttl`
(`msr:SaltRole` + `FuelSalt`/`CoolantSalt`/`FlushSalt` + `msr:hasRole`; `msr:MoltenSaltReactor`
+ `msr:usedIn`) and the `msrd:MSRE` individual with the seed A-Box, because they were populated
*only* by the deleted seed, and **deferred their return to chunk 7**. Chunk 7 therefore does two
things ground-demo could not: it re-adds that TBox, and it populates it from real extraction.

- **Reintroduce the TBox (additive, on the seed ontology).** Chunk 7 adds back to
  `ontology/msr.ttl`, loaded up front by `make load-seed` into `urn:msr:ontology` (exactly like
  the extraction-provenance TBox, D11): the `msr:SaltRole` class with its three closed
  controlled-vocabulary individuals `msr:FuelSalt`/`msr:CoolantSalt`/`msr:FlushSalt`, the
  `msr:hasRole` object property (domain `msr:MoltenSalt`, range `msr:SaltRole`), the
  `msr:MoltenSaltReactor` class, and the `msr:usedIn` object property (domain `msr:MoltenSalt`,
  range `msr:MoltenSaltReactor`). The roles are *categories*, not empirical facts, so they are
  legitimate seed TBox individuals; reactor *individuals* are **not** seeded (see below).

- **Roles: closed-set validated (`msr:hasRole`).** A validated salt↔role statement writes
  `msrd:{salt} msr:hasRole msr:{Role}` into `urn:msr:data`, where the role is one of the three
  reintroduced `msr:SaltRole` individuals. A role naming anything else is rejected (D3). This is
  a plain edge on existing individuals — no new nodes, no blank nodes.

- **Reactors: grounded + minted (`msr:usedIn`).** Since no reactor individuals exist, chunk 7
  *mints* one when — and only when — the reactor reference in the sentence is a chunk-6 `linked`
  mention resolving to a surviving reactor concept in `vocab.ttl` (e.g. the "MSRE" span linking
  to `voc:molten-salt-reactors`/its narrower concept). The minted individual has a deterministic
  IRI (`msrd:reactor-{slug}`, e.g. `msrd:reactor-msre`), is typed `a msr:MoltenSaltReactor`,
  carries an `rdfs:label` and a link to its grounding vocab concept **via a general-purpose
  predicate, not `msr:linksTo`** (whose `rdfs:domain` is `msr:Mention`; `skos:exactMatch` or
  `rdfs:seeAlso` fits and avoids the merged `LinksToTargetKindShape`/domain concerns entirely),
  and — as a pipeline-asserted individual — carries `prov:wasDerivedFrom` the source `Document`
  and
  `prov:wasGeneratedBy msrd:activity-extraction` plus a per-run generation edge (D12), so its
  identity is fully attributed to the document it came from. The salt↔reactor edge
  `msrd:{salt} msr:usedIn msrd:reactor-{slug}` is then written. Minting is deterministic (same
  reactor → same IRI), so it is idempotent (D8); a reactor reference that is *not* a linked
  mention yields no `usedIn` relation (precision-biased, no guessing).

Re-asserting an edge or a minted reactor already present is a set-semantics no-op (deterministic
IRIs, no blank nodes). There are no hand-curated seed edges to preserve any more — ground-demo
removed them all.

- _Why mint reactors rather than seed a closed reference set:_ chosen so every reactor
  individual is traceable to the real document that mentions it (Principle 3 — only real data),
  parallel to how chunk 7 mints measurements. The trade-off is an asymmetry with roles (open
  minted set vs. closed validated set, D3); it is accepted because a reactor is a real-world
  *entity* discovered in text, whereas a role is a fixed *category*. Seeding a hand-curated
  reactor reference set was rejected as re-introducing exactly the kind of unsourced individual
  ground-demo removed.

### D11 — Per-relation extraction confidence + rationale: queryable in the graph, full trace in an artifact

Every proposed relation SHALL carry an **extraction confidence** and a short **rationale**
the model returns alongside it — the supporting span/evidence in the sentence and how certain
the extraction is. This is the _extraction's_ self-assessment, deliberately distinct from the
measurement's _physical_ `uncertainty` string (the source-stated ± on the value, which
continues to fill the `uncertainty` column / `msr:uncertainty` when the prose gives one — the
two are different things and are stored in different places).

**Queryable in the graph — both measurements and role/reactor edges.** Confidence and
rationale are persisted in `urn:msr:data` for every _written_ text-derived relation, via a
small additive extraction-provenance TBox added to the seed `ontology/msr.ttl` (loaded into
`urn:msr:ontology` by the existing `make load-seed` graph-replace `PUT`, exactly like chunk
6's mention TBox — no loader change):

```turtle
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .   # add the prefix if absent
msr:extractionConfidence a owl:DatatypeProperty ; rdfs:range xsd:decimal ;
    rdfs:comment "Extractor's 0–1 confidence in a text-derived assertion (a PropertyMeasurement or a reified role/reactor edge). Absent on loaded NIST/seed data." .
msr:extractionRationale  a owl:DatatypeProperty ; rdfs:range xsd:string ;
    rdfs:comment "Short rationale/evidence for the extraction. For review; loaded data carries none." .
```

The two properties are domain-agnostic (no `rdfs:domain`) so they attach to either shape:

- **Measurement — directly on the node:** `msrd:m-doc-… msr:extractionConfidence 0.92 ;
  msr:extractionRationale "…" .` Queryable as `?m msr:extractionConfidence ?c`. A NIST
  measurement carries neither (loaded, not extracted), so their presence also marks a
  measurement as text-derived.
- **Role/reactor edge — assert + annotate via RDF reification.** The direct edge the agent
  needs is written unchanged (`msrd:{salt} msr:hasRole msr:{Role}`), _plus_ a deterministic
  `rdf:Statement` node that reifies it and carries the provenance:

  ```turtle
  msrd:edge-{report#}-{salt}-hasRole-{role} a rdf:Statement ;
      rdf:subject msrd:{salt} ; rdf:predicate msr:hasRole ; rdf:object msr:{Role} ;
      msr:extractionConfidence 0.80 ; msr:extractionRationale "…" ; msr:citedIn msrd:{report#} ;
      prov:wasDerivedFrom msrd:{report#} ; prov:wasGeneratedBy msrd:activity-extraction .
  ```

  Edge confidence is then queryable: `?s a rdf:Statement ; rdf:predicate msr:hasRole ;
  rdf:subject ?salt ; rdf:object ?role ; msr:extractionConfidence ?c`. The reification node is
  itself a pipeline-asserted individual, so it carries generation provenance like any other
  (D12): `prov:wasDerivedFrom`/`prov:wasGeneratedBy msrd:activity-extraction` in `urn:msr:data`
  and a per-run generation edge in `urn:msr:provenance`. It has a deterministic IRI and no blank
  nodes, so re-asserting it is a no-op; the direct edge is untouched, so the agent's grounding is
  unaffected. (There are no hand-curated seed role/reactor edges any more — ground-demo removed
  them — so every role/reactor edge in the graph is a text-derived one carrying its
  reification.) This is provenance reification only — the salt-role _model_ stays direct edges,
  so it does **not** change the ONTOLOGY.md POC simplification (which deferred reifying the role
  _itself_ for a salt with several roles/reactors); we reify solely to annotate an extracted
  edge with its confidence.

**Full trace in an artifact (all relations, all dispositions).** Chunk 7 additionally records
**every** proposed relation — written, rejected, or skipped, measurement _and_ role/reactor —
in a per-document trace artifact `data/corpus/{report#}/relations.jsonl`, one record per
relation `{report, seg_index, char_start, char_end, relation_kind, salt_iri,
property_iri|role_iri|reactor_iri, value|equation, unit_iri, confidence, rationale,
disposition:"written"|"rejected"|"skipped", reason}`, deterministically regenerated per run
(mirroring chunk 6's `mentions.jsonl`). A configurable **confidence threshold** (a precision
knob pinned by config + tests, like chunk 6's fuzzy cutoff) drops below-threshold relations as
`skipped` rather than writing a low-confidence fact. Rejected/skipped relations live only in
the artifact — nothing is written to the graph for them.

- _Why RDF standard reification for edges:_ it annotates the exact triple, works uniformly
  for `hasRole` and `usedIn`, reuses the standard `rdf:` vocabulary (no bespoke class), and
  keeps the direct edge intact. A domain reification class or a full PROV extraction-activity
  node (model id, timestamp, evidence links) is a clean later enrichment if richer provenance
  is wanted.
- _Why datatype properties directly on the measurement (not reified):_ a measurement is
  already a node, so annotating it needs no extra node/join and matches how `msr:uncertainty`
  already sits on the measurement.

### D12 — Generation provenance: reuse `provenance.py`, do not reinvent it

The `provenance-model` main spec requires **every** pipeline-asserted individual to carry
generation provenance, and `provenance-run-lineage` already gave the extraction pipeline the
machinery for it — `extraction/src/msr_extraction/provenance.py`, wired into `cli.py`'s
`ingest`/`link` subcommands. Chunk 7's `extract` subcommand reuses that helper unchanged; it
does not add a second provenance model. Concretely, per `extract` run:

- **One `run_ts`** is minted once (`provenance.run_timestamp()`) and threaded through the run,
  so every fact from the run shares one per-run activity node.
- **The stable per-pipeline activity** is typed once via `provenance.write_stable_activity()`
  — `msrd:activity-extraction a prov:Activity ; prov:wasAssociatedWith <agent:extraction@…> ;
  owl:versionInfo …` in `urn:msr:data`, timestamp-free so it re-asserts as a no-op.
- **The per-run activity node** `<urn:msr:run:extraction/{run_ts}>` is written via
  `provenance.write_activity(run_ts, client)` into `urn:msr:provenance` **before** any fact, so
  a mid-run crash never leaves a dangling generation edge.
- **Every text-derived individual chunk 7 asserts** — each `msr:PropertyMeasurement`, each
  minted `msr:MoltenSaltReactor`, and each `rdf:Statement` reification node — carries a stable
  `prov:wasGeneratedBy msrd:activity-extraction` edge in `urn:msr:data` (alongside its
  `prov:wasDerivedFrom` source `Document`), **and** one `<individual> prov:wasGeneratedBy
  <urn:msr:run:extraction/{run_ts}>` per-run generation edge in `urn:msr:provenance`. The
  salt↔role/reactor *direct edges* connect already-provenanced individuals (the loaded salt,
  the seed role, the minted-and-provenanced reactor), so the edge itself needs no new
  provenance node; its extraction provenance rides its `rdf:Statement` reification (D11).
- Because `provenance.py` bumps `EXTRACTION_VERSION` as the pipeline gains capabilities, adding
  the relation-extraction stage is a version bump (e.g. `0.3.0` → `0.4.0`), which also rebuilds
  the cached KG-schema prompt — consistent with the version-gated prompt cache.

This keeps chunk 7's measurements first-class provenanced facts (indistinguishable in prov
shape from mentions/documents), satisfies the merged `provenance-model` spec, and means the
future chunk-13 SHACL shapes validate chunk-7 output for free.

- _Why reuse, not extend:_ `provenance.py`'s stable/per-run split, its ordering guarantee, and
  its append-only `urn:msr:provenance` semantics are exactly what a new fact type needs; a
  chunk-7-specific provenance path would duplicate a contract already tested against
  mentions/documents.

### D13 — Chunk-7 writes must pass commit-time SHACL; the Python writer surfaces rejections

The `msr` repo now enforces SHACL at commit (`shacl-validation`, RDF4J `ShaclSail`, inference
off, per-transaction), so **every** chunk-7 `INSERT DATA` into `urn:msr:data` is validated
atomically — a violating transaction is rejected wholesale and nothing persists. Chunk 7 is
already designed to write conforming triples; the shapes make that a hard runtime guarantee
rather than a convention:

- **`PropertyMeasurementShape` requires `prov:wasDerivedFrom`, `prov:wasGeneratedBy`,
  `msr:dataLocator`, `msr:forProperty`, `msr:ofSalt`, `msr:hasUnit`, `msr:equationForm` (each
  minCount 1).** Chunk 7's measurement writer (D6) emits all seven, so it conforms — and D12's
  `prov:wasGeneratedBy` is now **required**, not merely spec-compliant: omitting it would make
  GraphDB reject the write. (`msr:citedIn` is deliberately *not* required by the shape and the
  shape puts no `sh:maxCount` on the PROV edges, so the per-run generation edge accrual is fine.)
- **`PropertyMeasurementUnitAllowlistShape` restricts `msr:hasUnit`** to the QUDT units in
  `ontology/qudt-units.json` — the *same* allowlist `unit-qudt-mapping` (D4) maps against and
  rejects misses app-side, so chunk 7's units conform by construction (defense in depth: the
  app rejects an out-of-allowlist unit; SHACL would too).
- **`ValidTemperatureRangeShape`** rejects a half-populated or inverted range, so chunk 7
  writes both bounds or neither, ordered (D5).
- **No shape targets `msr:MoltenSaltReactor` or `rdf:Statement`**, so minted reactors and
  reification nodes are unconstrained by the current catalogue; chunk 7 still gives them full
  generation provenance (D12) because the `provenance-model` spec requires it, and avoids
  `msr:linksTo` on the reactor (D9) so it never trips `LinksToTargetKindShape`.

**Surface SHACL rejections on the Python write path.** The `shacl-validation` "Validation
reports legible to writers" requirement names **extraction writers** explicitly: a caller MUST
be able to tell a validation rejection from a generic transport error. Today the Python
`sparql.py` `SparqlClient.update()` only calls `response.raise_for_status()`, raising an opaque
`HTTPStatusError`. Chunk 7 therefore adds Python-side classification — detecting a GraphDB SHACL
validation rejection (the RDF4J validation-report response) and raising a typed
`ValidationError` carrying the report, mirroring the Go loader's `ValidationError`. Because
chunk 7 pre-validates app-side, a SHACL rejection signals a chunk-7 bug (a triple that passed
app validation but violates a shape), so making it legible is a debugging guarantee, not an
expected control-flow path.

- _Scope note:_ this is a small additive change to the shared `sparql.py` (a helper chunk 6
  also uses); it strictly widens error classification and does not change the success path.

### D10 — Test strategy

Hermetic pytest, no live model and (for units) no GraphDB:

- **Relation extraction** — stubbed-Flash fixture sentences → expected validated relations
  (salt + property + value + unit, incl. the Arrhenius `η = 0.084·exp(4340/T)` case and a
  `DiscretePoint` value-at-T case); relations naming an unknown salt/property/role IRI or an
  out-of-allowlist unit are **rejected**; malformed JSON → dropped, no write.
- **Unit → QUDT mapping** — a table of surface forms → canonical `unit:` IRIs
  (`cP`→`unit:MilliPA-SEC`, `g/cm³`→`unit:GM-PER-CentiM3`, `mN/m`→`unit:MilliN-PER-M`,
  `S/cm`→`unit:S-PER-CentiM`); unmappable/out-of-allowlist surface forms rejected;
  property-vs-unit dimensional cross-check.
- **Equation-form/coefficient parsing** — each form maps to the right `msr:EquationForm`
  and `c0..c4`; coefficient-count-vs-form mismatch rejected.
- **Measurement dual-store write** — a validated measurement → the exact expected
  `INSERT DATA` triples (deterministic IRI, `msr:citedIn`, `prov:wasDerivedFrom`,
  `prov:wasGeneratedBy`, no blank nodes — the seven SHACL-required properties present) against
  a fake SPARQL client **and** the exact `measurement_value` row (`source='document'`, shared
  locator, coefficients) against a temp SQLite DB; re-run leaves both unchanged
  (idempotency); no `-wal`/`-shm` sidecar after the write.
- **Role/reactor edges** — a validated role statement → the expected `hasRole` triple to a
  reintroduced `msr:SaltRole` individual, an **unknown role rejected**; a reactor statement
  whose reference is a chunk-6 `linked` mention **mints** a deterministic
  `msr:MoltenSaltReactor` individual (with `rdfs:label`, grounding concept, and generation
  provenance) and the `usedIn` edge, while a reactor reference that is *not* a linked mention
  yields no `usedIn` relation; re-assert (edge + minted reactor) is a no-op.
- **Reintroduced role/reactor TBox** — `ontology/msr.ttl` parses (rdflib-valid) and declares
  `msr:SaltRole` + `FuelSalt`/`CoolantSalt`/`FlushSalt`, `msr:hasRole`, `msr:MoltenSaltReactor`,
  and `msr:usedIn`; the role/reactor SKOS concepts remain in `vocab.ttl`.
- **Generation provenance (D12)** — a written measurement, a minted reactor, and a reification
  node each carry `prov:wasGeneratedBy msrd:activity-extraction` (+ `prov:wasDerivedFrom`) in
  `urn:msr:data`; the `extract` run writes the per-run `prov:Activity` node and one per-fact
  generation edge into `urn:msr:provenance`; a second wall-clock run appends a new per-run
  activity + edges while `urn:msr:data`/`measurement_value` counts are unchanged (append-only
  audit graph, stable fact stores). Reuses `provenance.py` (stub the clock/`run_ts`).
- **SHACL conformance + rejection legibility (D13)** — a unit test asserts the emitted
  measurement triples carry all seven `PropertyMeasurementShape`-required properties and only
  allowlisted `msr:hasUnit` IRIs, and that a temp range is written both-bounds-or-neither
  ordered; a Python `sparql.py` test feeds a simulated GraphDB SHACL validation-report response
  and asserts `SparqlClient.update()` raises a typed `ValidationError` (with the report),
  distinct from a generic transport error. The end-to-end "a real write is *accepted* by
  SHACL" assertion lives in the guarded integration test (against a SHACL-enabled repo), not
  the hermetic suite.
- **Confidence + rationale + trace** — a written measurement carries queryable
  `msr:extractionConfidence`/`msr:extractionRationale` in the graph, and a written role/reactor
  edge is queryable via its `rdf:Statement` reification carrying the same properties (a NIST
  measurement carries neither, marking it as loaded not extracted); a written relation appears in
  `relations.jsonl` with its confidence, rationale, and `disposition:"written"`; a
  below-threshold relation is `skipped` (nothing written); a validation failure is `rejected`
  with its reason; a multi-relation sentence yields one record per relation.
- **Core-dataset read guard** — a salt/property present only in `urn:msr:staging` is not in
  the known-IRI set (inherited via chunk 6's reader; pinned by a test here too).
- **Guarded integration** (opt-in env flag, mirroring chunk 1's `GRAPHDB_REQUIRED`): against a
  **SHACL-enabled** `msr` repo, after seed + catalog + `link` + a real `extract` run over
  ORNL-TM-2316, a known FLiBe viscosity statement becomes a `PropertyMeasurement` with its
  value in `measurement_value` and `msr:citedIn msrd:ORNL-TM-2316` — its write **accepted by
  SHACL** (proving it carries the seven required properties + an allowlisted unit) — the
  chunk-4 agent (unchanged) answers a question using it, and a second `extract` run leaves both
  fact stores' counts unchanged while `urn:msr:provenance` gains a second per-run activity.
- **Manual acceptance run** — a real end-to-end `extract` over the curated docs with human
  inspection of the emitted measurements/edges (see tasks §9), so the change isn't "done"
  on green tests alone.

## Risks / Trade-offs

- **Flash hallucinates an IRI, unit, or value** → every closed-set referent (salt, property,
  role) is validated against the known-IRI set + QUDT allowlist and rejected on a miss (D3/D4);
  a reactor is admitted only when grounded on a chunk-6 `linked` mention and then minted (D9);
  the model can only assert facts anchored on real, already-linked corpus evidence; malformed
  output is dropped, never a silent write.
- **Go/Python SQLite runtime-contract drift** (a stray WAL sidecar would break the
  sandboxes' read-only mounts) → the Python writer pins `journal_mode=DELETE` +
  `busy_timeout` (D7) and a test asserts no `-wal`/`-shm` files appear next to the DB.
- **A chunk-7 write is rejected by commit-time SHACL** (an incomplete measurement, a
  half-populated temp range, an out-of-allowlist unit) → chunk 7 pre-validates every relation
  app-side so conforming triples are written by construction (D3/D4/D5), and the shapes are a
  defense-in-depth backstop, not the primary gate; the whole transaction is rejected atomically
  (no partial write), and the Python `sparql.py` surfaces the rejection as a typed
  `ValidationError` carrying the report so a mismatch is debuggable rather than an opaque 500
  (D13). Because chunk 7 writes small per-fact transactions, they stay on GraphDB's
  transactional-validation path (well under the configured limit).
- **Text value conflicts with / duplicates a NIST value for the same salt+property** →
  distinct locator namespaces (`doc/{report#}/…` vs `nist-srd27/…`) keep them separate
  rows/nodes with distinct provenance; both remain answerable and the agent can cite each.
  De-duplication of _agreeing_ text/NIST values is out of scope for the POC.
- **Extraction precision on noisy OCR** → sentence-scoped to already-linked mentions,
  schema-constrained + fully validated, over the small curated set; a low-confidence or
  ambiguous relation is dropped rather than written (precision-biased, like chunk 6).
- **Bare-formula mentions can't anchor a composed measurement** → skipped and recorded in
  the run summary (D6); the POC never guesses a composition.
- **Equation split across sentences/lines** (a correlation whose coefficients span OCR
  line breaks) → the extractor sees the segment text as chunk 5 normalized it; genuinely
  multi-sentence correlations are an accepted POC limitation (recall, not precision).
- **Reusing chunk 6's merged code** → chunk 6 is merged and archived; chunk 7 reuses
  `graph_reader.py` (`GraphReader`), `kg_prompt.py` (`KGSchemaPromptCache`/`build_prefix`),
  `sparql.py` (`SparqlClient`), `provenance.py` (`write_stable_activity`/`write_activity`/
  `run_activity_iri`; D12), and the `mentions.jsonl` artifact (`linker.MentionRecord`,
  `config.mentions_path(report)`). Chunk 7 extends `graph_reader.py` additively (new
  role/property accessors — reactors are minted, not read; D9) and imports the rest unchanged;
  the coupling is import-level and covered by tests. (This worktree has already ff-merged
  `main`, so the merged chunk-6 + trust-trilogy modules are present.)
- **Minting reactors could over-generate** (a spurious `msr:MoltenSaltReactor` from a loose
  mention) → a reactor is minted only when its reference is a chunk-6 `linked` mention resolving
  to a surviving reactor `vocab.ttl` concept (D9), so minting is bounded by the same
  linked-mention gate as everything else; a reactor reference that is not a linked mention
  produces no `usedIn` relation. The minted individual carries `prov:wasDerivedFrom` its
  document, so a bad mint is traceable and rollback-able.
- **Editing the seed `ontology/msr.ttl`** (shared with chunk 6's mention TBox + the
  `provenance-model` PROV-O slice) → chunk 7's two additions are additive and self-contained:
  the extraction-provenance vocabulary (`msr:extractionConfidence`/`msr:extractionRationale` +
  the `rdf:` prefix; D11) and the reintroduced role/reactor OWL layer (`msr:SaltRole` + three
  role individuals + `msr:hasRole`; `msr:MoltenSaltReactor` + `msr:usedIn`; D9). Both load via
  the existing `PUT` on `urn:msr:ontology`, with no loader change; adding to `msr.ttl` bumps
  `owl:versionInfo`, rebuilding the cached KG-schema prompt.
- **`make load-seed` no longer touches `urn:msr:data`** → `ground-demo-in-real-docs` removed
  `example-flibe.ttl`; `loader seed` now PUTs only `msr.ttl` → `urn:msr:ontology` and
  `vocab.ttl` → `urn:msr:vocab` and `CREATE SILENT`s `urn:msr:staging` (`cmd/loader/seed.go`,
  `seed-graph-loading` spec). So a re-`load-seed` is **safe** for the NIST salts, mentions, and
  text-derived measurements in `urn:msr:data`; it only re-PUTs the TBox/vocab (idempotent, and
  the intended way to apply a `msr.ttl` edit). Chunk 7 still (like chunks 2/6) writes its data
  additively via `INSERT DATA` and never `PUT`s `urn:msr:data`; its TBox additions ride
  `urn:msr:ontology`. The `extract` target carries no `load-seed` prerequisite.
- **Confidence leaking into the agent's answer surface** → confidence/rationale are
  measurement-provenance properties, not property values; the schema-generic agent grounds on
  `msr:forProperty`/`msr:hasUnit`/coefficients and never treats `msr:extractionConfidence` as
  a measured quantity. Surfacing it in the trace is a chunk-10 display choice, not an agent
  behavior change.

## Migration Plan

Additive on top of chunks 2 and 6 and the trust quartet (all merged and archived). Chunk 7's
two `ontology/msr.ttl` additions — the extraction-provenance vocabulary (D11) and the
reintroduced role/reactor OWL layer (D9) — are committed **before** the bootstrap's initial
`load-seed`, so they load into `urn:msr:ontology` up front. The SHACL shape catalogue is
installed into the reserved shapes graph at stack bring-up (`make up`, via
`scripts/ensure-repo.sh`), so `make extract`'s writes are validated at commit from the first
run — chunk 7 adds **no** shape and changes **no** shape (its measurement/mention/unit
invariants are already covered by the merged catalogue; `msr:MoltenSaltReactor` and
`rdf:Statement` are intentionally unconstrained, D13). `make load-seed` now PUTs **only**
the TBox and vocab (`msr.ttl` → `urn:msr:ontology`, `vocab.ttl` → `urn:msr:vocab`) and
`CREATE SILENT`s `urn:msr:staging` — it **no longer touches `urn:msr:data`** (the seed A-Box
`example-flibe.ttl` was removed by `ground-demo-in-real-docs`). The canonical fresh bootstrap
is `make up` → `make load-nist` (runs `load-seed` then the NIST load) → `make ingest` →
`make link` → `make extract` → `make test`. A **re-`load-seed` is safe** for loaded data now:
it re-PUTs the TBox/vocab idempotently and leaves `urn:msr:data` (NIST salts, mentions, and
chunk-7 measurements/reifications/minted reactors) intact — indeed re-running `load-seed` is
the intended way to apply a `msr.ttl` TBox edit to a live store. The root `Makefile` gains an
`extract` target additively (like `link:`, with **no** `load-seed` prerequisite); the
`extraction` image needs no new heavy dependency beyond the DeepSeek client chunk 6 already
added (stdlib `sqlite3` and the QUDT allowlist file are already present). Rollback: delete the
text-derived measurement triples (`DELETE WHERE { GRAPH <urn:msr:data> { ?m a
msr:PropertyMeasurement ; msr:citedIn ?d . … } }` scoped to text-derived IRIs), the role/
reactor edges + `rdf:Statement` reifications + minted `msr:MoltenSaltReactor` individuals, and
`DELETE FROM measurement_value WHERE source='document'`; the per-run provenance in
`urn:msr:provenance` is append-only audit history and may be left or truncated separately.
Everything is re-creatable from the vendored inputs, the graph, and `mentions.jsonl` by
re-running `extract`.

## Resolved Questions

- **Extraction granularity — RESOLVED: yes, multiple relations per sentence are extracted.**
  Each Flash call is scoped to a single mention-bearing sentence (with its segment context),
  but it returns a _list_ of zero or more relations and chunk 7 validates and writes each
  admissible one independently (D2), so a sentence asserting several facts loses none.
  Batching multiple sentences into one call is a later cost optimization, not a correctness
  change.
- **Slug spelling in the IRI — RESOLVED (ok).** The locator uses the canonical salt form
  with `|` (`doc/{report#}/{property}#BeF2-LiF|34.0-66.0`); the derived measurement IRI
  slugs `|` and `/`/`#` to `-`. Final spelling is settled at implementation and pinned by
  the dual-store write tests. Non-blocking.
- **Where reactor individuals come from — RESOLVED: mint from grounded extraction.**
  `ground-demo-in-real-docs` removed the `msrd:MSRE` individual (unsourced hand-curated seed)
  and deferred the role/reactor layer's return to chunk 7. Chunk 7 reintroduces the OWL TBox
  (D9) and **mints** each `msr:MoltenSaltReactor` individual from a real, chunk-6-linked reactor
  mention, with full `prov:wasDerivedFrom`/`prov:wasGeneratedBy` provenance — rather than
  seeding a hand-curated reactor reference set — so every reactor is traceable to the document
  that mentions it (Principle 3). Roles stay a closed seed controlled vocabulary. This makes the
  reactor referent an open minted set while salt/property/role stay closed validated sets (D3),
  an accepted asymmetry.
- **Generation provenance — RESOLVED: reuse `provenance.py` (D12).** The `provenance-model`
  main spec requires `prov:wasGeneratedBy` (stable + per-run) on every asserted individual;
  chunk 7 satisfies it by reusing the existing pipeline provenance helper for its measurements,
  minted reactors, and reification nodes, writing per-run lineage into `urn:msr:provenance`
  exactly as chunk 6 does for mentions/documents. No second provenance model is introduced.
- **Commit-time SHACL — RESOLVED: conform by construction + surface rejections (D13).** The
  merged `shacl-validation` `ShaclSail` validates every chunk-7 write. `PropertyMeasurementShape`
  makes the seven measurement properties (incl. `prov:wasGeneratedBy`) a hard requirement, the
  unit-allowlist shape shares chunk 7's `qudt-units.json` source, and the temp-range shape
  forbids a half/inverted range — all of which chunk 7's app-side validation already guarantees,
  so no chunk-7 write should ever be rejected in practice. Chunk 7 adds/changes no shape;
  `msr:MoltenSaltReactor` and `rdf:Statement` nodes are left unconstrained by the catalogue.
  Chunk 7 additionally classifies a SHACL rejection as a typed `ValidationError` on the Python
  write path (the spec's "legible to writers" requirement names extraction writers).
- **Uncertainty & extraction confidence — RESOLVED: capture both, in separate places,
  confidence queryable in the graph.** The source-stated _physical_ uncertainty string is
  captured into the `uncertainty` column / `msr:uncertainty` when the prose gives one (empty
  otherwise). Separately, every extracted relation carries an _extraction_ confidence +
  rationale (how certain the extraction is and why): for a written text-derived measurement
  these are **persisted queryably on the `msr:PropertyMeasurement` node**, and for a written
  role/reactor edge via an `rdf:Statement` **reification of the edge** — both using the
  additive TBox (`msr:extractionConfidence`/`msr:extractionRationale`); every proposed relation
  (incl. rejected/skipped) is also recorded in the `relations.jsonl` trace artifact; a
  configurable confidence threshold gates low-confidence relations (D11).

## Open Questions

- None outstanding.
