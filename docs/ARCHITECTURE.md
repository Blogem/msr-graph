# MSR Knowledge-Graph POC — Architecture

Status: **draft for review.** Ties together the data scope, vocabulary, and seed
ontology into a runnable pipeline. Two behaviours are the point of the POC and each gets
a concrete worked example below:

- **Self-evolving ontology** — new classes/properties detected from incoming data,
  proposed, human-reviewed, then merged. → worked example: *thermal conductivity*.
- **AI analysis grounded by graph + real data** — an LLM that understands the domain
  (graph) and computes over real values (table). → worked example in
  [ONTOLOGY.md](ONTOLOGY.md#how-the-ai-analysis-uses-it), recapped below.

## Components & data stores

| Component | Tech | Role |
|-----------|------|------|
| Structured loader | **Go** | Parse NIST CSVs, filter to fluoride subset, split salt formula+composition into constituents, load coefficients → SQLite, emit catalog triples → GraphDB — **before NER runs**, so mentions link to loaded salt individuals. |
| NER / relation extraction | **Python + spaCy + DeepSeek V4 Flash** | spaCy links known entities deterministically (EntityRuler seeded from the SKOS vocab **and the salt catalog**); Flash — grounded by the cached KG-schema prompt — disambiguates unresolved spans and extracts salt↔property↔value and salt↔reactor↔role relations. |
| Novelty miner + triage | **Python + DeepSeek V4 Flash** | Score unlinked terms; classify candidates (property / class / instance / relation) and propose ontology placement. Python *only* because it reads spaCy's `Doc`/span output directly — see language boundary. |
| Sandbox pool | **Go + Docker** | Warm pool of throwaway Python sandbox containers (channel-based) executing the analysis agent's scripts; each container is destroyed after one use and replaced fresh. |
| Analysis agent | **Go + DeepSeek V4 Pro** | Conversational: tools are SPARQL over GraphDB, read-only SQL over SQLite, and `run_python` in a sandbox. All computation in scripts, never in the model; every step streams as a trace event. |
| Web app | **Go + SvelteKit** | **Single frontend**: chat with the data (visible tool/script/provenance trace), ontology-diff review queue (approve/edit/reject), checkpoint/reset admin. |
| Graph store | **GraphDB (Docker)** | Ontology (TBox) + instances (ABox) + SKOS vocab + provenance. RDF/SPARQL. |
| Value store | **SQLite** | Numeric coefficients (NIST + text-derived), keyed by `dataLocator`. The federated numbers. Mounted **read-only** into sandboxes. |

**Language boundary.** The rule: **Python only where there's a hard ML dependency
(spaCy); Go everywhere else.** NER + novelty mining + triage are one Python service —
they share spaCy `Doc`/span objects, and re-implementing that in Go would mean
serializing spaCy internals for no gain — and it emits finished *candidate proposals* as
data. Everything downstream (structured loader, sandbox pool, web-app server, analysis
agent) is Go, because none of them touch spaCy; the LLM calls in triage and in the agent
are just HTTPS to the model and don't pull anything toward Python. Alternative seam if you want even less
Python: Python emits raw candidates + context and Go does the triage LLM step too — I'd
keep triage in Python for cohesion, but it's a clean cut either way.

## Pipeline

```
STRUCTURED                                   UNSTRUCTURED
NIST CSVs (fluoride subset)                  msr-archive OCR (~12 curated docs)
      │                                            │
      ▼                                            ▼
[Structured loader · Go]                     [spaCy NER + Flash relations]
      │                                       │                     │
      │  coefficients                  known entities         unknown terms
      ▼                                       │                     ▼
   SQLite  ◄───────────────┐                  │              [Novelty miner]
      │                    │ text-derived     │                     │
      └──► GraphDB catalog  values            │                     ▼
             (salts, PropertyMeasurement, mentions)         [Triage + LLM classifier]
                         ▲                                          │
                         │ back-populate                            ▼
                         │                                   Review queue ──► human (approve/edit/reject)
                         │                                          │
                         └──── [Apply: +ontology +vocab +EntityRuler ; version++] ◄┘

ANALYSIS:  [agent · V4 Pro] ─SPARQL─► GraphDB · ─SQL─► SQLite · ─scripts─► sandbox ⇒ traced answer
```

### Stages

0. **Acquisition** — NIST CSVs; msr-archive OCR sidecars for the ~12 curated docs
   (per [DATA_SCOPE.md](DATA_SCOPE.md)). IAEA safety docs are the stretch source.
1. **Structured ingest** — filter to fluoride rows; coefficients → SQLite; catalog
   triples (`MoltenSalt`, `Constituent`, `PropertyMeasurement` with `dataLocator`) →
   GraphDB. No numbers in the graph.
2. **Unstructured ingest + NER** — runs **after stage 1**, so the salt catalog is already
   in the graph. spaCy `EntityRuler`/`PhraseMatcher` seeded from the vocab (prefLabels +
   altLabels + chemical formulas) **and the loaded salt catalog** links *known* entities —
   including salt mentions → the loaded `MoltenSalt` individuals — with high precision; a
   statistical/noun-chunk pass surfaces *unknown* terms. DeepSeek V4 Flash (cached
   KG-schema prompt) extracts salt↔property↔value and salt↔reactor↔role relations and
   disambiguates spans the lexical layers can't settle.
3. **Graph population** — linked entities/relations → ABox triples; text-derived property
   values → `PropertyMeasurement` (source = document) with the value stored in SQLite
   *alongside the NIST coefficients* (a `source` column distinguishes them — one uniform
   federation boundary).
4. **Self-evolution loop** — see next section (the centerpiece).
5. **Analysis** — conversational: the agent (DeepSeek V4 Pro) answers over SPARQL +
   read-only SQL + sandboxed Python scripts, streaming the full trace (tool calls, data,
   scripts, provenance) to the chat UI.

### Matching & OCR robustness (how fuzzy spaCy needs to be)

The corpus is OCR'd and spans five decades, so surface forms vary ("LiF-BeF2" /
"LiF·BeF₂" / "2LiF-BeF2", "THERMAL-STRE SS", spacing/case). Fuzziness is layered and
biased toward *linking to a known concept* (a fuzzy hit should resolve to an existing
concept, not spawn a false novelty candidate — otherwise the queue floods):

1. **OCR normalization pre-pass** — de-hyphenate line breaks, collapse stray spaces,
   normalize sub/superscripts and common OCR confusions. Removes most of the fuzz cheaply.
2. **Expanded exact matching** — feed the vocab's altLabels *plus generated variants*
   (hyphen/no-hyphen, spacing, case via `attr="LOWER"`) into spaCy `PhraseMatcher`. This
   turns most "fuzziness" into many cheap exact patterns — high precision.
3. **Chemical-formula normalizer** — salts get a dedicated parser, *not* fuzzy string
   matching: parse `LiF-BeF2` into (compound, fraction) sets so `BeF2-LiF` ≡ `LiF-BeF2`
   and composition variants unify structurally. Chemistry has structure; use it.
4. **Bounded fuzzy matcher** — for the long tail, a `rapidfuzz`/`spaczz` pass with a high
   threshold (~90) and a minimum token length catches OCR-mangled multi-word terms.
5. **LLM disambiguation** — spans still unresolved after 1–4 go to DeepSeek V4 Flash with
   sentence context on top of the cached KG-schema prompt; it may only link to an
   *existing* IRI (schema-constrained JSON, validated — else rejected) or declare the span
   novel → novelty queue. (Replaces the earlier embedding-similarity stretch idea.)

Net: **high-precision linking with bounded fuzziness.** Over-fuzzy matching pollutes both
the graph and the novelty queue, so the formula normalizer + expanded exact patterns do
most of the work and true fuzzy matching is a bounded fallback.

## Self-evolution mechanism

Nothing mutates the ontology automatically — the loop *proposes*, a human *disposes*.

1. **Detect.** A term extracted by NER that matches no known concept/altLabel/class is
   parked in a novelty queue instead of being discarded.
2. **Score.** Keep candidates above a corpus-salience threshold (document frequency —
   the same measure used to build the vocabulary).
3. **Triage by contextual signal** into a proposed change kind:
   - **Property** — co-occurs with a numeric value + a recognized physical **unit**
     (its dimension identifies the quantity), or matches a QUDT `QuantityKind` / INIS
     "thermodynamic properties" descriptor → propose a new `msr:PhysicalProperty`.
   - **Class** — appears in material/'`constructed of X`' or process contexts → propose a
     new subclass under an existing class.
   - **Instance** — matches a compound-formula or named-reactor pattern → a new individual.
     **Never enters staging**: the extraction run writes it directly into `<urn:msr:data>`
     (flagged `msr:autoAccepted true`, provenance kept) since the schema is unchanged; only
     TBox changes (property/class/relation) hit the review gate. Exception: an individual
     that depends on *proposed* schema (e.g. `msrd:graphite` needs the proposed `Moderator`
     class) cannot be typed yet — it rides along inside that proposal's bundle and reaches
     `<urn:msr:data>` when the proposal is approved.
   - **Relation** — recurring subject–verb–object between known types → propose a new
     object property.
4. **Ground & package.** An LLM classifier confirms the kind and proposes placement
   (broader class, `quantityKind`, `canonicalUnit`), justified by evidence: frequency,
   example sentences with document citations, and any external match (QUDT / INIS).
5. **Review gate.** The review app (Go + SvelteKit) renders the proposal as a **visual
   diff** — the affected ontology neighborhood with the new node/edges highlighted, the
   proposed `quantityKind`/`unit`/placement as editable fields, and an evidence panel of
   source sentences with highlighted spans and document links. (The underlying triples are
   available as a raw view, but the reviewer works with the rendered diff.) Approve / edit
   / reject.
6. **Apply.** A proposal is **one bundle of nodes + edges** the reviewer approves or
   rejects as a whole — but its triples can belong to different core graphs (a new class →
   ontology; its SKOS concept → vocab; individuals and their edges → data). On approval the
   apply engine therefore **routes by triple type** instead of one graph-level `ADD`:
   subjects typed `skos:Concept` (and SKOS-predicate triples) → `<urn:msr:vocab>`; TBox
   axioms (`owl:Class` / `owl:ObjectProperty` / `owl:DatatypeProperty` declarations,
   `rdfs:subClassOf`, domain/range, `msr:PhysicalProperty` individuals with their
   `quantityKind`/`canonicalUnit`) → `<urn:msr:ontology>`; everything else (individuals,
   edges between individuals) → `<urn:msr:data>`. Implemented as three filtered
   `INSERT { GRAPH <dest> … } WHERE { GRAPH <proposal> … }` copies; the proposal graph
   stays put as the audit record. Status → `approved`, the ontology version is bumped with
   a PROV record (who / when / evidence), and the spaCy `EntityRuler` gains the new pattern
   so future mentions link automatically.
7. **Back-populate.** Previously-parked mentions are re-processed into instances now that
   a target exists.

### Where candidates live — staging by named graph

Candidates are **already in GraphDB the moment they're detected** — just isolated in
named graphs so they're trivially filterable:

| Named graph | Contents | In the core dataset? |
|-------------|----------|-----------------------|
| `<urn:msr:ontology>` / `<urn:msr:data>` / `<urn:msr:vocab>` | approved TBox / ABox / SKOS | **yes** |
| `<urn:msr:proposal/{id}>` | the proposed triples for one candidate | **no** |
| `<urn:msr:staging>` | `msr:ChangeProposal` resources (status, kind, evidence, provenance, link to the proposal graph) | **no** |

Because graph membership *is* the filter, the analysis agent and every normal query run
against the **core dataset** (the three core graphs) and **never see pending candidates** —
no status-flag filtering required. One mechanism caveat: GraphDB evaluates a query with no
`FROM`/`FROM NAMED` clauses against the union of the default graph and **all named graphs**
— staging included ([documented behavior](https://graphdb.ontotext.com/documentation/11.2/query-behavior.html)).
"Core only" is therefore **not a store setting; it's a query-layer contract**: a shared Go
SPARQL client injects `FROM <urn:msr:ontology> FROM <urn:msr:data> FROM <urn:msr:vocab>`
into every core read, and everything that must not see candidates (the analysis agent above
all) goes through it. A chunk-1 acceptance test pins the exclusion. The review app queries
`<urn:msr:staging>` to list what's pending. Lifecycle:

- **detected** → proposed triples → `<urn:msr:proposal/{id}>`; a `ChangeProposal`
  (`msr:reviewStatus "pending"`) → `<urn:msr:staging>`. (TBox proposals only — instances
  are written directly to `<urn:msr:data>` by the extraction run, never staged.)
- **approve** → typed routing copies the proposal's triples into
  `<urn:msr:ontology>` / `<urn:msr:vocab>` / `<urn:msr:data>` (see *Apply* above);
  status → `approved`.
- **edit** → modify the proposal graph, then approve.
- **reject** → status → `rejected`; triples stay put (audit trail), never reach core.

This is exactly the property you asked for: everything is in the graph and queryable, but
the unreviewed material is one `FROM` clause away from being included or excluded.

### Corpus support: per-observation model, not a stored scalar

A proposal's corpus support used to be a single materialized `msr:docFrequency` integer
written onto the `msr:ChangeProposal` resource. That broke the moment a term was mined
from a *second* corpus: proposal IRIs are deterministic on `term + kind`, so re-mining
`moderator` from the safety corpus after it already had a chemistry-corpus proposal wrote
to the same resource, and the additive writer **appended** a second `docFrequency` value
(`269, 2`) rather than replacing it — `GET /api/proposals` then emitted one row per value,
producing duplicate ids that crashed the Svelte keyed review queue. It also threw away a
genuinely useful signal: *which* documents and corpora a term was seen in, and how often.

The fix (`proposal-observation-provenance`) replaces the scalar with an append-only
per-(proposal × document × mining run) evidence model:

- **`msr:Corpus` is first-class.** `msrd:corpus-chemistry` (the msr-archive OCR corpus)
  and `msrd:corpus-safety` (the IAEA/GIF/ORNL safety corpus) are resources, and every
  `msr:Document` asserts `msr:inCorpus <corpus>` (deterministic, additive, idempotent).
- **`msr:Observation` nodes replace `msr:docFrequency`.** Each mining run appends one
  `msr:Observation` per document a candidate survives in, linked from the proposal via
  `msr:hasObservation`, carrying `msr:inDocument`, `msr:occurrenceCount` (term frequency
  *within* that document — not mere presence), `msr:inCorpus`, `msr:observedInRun` (the
  run's chunk-12 `prov:Activity`), and `prov:generatedAtTime`. Observations are
  **append-only**: a later run adds new observations rather than overwriting prior ones,
  so the full audit trail survives (mirroring the chunk-12 per-run-activity pattern); the
  current view is the *latest* observation per (proposal, document). They live in
  `urn:msr:staging` alongside the proposal — non-core, invisible to the analysis agent,
  same as the rest of the review metadata.
- **Aggregates are computed at read time, never stored.** `GET /api/proposals` and the
  proposal-detail endpoint derive `documentFrequency` (distinct documents with a latest
  observation), `totalOccurrences` (sum of latest per-document `occurrenceCount`),
  `corpusCount`, and `corpora[]` from a proposal's observations via `GROUP BY`/`SAMPLE` in
  the queue SPARQL (`cmd/server/proposals.go`). This is the root-cause fix: with nothing
  stored to duplicate, a proposal resolves to **exactly one queue row** regardless of how
  many mining runs or corpora contributed observations. The detail endpoint additionally
  returns the observation breakdown grouped by corpus → per document (document, corpus,
  latest `occurrenceCount`, first/last observed).
- **Cross-corpus breadth is a reviewer signal, not an automated one.** A term attested in
  *independent* corpora (e.g. both the chemistry and safety corpora) is materially more
  likely to be a real domain concept than a single-corpus artifact, so the queue/detail
  surfaces `corpusCount`/`corpora` to the reviewer as a visible cross-corpus badge and
  per-corpus breakdown. This breadth is **surfaced only** — it does not feed triage
  classification, auto-accept, or mining-ceiling ranking; scoring on it is a deliberate
  later decision once real cross-corpus data has been observed.
- **`msr:hasEvidence` is unaffected.** The existing sampled evidence sentences (a small
  quote sample used by the diff render) are retained unchanged alongside observations;
  observations are the complete count/provenance layer, evidence is the display quotes —
  the two are kept deliberately separate.

**Backfill migration.** Because chunk 8 (`mine-ontology-candidates`) and the safety-genre
ingest already wrote proposals with the old scalar, a one-shot backfill re-scans the two
already-cached corpora — the chemistry `archive_dir` OCR sidecars (~637 docs under
`data/corpus/msr-archive`) and the four-document safety corpus — and rebuilds observations
for the existing staged proposals, keyed on each proposal's stored `msr:term`. It reuses
the miner's exact deterministic matching (so reconstructed counts reproduce the original
`docFrequency` values), tags every scanned document with `msr:inCorpus`, and then removes
the stale `msr:docFrequency` scalars. It is **inference-free** (no DeepSeek/LLM triage
call — proposals already carry their triaged `kind`/`term`) and **re-runnable/idempotent**
(re-running does not duplicate observations). The 19 proposals that previously carried two
appended `docFrequency` values split naturally into correct per-corpus observations (e.g.
`moderator` → a chemistry observation set with `documentFrequency` ≈ 269 and a separate
safety observation set with `documentFrequency` = 2).

Run it once as a migration after upgrading to this model (checkpoint first —
`make checkpoint LABEL=before-observation-migration` — since the migration plan's rollback
path is restoring that checkpoint):

```bash
docker compose run --rm extraction backfill-observations
```

`backfill-observations` is a **top-level** `msr-extraction` subcommand (`_HANDLERS` in
`extraction/src/msr_extraction/cli.py`, alongside `mine`/`extract`/`link` — not nested
under `mine` or `safety`), implemented by `backfill_observations.run_backfill` and wired
through the thin `_cmd_backfill_observations` handler. Its idempotency doesn't rely on
naturally-idempotent SPARQL alone: every observation/tag/removal it writes is stamped with
a **fixed** run token, `BACKFILL_RUN_TS = "backfill"` (not a wall-clock timestamp), so
re-running the exact same backfill re-asserts the exact same triples — a set-semantics
no-op — rather than accumulating a new "run" each time. Re-running therefore leaves triple
counts stable, which is what "safe to re-run" means concretely here.

## Worked self-evolution example — the birth of *solubility*

Seed state: the ontology carries eight properties and the vocabulary its 29 concepts —
neither contains **solubility**. NER is running over the MSR chemistry reports.

1. **Extract & miss.** Phrases like *"…the solubility of PuF₃ in the LiF-BeF₂ solvent is
   about 2 mol % at 565 °C…"* recur. "solubility" matches no seed concept or altLabel →
   parked in the novelty queue (not dropped).
2. **Score.** Document frequency = **280 / 637** — well above threshold, never linked.
   Strong candidate.
3. **Triage → property (with a genuine judgment call).** It sits next to a value + a unit,
   so it triages as a `PhysicalProperty`, and grounds to the **INIS descriptor SOLUBILITY**
   (RT dissolution, crystallization). But its *unit is ambiguous* — the corpus expresses
   solubility as mol %, wt %, or g·L⁻¹ by context. The LLM classifier flags this rather
   than guessing; this is exactly where human review earns its place (not rubber-stamping).
4. **Package** for review: frequency, example sentences with citations, the INIS grounding,
   and the proposed triples — with the unit deliberately left as a decision.
5. **Review gate** — the SvelteKit app renders a visual diff: a new `solubility` property
   node under `PhysicalProperty`, its evidence panel, and a **unit dropdown** the reviewer
   sets to *mole fraction*. Conceptually the change is:
   ```turtle
   + msr:solubility a msr:PhysicalProperty ;
   +     rdfs:label "solubility" ;
   +     msr:quantityKind qk:AmountOfSubstanceFraction ;   # reviewer's choice: mol fraction
   +     msr:canonicalUnit unit:MOL-PER-MOL ;
   +     rdfs:comment "Added by evolution loop; 280/637 docs; unit set by reviewer." .
   + voc:solubility a skos:Concept ; skos:inScheme voc:msr-scheme ;
   +     skos:prefLabel "solubility"@en ; skos:altLabel "miscibility"@en .
   ```
   → **approve.**
6. **Apply.** The proposal bundle is promoted by **typed routing**: `msr:solubility` (a
   `PhysicalProperty` individual with its `quantityKind`/`canonicalUnit`) →
   `<urn:msr:ontology>`, the `voc:solubility` SKOS concept → `<urn:msr:vocab>`; ontology
   `0.1.0-seed → 0.2.0` with a PROV activity (`prov:wasAssociatedWith` the reviewer,
   `prov:used` the evidence); the EntityRuler gains `"solubility" → msr:solubility`.
7. **Back-populate.** Parked mentions become measurements — e.g. PuF₃ solubility in the
   LiF-BeF₂ solvent, value in SQLite (`source = document`; `{report#}` = the chemistry
   report the statement came from):
   ```turtle
   msrd:m-doc-{report#}-solubility-PuF3-in-BeF2-LiF a msr:PropertyMeasurement ;
       msr:ofSalt msrd:salt-BeF2-LiF-34.0-66.0 ; msr:forProperty msr:solubility ;
       msr:hasUnit unit:MOL-PER-MOL ; msr:equationForm msr:DiscretePoint ;
       msr:dataLocator "doc/{report#}/solubility#PuF3-in-BeF2-LiF" ; msr:citedIn msrd:ORNL-TM-2316 .
   ```

**Why this one matters:** solubility is **doubly new** — absent from *both* the structured
NIST DB and the seed vocabulary — so it's a genuine discovery, not a gap-fill. It also
forced a real human decision (which unit convention), showing the review gate contributes
judgment rather than rubber-stamping. And it gates reactor design (how much fissile the
salt can hold), so the graph grew a decision-relevant dimension purely from documents.

### Same mechanism, a new *class* + *relation* (not just a property)

The goal names classes too, and the loop generalizes. Candidate **"graphite"** (388/637
docs; "graphite-moderated" in 159) appears in a moderator context — *"the MSRE core is
moderated by graphite"*. It's outside the seed vocabulary and triages as a **class +
relation**: propose a new `msr:Moderator` class, an individual `msrd:graphite`, and a new
object property `msr:moderatedBy` (`MoltenSaltReactor → Moderator`). It grounds to INIS
`GRAPHITE` (UF "graphite moderator") and `MODERATORS`. One approved bundle, routed to two
graphs: the `Moderator` class + `moderatedBy` property → `<urn:msr:ontology>`; the
`msrd:graphite` individual + `msrd:MSRE msr:moderatedBy msrd:graphite` edge →
`<urn:msr:data>` — reaching beyond salts and properties into reactor structure. Same detect → triage → review → apply → back-populate
loop; only the *kind* of change differs.

## AI-analysis example (recap)

Detailed in [ONTOLOGY.md](ONTOLOGY.md#how-the-ai-analysis-uses-it): "density of this
LiF-BeF2 melt at 900 K?" → agent SPARQLs the graph for the measurement (Linear form,
in-range, locator), pulls `c0,c1` from SQLite, and evaluates via a generated Python script
in a sandbox: `2.413 − 4.88e-4·900 = **1.974 g·cm⁻³**` — the script itself appears in the
chat trace. Graph = method, table = numbers, sandbox = computation. After the evolution example above,
the *same* agent can now also answer solubility questions — the analysis surface grows
automatically as the ontology evolves.

## Runtime contracts (solidified)

The seams each implementation chunk builds against — decided here so OpenSpec changes
reference them instead of re-deciding.

**Run model — batch, not services.** Only two long-running processes: GraphDB (Docker) and
the web-app server (`server` — chat, review, and checkpoint APIs, the embedded frontend,
and the sandbox-pool manager). The loader, corpus ingest, NER/extraction, and the novelty
miner are one-shot container runs behind `make` targets. Two consequences: the spaCy `EntityRuler` is
**rebuilt from the graph** (vocab + approved concepts) at the start of every extraction run
— approval doesn't push a refresh signal, the next run simply sees the new concept; and
**back-population = re-run** — at ~12 docs a full re-pass is cheaper and safer than
incremental bookkeeping.

**Canonical salt naming — normalize at the boundary.** NIST's `Salt` column is not
consistent about component order and the corpus writes the same salt a dozen ways, so the
loader canonicalizes on ingest: **components alphabetized, composition values reordered in
lockstep, mole-% formatted with one decimal** (`LiF-BeF2,34.0-66.0` → `BeF2-LiF |
66.0-34.0`). The canonical form is used *everywhere* — IRI, locator, SQLite `salt` column,
`rdfs:label`. Human-friendly names ("FLiBe") come from the vocab's own SKOS labels
(`skos:prefLabel`/`skos:altLabel`), not from an alignment edge to the salt and not from raw
strings; chunk 6's formula normalizer maps mention variants to the same canonical form, so
text mentions and NIST rows meet at one IRI, and the linker's `msr:linksTo` edge (not
`skos:closeMatch`) is what connects a document mention to that salt individual — see
*Grounding via `msr:linksTo`*, below.

**Idempotent writes via deterministic IRIs.** RDF graphs are sets, so re-asserting the same
triples is a no-op — provided nothing is a blank node. Pipeline-written data therefore
mints IRIs deterministically and uses **no blank nodes**, so the loader re-asserting its
catalog (salts, constituents, measurements) on every run is a no-op:

| Thing | IRI pattern |
|-------|-------------|
| salt | `msrd:salt-{formula}-{composition}` (canonical form, e.g. `msrd:salt-BeF2-LiF-66.0-34.0`) |
| constituent | `{salt-iri}-c-{compound}` |
| measurement | `msrd:m-{locator-slug}` (slug = locator with `/ # \|` → `-`) |
| mention | `msrd:mention-{report#}-{start}-{end}` |
| proposal | `urn:msr:proposal/{kind}-{term-slug}` |

Every stage can be re-run safely; SQLite writes are `INSERT OR REPLACE` on the locator key.
Seed files (`msr.ttl`, `vocab.ttl`) are loaded with **graph-replace semantics** (SPARQL
Graph Store `PUT`) into `urn:msr:ontology`/`urn:msr:vocab` only — there is no seed A-Box, so
`urn:msr:data` is never touched by `make load-seed` and is populated exclusively by the
loader and the extraction pipeline. Editing a seed file and re-running `make load-seed`
never leaves renamed IRIs behind.

**Grounding via `msr:linksTo` (no `skos:closeMatch`).** The agent resolves a salt reference
by matching a real `msr:Mention`'s `msr:surfaceForm` and following `msr:linksTo` to the
`msr:MoltenSalt` individual, then reading its measurement; the matched Mention (with
`msr:inDocument`) is the traceable grounding evidence. A property reference resolves by
matching the query term against a `msr:PhysicalProperty`'s own `rdfs:label` — no concept
hop. `skos:closeMatch` is not used anywhere in grounding: its domain/range is
`skos:Concept`, and neither a salt individual nor a `msr:PhysicalProperty` is one, so a
`salt skos:closeMatch concept` edge would be a SKOS-range abuse. DIAMOND alignment is
unaffected by this — it uses `rdfs:seeAlso`, not `skos:closeMatch`, and stays (see
ONTOLOGY.md). Because there is no seed A-Box, this grounding data exists only after the
real pipeline has run (`make load-nist && make ingest && make link`); see README.md.

**Write paths.**

| Writer | Store | Protocol |
|--------|-------|----------|
| Go loader | SQLite (`source='nist'`) + `urn:msr:data` | `database/sql` · SPARQL 1.1 UPDATE over HTTP |
| Python extraction | mention/relation triples → `urn:msr:data`; proposals → `urn:msr:proposal/{id}` + `urn:msr:staging` | SPARQL UPDATE over HTTP |
| Python extraction | SQLite (text-derived values, `source='document'`) | stdlib `sqlite3` |
| Go apply engine | GraphDB graph ops (typed-routing promotion, status flips, version bump) | SPARQL UPDATE |
| Analysis agent | read-only | SPARQL SELECT (core dataset) · SQL SELECT · scripts via sandbox |
| Sandbox scripts | SQLite mounted **read-only** at `/data/msr.db` | stdlib `sqlite3`; no write path exists |

GraphDB's HTTP endpoint is language-neutral, so Python writing the graph directly doesn't
blur the language boundary — that rule is about ML dependencies, not store access.

**SQLite runtime.** One file, several processes, so the operational settings are pinned
here rather than left to defaults. **Journal mode `DELETE`** (never WAL — WAL requires a
writable `-shm` sidecar, which would break the sandboxes' read-only mounts) and a
`busy_timeout` on every connection. Sandboxes mount the **data directory** read-only (not
the bare file), so journal sidecars stay visible and a mid-write read can't see a torn
state. Writers are the batch jobs only (loader, extraction); the server does not write
SQLite at runtime — checkpoints copy the file via **`VACUUM INTO`** on a dedicated
connection (safe regardless of writers; see below) and restore puts the copy back while no
extraction is running.
**DDL ownership:** chunk 1 owns the init script (idempotent `CREATE TABLE IF NOT EXISTS`);
any later chunk adding a table extends that same script.

Checkpoints take the SQLite copy with **`VACUUM INTO`** on a dedicated read-write
connection opened on the live `msr.db` (never the chat path's `mode=ro&query_only`
connection, which forbids `VACUUM`) — a consistent single-file snapshot regardless of
concurrent readers, needing no C backup API (`internal/checkpoint`, design D4).

**GraphDB repository.** Single repo `msr`, **inference disabled** (no ruleset), for three
reasons. (1) *Staging isolation*: forward-chaining materializes inferred triples into the
implicit graph, not the named graph of their premises — so a pending proposal could spawn
statements outside its proposal graph, and graph membership (the entire isolation
mechanism) stops being reliable; checkpoint/restore and the idempotency/triple-count tests
also stay exact only when the store holds exactly what was written. (2) *Traceability*:
inferred triples live in no graph we control and carry no provenance (`citedIn`, DOI,
version) — an answer grounded on one breaks the provenance chain; and domain/range
inference silently repairs typing mistakes the review loop should surface instead.
(3) *Low payoff*: the shallow TBox only needs subclass/type propagation, which property
paths (`rdfs:subClassOf*`) answer explicitly. Revisit note: GraphDB fixes the ruleset at
repository creation (changing it means recreating the repo) — another reason to start
disabled and opt in later rather than the reverse.

**Integration-test repository.** `go test`'s integration tests never run against the
production `msr` repo — they target a disposable, identically-configured (SHACL-enabled,
inference-disabled) repository `msr-test`, provisioned by `make test-repo` and torn down/
recreated on every run (`scripts/ensure-repo.sh REPO_ID=msr-test REPO_RESET=1`, then
seeded via `go run ./cmd/loader seed`). `make test` depends on `make test-repo` and exports
`GRAPHDB_TEST_REPO=msr-test` for the test process to read. `scripts/ensure-repo.sh` hard-
refuses `REPO_ID=msr` combined with `REPO_RESET=1` (non-zero exit, no DELETE issued), so a
misconfigured `GRAPHDB_TEST_REPO` can never cause the reset path to drop the production
repo. `make up` is unaffected: it still calls `ensure-repo.sh` with the default
`REPO_ID=msr` and no reset.

**LLM access — DeepSeek API only.** No Anthropic models and no local LLMs anywhere in the
design (spaCy is a local *NER pipeline*, not an LLM — it stays). The endpoint is
OpenAI-compatible, so Go and Python both use OpenAI-compatible clients with the base URL
overridden. Two models, one per side of the pipeline:

- **DeepSeek V4 Flash** — extraction side: span disambiguation, relation extraction,
  novelty triage.
- **DeepSeek V4 Pro** — the conversational analysis agent.

**Prompt caching.** DeepSeek context caching is prefix-based and automatic, so the system
prompt is built as a **byte-stable prefix**: a canonical, deterministically ordered
serialization of the ontology TBox + SKOS vocab + the salt catalog (small, stable,
schema-level). It regenerates only on an ontology version bump — invalidating the cache
exactly when the schema actually changes. **Detection:** the long-running server checks
`owl:versionInfo` (one cheap SELECT) at the start of every chat request and rebuilds the
prompt when it changed — this covers both approvals and checkpoint restores with no push
signal; the batch Python jobs simply read the version at run start. **Ownership:** the Go
prompt builder lives with the agent (chunk 4), the Python one with the extraction service
(chunk 6, reused by 7 and 8) — the two need not be byte-identical to *each other*, only
stable within themselves (each side caches its own prefix). **Not the whole graph:** mentions, measurements,
and evidence stay behind tools — they grow unbounded, and the traceability requirement
wants data retrieval *visible as tool calls*, not silently baked into a prompt.

Config: `DEEPSEEK_BASE_URL`, `LLM_MODEL_EXTRACT` (Flash), `LLM_MODEL_ANALYSIS` (Pro).
Clients are injected interfaces — **tests always run against stubs, never a live model.**

**Salience vs. extraction scope.** The LFS-skip clone leaves all 637 OCR texts on disk, so
document-frequency statistics (novelty scoring, the vocabulary's evidence numbers) are
computed over the **full corpus** — a cheap text scan — while NER/relation extraction and
evidence sentences come only from the curated ~12. The worked example's "280/637" is real,
and the processing scope stays small.

**Ontology versioning.** `owl:versionInfo` on the ontology header inside
`<urn:msr:ontology>` (seed `0.1.0-seed`); each approved schema change bumps the minor version
and writes a PROV activity (reviewer, timestamp, evidence link) into `<urn:msr:staging>` —
the audit trail lives with the proposal history, outside the analysis dataset.

## Analysis execution — sandboxed Python pool

**All computation happens in throwaway sandboxes — none in the model, and none in SQLite.**
This supersedes the earlier `msr_eval`-in-SQLite decision: the agent now writes small
Python scripts and executes them via a `run_python` tool. A Go **sandbox pool** keeps N
warm containers ready:

- **Pool mechanics (Go):** a buffered channel `chan *Sandbox` *is* the pool; acquire =
  channel receive (blocks when empty). There is no release — after **one** script run the
  container is force-removed (no artifacts survive between runs) and a goroutine spawns a
  fresh replacement into the channel.
- **Container spec:** minimal Python image (stdlib + numpy/pandas pre-installed),
  `--network none`, read-only root FS + tmpfs `/tmp`, non-root user, CPU/memory/pids
  limits, wall-clock timeout; the SQLite data **directory** is bind-mounted read-only
  (DB at `/data/msr.db` — directory mount keeps journal sidecars visible, per the
  SQLite runtime contract).
- **Script contract:** script source arrives on stdin (`docker exec -i … python -`), the
  result is JSON on stdout; stderr + exit code are captured for the trace. Scripts query
  `/data/msr.db` (stdlib `sqlite3`) and compute — equation evaluation, aggregation,
  comparison — in deterministic code a reviewer can read in the trace.
- The *no-model-arithmetic* invariant survives the redesign and gets more visible: every
  computation is a script in the trace, and the agent's final numbers must match script
  output.

## Conversational analytics & traceability (key requirement)

Chatting with the data is the user-facing analysis surface, and **the trace is a
first-class deliverable** — for the POC, *how* an answer was produced matters as much as
the answer itself.

- **Chat API (Go server):** `POST /api/chat`, **stateless** — the request body carries
  the full conversation so far, OpenAI-style (`{"messages": [{"role": "user"|"assistant",
  "content": …}, …]}`); the server holds no session state and the SvelteKit app keeps the
  history in memory. The response streams **trace events** over SSE:
  `text` (assistant tokens) · `tool_call` (name + args) · `tool_result` (bindings/rows,
  truncated inline, full payload retrievable) · `script_run` (script source, stdout,
  stderr, exit code, sandbox id) · `provenance` (dataLocators, `citedIn` documents,
  dataset DOIs, ontology version used) · `done`. (Browsers' native `EventSource` can't
  POST — the frontend consumes the stream via `fetch` streaming.)
- **UI:** answer pane plus a per-turn expandable **trace timeline** — every claim links
  back to the tool step that produced it; provenance chips (NIST DOI / ORNL report)
  render inline.
- **No persistence:** traces are ephemeral per session — the demo streams live, and
  nothing needs replay afterwards. (Consequence: the server never writes SQLite.)
- Traceability also settles the prompt-vs-tools question above: data reaches the model
  through **visible tool calls**, never by stuffing instance data into the prompt.

## Checkpoints & demo rollback

Demo requirement: evolve the ontology, roll it back, do it again.

- **Checkpoint** = full GraphDB repository export (TriG, **all** named graphs incl.
  staging/proposals) + a copy of the SQLite file (via `VACUUM INTO` on a dedicated
  connection) + the ontology version, stored under `data/checkpoints/{label}/` as three
  fixed files: `store.trig` (the TriG export), `msr.db` (the SQLite snapshot), and
  `manifest.json` (`{"label", "ontology_version"}`).
- **Restore** = clear repository → import the TriG → put the SQLite copy back. Full-store
  restore is deliberately chosen over per-change undo: proposal statuses, back-populated
  instances, and text-derived rows all revert together in one atomic move — no dangling
  ABox referencing a rolled-back class.
- Exposed as API — `GET /api/checkpoints` (list), `POST /api/checkpoints` (create, JSON
  body `{"label": "..."}`), `POST /api/checkpoints/{label}/restore` — plus an admin panel
  in the web app. `{label}` is validated to a conservative filesystem-safe charset
  (alphanumerics, dash, underscore) before any path is touched, rejecting path traversal.
- `make checkpoint` / `make restore` wrap the create/restore routes against the running
  server (`SERVER_URL`, default `http://localhost:8080`, matching `cmd/server`'s
  `SERVER_ADDR` default `:8080`), taking a `LABEL` variable (default `demo`):
  `make checkpoint LABEL=before-solubility` / `make restore LABEL=before-solubility`.
- Per-change undo stays cheap if ever wanted (an approval only copies triples that still
  sit in the proposal graph, so a DELETE-where-in-proposal pattern can surgically remove
  one change from the core graphs), but checkpoints are the demo path.

## Deployment — everything in containers

The whole solution runs under Docker Compose:

| Service | Image | Notes |
|---------|-------|-------|
| `graphdb` | ontotext/graphdb | repo `msr`, data volume |
| `server` | Go binary + embedded SvelteKit build | chat + review + checkpoint APIs; mounts `/var/run/docker.sock` to manage the sandbox pool (sandboxes are **sibling** containers) |
| `extraction` | Python (spaCy + pipeline) | one-shot runs via `make extract`, not long-running |
| sandbox pool | minimal Python image | N sibling containers, lifecycle owned by `server` |

A shared volume carries the SQLite file (batch jobs write, sandboxes read-only, server
only for checkpoint/restore copies) and the corpus cache.

## Tech stack summary

- **GraphDB** (Docker) — RDF/SPARQL triple store.
- **SQLite** — federated numeric value store; mounted read-only inside sandboxes.
- **spaCy** — deterministic NER first pass; `EntityRuler` synced from the vocab + salt
  catalog + approved concepts.
- **Go** — structured loader, sandbox pool, analysis agent, web-app server.
- **SvelteKit** — the single frontend: chat + trace timeline, review queue, admin.
- **Python** — the spaCy extraction service *only*: NER, relations, novelty mining, triage.
- **LLM** — DeepSeek API (OpenAI-compatible): **V4 Flash** for extraction/triage, **V4
  Pro** for analysis; cached KG-schema system prompt; stubbed in all tests.
- **Docker Compose** — the whole solution runs in containers; sandboxes are managed
  sibling containers.

## Open questions for review

Decided:
- **Text-derived values** → stored in SQLite with a `source` column, alongside the NIST
  coefficients (one uniform federation boundary). ✓
- **Instance auto-accept** → instances never enter staging: the extraction run writes new
  specific salts/compounds/reactors directly into `<urn:msr:data>` (flagged
  `msr:autoAccepted true`, provenance kept); only *TBox* changes (new property / class /
  relation) go through the human review gate. Individuals depending on proposed schema
  ride the proposal bundle. ✓
- **Approval promotion** → typed routing: one approved bundle, triples copied to
  ontology / vocab / data by what they are (no single-graph `ADD`). ✓
- **Salt naming** → canonicalized at the loader boundary (alphabetized components,
  lockstep-reordered compositions, one-decimal mole %); canonical form used in IRIs,
  locators, SQLite, and labels; friendly names via vocab `prefLabel`/`altLabel`, and salt
  grounding via the real `msr:Mention`/`msr:linksTo` edge, not `skos:closeMatch`. ✓
- **SQLite runtime** → journal mode `DELETE`, `busy_timeout` everywhere, directory (not
  file) mounted read-only into sandboxes, backup-API checkpoints; batch jobs are the only
  writers. ✓
- **Chat API** → stateless `POST /api/chat` (client sends full message history);
  traces stream live and are not persisted. ✓
- **Review app** → Go + SvelteKit rendering visual ontology diffs. ✓
- **Language boundary** → Python only for the spaCy extraction service; Go everywhere else. ✓
- **Run model** → batch CLI stages; only GraphDB + `server` long-running; EntityRuler
  re-seeded from the graph per run; back-population = idempotent re-run. ✓
- **Core-dataset enforcement** → query-layer `FROM` injection in a shared Go SPARQL client
  (GraphDB's no-dataset default is union-of-all-graphs). ✓
- **Writes** → deterministic IRIs, no blank nodes, idempotent re-runs; Python talks to
  GraphDB/SQLite directly. ✓
- **Inference** → disabled; hierarchy queries via property paths. ✓
- **LLM** → DeepSeek API only (V4 Flash for extraction/disambiguation/triage, V4 Pro for
  analysis), OpenAI-compatible clients, cached byte-stable KG-schema prompt — no Anthropic
  models, no local LLMs; tests always run against stubs. ✓
- **Computation** → sandboxed Python pool (warm, channel-based, destroy-after-one-use);
  supersedes `msr_eval`-in-SQLite. ✓
- **Relation extraction depth** → resolved: DeepSeek V4 Flash with schema-constrained,
  validated output (was rules-vs-LLM). ✓
- **Frontend** → one SvelteKit app: chat + trace, review, admin. Traceability/explainability
  is a key requirement — the trace is a first-class deliverable. ✓
- **Rollback** → checkpoint/restore of the full store (graph + SQLite) for demo re-runs. ✓
- **Deployment** → everything in containers (Compose); `server` manages sandbox siblings
  via the Docker socket. ✓
- **NER ordering** → the salt catalog loads before NER; entity linking targets the loaded
  salt individuals, not just vocab concepts. ✓
- **Salience scope** → frequency stats over all 637 OCR texts; extraction over the curated set. ✓

Open (build-time tuning, non-blocking):
- **Novelty salience threshold** — fixed document-frequency cutoff vs. relative/tf-idf.
- **Sandbox pool sizing** — pool size (default 3) and per-container CPU/mem/timeout limits.
- **Exact DeepSeek model ids** — pin the V4 Flash/Pro identifiers at build time (config
  aliases until then).
