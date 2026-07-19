# Design: extract-property-relations

## Context

Chunks 1, 2, 3, 5, and 4 (`grounded-analysis-agent`) are **merged to main and archived**;
chunk 6 (`ner-entity-linking`) is **merged to main** (code in `extraction/`) though its change
is not yet archived, and is chunk 7's direct upstream. The chunk-4 agent — now the synced
`analysis-agent` main spec — is explicitly **schema-generic** ("data added by later chunks
becomes answerable with no agent code change") and its `sql_query` reads `measurement_value`
with no `source` filter, so chunk 7's `source='document'` rows and text-derived
`PropertyMeasurement` nodes are answerable through the unchanged agent by construction. The
fixed points this change builds on:

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

This change reads the linked mentions + segment text and the graph's known entities, has
Flash extract relations from the sentences that carry linked mentions, validates every
extracted relation against the known schema, and writes text-derived measurements and
role/reactor edges into the same two stores chunk 4 already reads. It is bound by the
cross-cutting contracts in `docs/ARCHITECTURE.md` → _Runtime contracts_ and
`docs/IMPLEMENTATION_PLAN.md` → _Cross-cutting contracts_: DeepSeek V4 Flash only via an
injected client stubbed in every test; deterministic IRIs, no blank nodes, idempotent
re-runs; the SQLite runtime contract (journal `DELETE`, `busy_timeout`, no WAL sidecars);
coefficients live only in SQLite, meaning in the graph.

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
  unchanged (the `uncertainty` column already exists). The **only** graph-schema change is a
  small additive extraction-provenance TBox on the seed ontology (`msr:extractionConfidence`,
  `msr:extractionRationale`; D11) plus RDF reification (`rdf:Statement`) of extracted
  role/reactor edges to carry that provenance, mirroring chunk 6's additive mention TBox — the
  existing `PropertyMeasurement` / role / reactor vocabulary and the direct edges themselves
  are otherwise unchanged.
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
validates, and writes both stores. There is no long-running service; re-seeding the
known-IRI set from the graph each run is how approved evolution concepts (chunks 8→9) reach
extraction, exactly as with NER.

- **Read the core dataset only.** The known-IRI set must include _approved_ concepts/salts
  but must not include pending proposals in `urn:msr:staging`/`urn:msr:proposal/{id}`.
  Chunk 7 reuses chunk 6's merged Python graph reader
  (`extraction/src/msr_extraction/graph_reader.py`, `GraphReader` — a `default-graph-uri`
  restriction to the three core graphs) rather than a new one — same enforcement, no
  duplication.
- **Extend the reader for role/reactor/property individuals.** As merged, chunk 6's
  `GraphReader.read_known_entities()` exposes only `concept`/`class`/`salt` kinds (SKOS
  concepts, `owl:Class`, `PhysicalProperty` — tagged `class` — and `MoltenSalt` individuals).
  Chunk 7's validation additionally needs the sets of `msr:SaltRole` individuals
  (`FuelSalt`/`CoolantSalt`/`FlushSalt`) and `msr:MoltenSaltReactor` individuals (e.g.
  `msrd:MSRE`), and must distinguish `PhysicalProperty` IRIs from other classes. Chunk 7
  therefore adds **new reader methods** (e.g. `read_salt_roles()`, `read_reactors()`, and a
  property-specific accessor) rather than folding these into `read_known_entities()` — leaving
  chunk 6's NER seeding and the byte-stable KG-schema prompt prefix (built from
  `read_known_entities()` via `kg_prompt.KGSchemaPromptCache`) unchanged. The valid
  role/reactor/property IRIs also enrich the Flash context so the model maps to existing
  targets; app-side validation against these sets is the hard guarantee.
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

### D3 — Validate every extracted IRI/unit against the known set; reject on a miss

Each extracted relation is admitted only if **all** its referents exist in the run's known
sets: the salt IRI is a loaded `MoltenSalt` individual, the property IRI is a seed
`msr:PhysicalProperty`, a role IRI is a seed `msr:SaltRole`, a reactor IRI is a seed
`msr:MoltenSaltReactor`, and the unit resolves into the QUDT allowlist (D4). A relation
naming anything outside these sets is **rejected and never written** — the model can only
assert facts about known entities, never mint new ones. Malformed/schema-violating JSON is
dropped, never a silent write. Novel-property statements (no known property IRI) fall
through to chunk 8, consistent with chunk 6's "LLM-asserted, reviewer-verified" principle.

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

### D6 — Deterministic dual-store write, one shared locator

A validated measurement writes to both stores keyed by one deterministic locator
`doc/{report#}/{property}#{slug}`, where `{slug}` is the canonical salt form (matching the
NIST scheme `nist-srd27/{property}#{canonical-salt}`, but namespaced under `doc/{report#}`
so a text value never collides with a NIST row). The measurement IRI is minted
deterministically by slugging that locator (`msrd:m-doc-{report#}-{property}-{slug}`, `/`
and `#` and `|` → `-`), no blank nodes — so re-asserting is a set-semantics no-op. The
graph node carries `msr:ofSalt` (the loaded salt individual the mention resolved to),
`msr:forProperty`, `msr:hasUnit`, `msr:equationForm`, `msr:validTempMin`/`Max`,
`msr:dataLocator` (the shared locator), `prov:wasDerivedFrom` the source `Document`, and
**`msr:citedIn`** that `Document`; the SQLite row carries `source='document'`, `doc_id` =
report#, the canonical `salt`, `property`, `equation_form`, `t_min`/`t_max`, `uncertainty`,
and `c0..c4`. The triple write is additive `INSERT DATA` via chunk 5's `SparqlClient`; the
SQLite write upserts on the `locator` primary key.

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

Re-running `extract` MUST leave both stores unchanged: graph triples re-assert as a no-op
via deterministic IRIs and no blank nodes (RDF set semantics over additive `INSERT DATA`),
and SQLite rows upsert on the `locator` primary key (`INSERT … ON CONFLICT(locator) DO
UPDATE`), so a second run neither duplicates a measurement nor changes a row count. This is
tested on both stores.

### D9 — Salt role / reactor edges

Validated salt↔role and salt↔reactor statements write `msrd:{salt} msr:hasRole
msr:{Role}` and `msrd:{salt} msr:usedIn msrd:{Reactor}` into `urn:msr:data`, where the role
is a seed `msr:SaltRole` individual (`FuelSalt`/`CoolantSalt`/`FlushSalt`) and the reactor a
loaded `msr:MoltenSaltReactor` individual (e.g. `msrd:MSRE`). These are plain edges on
existing individuals — no new nodes, no blank nodes — so re-asserting an edge already
present (incl. the seed's hand-curated `hasRole`/`usedIn`) is a set-semantics no-op. A
role/reactor naming an unknown individual is rejected (D3).

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
      msr:extractionConfidence 0.80 ; msr:extractionRationale "…" ; msr:citedIn msrd:{report#} .
  ```

  Edge confidence is then queryable: `?s a rdf:Statement ; rdf:predicate msr:hasRole ;
  rdf:subject ?salt ; rdf:object ?role ; msr:extractionConfidence ?c`. The reification node
  has a deterministic IRI and no blank nodes, so re-asserting it is a no-op; the direct edge
  is untouched, so the agent's grounding is unaffected and hand-curated seed edges (which
  carry no reification) simply have no confidence. This is provenance reification only — the
  salt-role _model_ stays direct edges, so it does **not** change the ONTOLOGY.md POC
  simplification (which deferred reifying the role _itself_ for a salt with several
  roles/reactors); we reify solely to annotate an extracted edge with its confidence.

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

### D10 — Test strategy

Hermetic pytest, no live model and (for units) no GraphDB:

- **Relation extraction** — stubbed-Flash fixture sentences → expected validated relations
  (salt + property + value + unit, incl. the Arrhenius `η = 0.084·exp(4340/T)` case and a
  `DiscretePoint` value-at-T case); relations naming an unknown salt/property/reactor/role
  IRI or an out-of-allowlist unit are **rejected**; malformed JSON → dropped, no write.
- **Unit → QUDT mapping** — a table of surface forms → canonical `unit:` IRIs
  (`cP`→`unit:MilliPA-SEC`, `g/cm³`→`unit:GM-PER-CentiM3`, `mN/m`→`unit:MilliN-PER-M`,
  `S/cm`→`unit:S-PER-CentiM`); unmappable/out-of-allowlist surface forms rejected;
  property-vs-unit dimensional cross-check.
- **Equation-form/coefficient parsing** — each form maps to the right `msr:EquationForm`
  and `c0..c4`; coefficient-count-vs-form mismatch rejected.
- **Measurement dual-store write** — a validated measurement → the exact expected
  `INSERT DATA` triples (deterministic IRI, `msr:citedIn`, no blank nodes) against a fake
  SPARQL client **and** the exact `measurement_value` row (`source='document'`, shared
  locator, coefficients) against a temp SQLite DB; re-run leaves both unchanged
  (idempotency); no `-wal`/`-shm` sidecar after the write.
- **Role/reactor edges** — a validated statement → the expected `hasRole`/`usedIn` triple;
  unknown role/reactor rejected; re-assert is a no-op.
- **Confidence + rationale + trace** — a written measurement carries queryable
  `msr:extractionConfidence`/`msr:extractionRationale` in the graph, and a written role/reactor
  edge is queryable via its `rdf:Statement` reification carrying the same properties (a NIST
  measurement and a hand-curated seed edge carry neither); a written relation appears in
  `relations.jsonl` with its confidence, rationale, and `disposition:"written"`; a
  below-threshold relation is `skipped` (nothing written); a validation failure is `rejected`
  with its reason; a multi-relation sentence yields one record per relation.
- **Core-dataset read guard** — a salt/property present only in `urn:msr:staging` is not in
  the known-IRI set (inherited via chunk 6's reader; pinned by a test here too).
- **Guarded integration** (opt-in env flag, mirroring chunk 1's `GRAPHDB_REQUIRED`): after
  seed + catalog + `link` + a real `extract` run over ORNL-TM-2316, a known FLiBe viscosity
  statement becomes a `PropertyMeasurement` with its value in `measurement_value` and
  `msr:citedIn msrd:ORNL-TM-2316`, the chunk-4 agent (unchanged) answers a question using
  it, and a second `extract` run leaves both stores' counts unchanged.
- **Manual acceptance run** — a real end-to-end `extract` over the curated docs with human
  inspection of the emitted measurements/edges (see tasks §9), so the change isn't "done"
  on green tests alone.

## Risks / Trade-offs

- **Flash hallucinates an IRI, unit, or value** → every referent is validated against the
  known-IRI set + QUDT allowlist and rejected on a miss (D3/D4); the model can only assert
  facts about known entities; malformed output is dropped, never a silent write.
- **Go/Python SQLite runtime-contract drift** (a stray WAL sidecar would break the
  sandboxes' read-only mounts) → the Python writer pins `journal_mode=DELETE` +
  `busy_timeout` (D7) and a test asserts no `-wal`/`-shm` files appear next to the DB.
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
- **Reusing chunk 6's merged code** → chunk 6 is now merged to `main`; chunk 7 branches from
  it and reuses `graph_reader.py` (`GraphReader`), `kg_prompt.py`
  (`KGSchemaPromptCache`/`build_prefix`), `sparql.py` (`SparqlClient`), and the
  `mentions.jsonl` artifact (`linker.MentionRecord`, `config.mentions_path(report)`). Chunk 7
  extends `graph_reader.py` additively (new role/reactor/property accessors) and imports the
  rest unchanged; the coupling is import-level and covered by tests. (The chunk-7 worktree
  branched from an older base — it must ff-merge `main` before implementation so the merged
  chunk-6 modules are present.)
- **Editing the seed `ontology/msr.ttl`** (shared with chunk 6's mention TBox) → chunk 7
  starts after chunk 6 is merged (P4 after M3), so it adds its extraction-provenance TBox on
  top of chunk 6's; the addition is additive and self-contained (two datatype properties + the
  `rdf:` prefix), loaded by the existing `PUT` on `urn:msr:ontology`, with no loader change.
- **`make load-seed` graph-replaces `urn:msr:data`** (from `example-flibe.ttl`), so a
  re-seed after data is loaded would wipe NIST salts, mentions, and text-derived measurements
  → chunk 7 (like chunks 2/6) writes additively via `INSERT DATA` and **never** `PUT`s
  `urn:msr:data`; the `extract` target carries no `load-seed` prerequisite, and the run order
  (`load-nist` → `ingest` → `link` → `extract`) never re-seeds after data lands. The
  extraction-provenance TBox is loaded up front (it rides `urn:msr:ontology`, not
  `urn:msr:data`).
- **Confidence leaking into the agent's answer surface** → confidence/rationale are
  measurement-provenance properties, not property values; the schema-generic agent grounds on
  `msr:forProperty`/`msr:hasUnit`/coefficients and never treats `msr:extractionConfidence` as
  a measured quantity. Surfacing it in the trace is a chunk-10 display choice, not an agent
  behavior change.

## Migration Plan

Additive on top of chunks 2 and 6 (both merged to `main`). The extraction-provenance TBox
(D11) is committed to `ontology/msr.ttl` **before** the bootstrap's initial `load-seed`, so it
loads into `urn:msr:ontology` up front. Note `make load-seed` graph-**replaces** each core
graph — including `urn:msr:data` from `example-flibe.ttl` — and `make load-nist` **depends on**
`load-seed`; the canonical fresh bootstrap is therefore `make up` → `make load-nist` (runs
`load-seed` then the NIST load) → `make ingest` → `make link` → `make extract` → `make test`.
**Do not re-run `make load-seed` after data is loaded** — it would wipe `urn:msr:data` (NIST
salts, chunk-6 mentions, and chunk-7 text-derived measurements + reifications); a TBox change
is applied by editing `msr.ttl` and re-bootstrapping from `load-nist`, not by re-seeding a live
store. The root `Makefile` gains an `extract` target additively (like `link:`, with **no**
`load-seed` prerequisite); the `extraction` image needs no new heavy dependency beyond the
DeepSeek client chunk 6 already added (stdlib `sqlite3` and the QUDT allowlist file are already
present). Rollback: delete
the text-derived measurement triples (`DELETE WHERE { GRAPH <urn:msr:data> { ?m a
msr:PropertyMeasurement ; msr:citedIn ?d . … } }` scoped to text-derived IRIs) and role/
reactor edges, and `DELETE FROM measurement_value WHERE source='document'`; everything is
re-creatable from the vendored inputs, the graph, and `mentions.jsonl` by re-running
`extract`.

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
