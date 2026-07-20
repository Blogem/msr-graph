# Design: mine-ontology-candidates

## Context

Chunks 1, 2, 3, 5 and 6 are merged to main, and so is the **trust foundation** that reshapes
this change: `ground-demo-in-real-docs` **deleted the hand-curated seed A-Box**
(`ontology/example-flibe.ttl`) and the role/reactor TBox layer, so `urn:msr:data` is now
populated *only* by real-data writers (loader + extraction) via additive `INSERT DATA`; and
`provenance-model` / `provenance-run-lineage` make **PROV-O provenance a required invariant** on
every fact-bearing individual in `urn:msr:data` (two `prov:Activity` IRIs per pipeline + an
append-only `urn:msr:provenance` graph). Chunk 1 (`bootstrap-graph-infra`) shipped the running
stores, the seed ontology/vocab (TBox + terminology only — **no A-Box**), the `internal/graph`
core-dataset client, the `urn:msr:staging` graph, and the `extraction/` Python scaffold. Chunk 6
(`ner-entity-linking`) lands the pieces this change builds on, verified against the merged code:

- the per-run mention/miss artifact `data/corpus/{report#}/mentions.jsonl`
  (`linker.write_mentions_jsonl`), one record per recognized span with fields
  `{report, seg_index, char_start, char_end, surface_form, status, target_iri, target_kind,
  layer, score}`;
- the core-dataset graph **reader** `graph_reader.GraphReader` — `read_known_entities()` →
  `list[KnownEntity(target_iri, labels, kind)]`, `known_iris()`, `read_version()` — which
  injects `default-graph-uri` for the three core graphs on every read;
- the reusable **KG-schema prompt builder** `kg_prompt.KGSchemaPromptCache` /
  `build_prefix` (byte-stable, version-gated; its docstring names chunk 8 as a consumer);
- the injected DeepSeek **Flash client** `disambiguation.FlashClient` (`Completer` protocol,
  `from_config` → `None` when `DEEPSEEK_BASE_URL` is unset) and the UPDATE-only
  `sparql.SparqlClient` (graph named inside each `INSERT DATA`).

**A verified constraint that shapes this change:** chunk 6's matcher is a rules-only
`spacy.blank("en")` pipeline (the statistical `en_core_web_sm` model was deliberately dropped,
`pyproject.toml`), so it recognizes only *seeded labels* and *salt-formula-shaped* candidate
spans. Its `status:"novel"` misses are therefore **salt-formula spans only** — a plain novel
term like `solubility` or `graphite` is never emitted as a miss (it is simply not a span in
chunk 6's world). Chunk 8 consequently cannot treat the chunk-6 miss output as its candidate
feed for property/class/relation discovery; it must enumerate those candidates itself (D1).

Chunk 6 in turn depends on chunk 2 (the salt catalog + the vendored QUDT allowlist
`ontology/qudt-units.json`, confirmed to hold the 4 NIST units only) and chunk 5 (the corpus:
the curated ~12 as `normalized.txt`/`segments.jsonl`, and the **full 637 OCR sidecars** under
`data/corpus/msr-archive/`, per `config.Config.archive_dir`). This change consumes all of the
above and adds no new third-party dependency (spaCy, `openai`, `rapidfuzz`, `httpx` are all
already in `extraction/pyproject.toml`).

This is the **detection half of the self-evolution loop** — chunk 8 _proposes_, chunk 9
_disposes_. It is bound by the cross-cutting contracts in `docs/ARCHITECTURE.md` →
_Self-evolution mechanism_ / _Where candidates live — staging by named graph_ / _Runtime
contracts_, and by `docs/IMPLEMENTATION_PLAN.md` → chunk 8. Fixed points it honours:

- **Nothing mutates the ontology automatically** — TBox changes (property / class / relation)
  become reviewable `ChangeProposal`s in staging; only a human (chunk 9) promotes them.
- **Instances never enter staging** — a new individual under an existing class is written
  directly to `urn:msr:data` flagged `msr:autoAccepted`; the one exception is an individual
  that depends on _proposed_ schema, which rides its proposal's bundle.
- **Salience over the full corpus, extraction over the curated set** — document-frequency
  stats are computed over all 637 OCR texts (a cheap scan); evidence sentences come from the
  curated ~12 (where offsets and `Document` nodes exist).
- **Staging by graph membership** — proposals sit in `urn:msr:staging` +
  `urn:msr:proposal/{id}`, one `FROM` clause away from the core dataset; no status-flag
  filtering is needed for the agent to not see them.
- **Born provenance-complete and real** — every individual this stage writes to `urn:msr:data`
  carries the `provenance-model` edges (`prov:wasGeneratedBy` the mine activity +
  `prov:wasDerivedFrom` its source `msr:Document`), with per-run lineage appended to
  `urn:msr:provenance`; no fact is hand-provenanced and every derivation root is a real document
  (Principle 3 — only real data).
- **Deterministic IRIs, no blank nodes, idempotent re-runs**; **LLM = DeepSeek V4 Flash only**,
  injected and **stubbed in every test**; the reused KG-schema prompt is byte-stable.

## Goals / Non-Goals

**Goals:**

- A `mine` one-shot stage that reads the chunk-6 miss output, excludes already-known terms,
  scores candidates by document frequency over the full 637-doc corpus against a salience
  threshold, and attaches curated-set evidence sentences (text + `msr:citedIn` + offsets).
- Triage each surviving candidate into `property`/`class`/`instance`/`relation` via context
  signals plus a DeepSeek V4 Flash classifier (injected, stubbed) on the reused chunk-6
  KG-schema prompt, with proposed placement/grounding recorded as reviewer-verifiable claims.
- The `msr:ChangeProposal` mini-schema added to the seed ontology, plus the two-graph staging
  data model — `ChangeProposal` resource → `urn:msr:staging`, proposed triples →
  `urn:msr:proposal/{id}` — as the chunk-9 contract.
- Emit TBox-affecting candidates as proposals with deterministic IRIs (idempotent); surface
  `solubility` (property) and `graphite` (class + relation bundle) correctly; validate any
  asserted `qk:`/`unit:` IRI against the vendored QUDT allowlist (reject on miss).
- Write instance-kind candidates directly to `urn:msr:data` flagged `msr:autoAccepted` and
  **provenance-complete** (`prov:wasGeneratedBy`/`prov:wasDerivedFrom` + `urn:msr:provenance`
  lineage), with the rides-with-proposal exception for individuals depending on proposed schema.
- Keep everything in staging invisible to the core dataset (pinned by test).

**Non-Goals:**

- **No approval / edit / reject, no typed routing into core, no version bump, no
  checkpoint/restore, no back-population** — all chunk 9. Chunk 8 only writes pending
  proposals + auto-accepted instances. _Deferred, not dropped:_ the split keeps detection
  (unsupervised, evidence-gathering) separately verifiable from governance (stateful,
  destructive-to-core routing); the staging records are exactly chunk 9's input.
- **No relation-extraction of salt↔property↔value measurements and no SQLite writes** —
  chunk 7. Chunk 8 mines _concepts_, not measured values; `msr:docFrequency` counts are the
  only numbers it writes, and those go to the graph, not SQLite.
- **No NER re-run and no changes to the chunk-6 linker** — chunk 8 consumes
  `mentions.jsonl` as-is; it never re-links text.
- **No external-catalog validation** — QUDT/INIS references are the classifier's _claims_
  presented as evidence; nothing dereferences the (unloaded) catalogs. The only hard check
  is the vendored QUDT-allowlist guard on concrete asserted IRIs.
- **No Go changes** — this is a Python extraction stage writing the graph directly over HTTP.
- **No new packages** — reuses chunk 6's Flash client, prompt builder, and graph reader, and
  chunk 5's SPARQL-UPDATE helper.
- **No SHACL authoring** — the write-time validation shapes are chunk 13 (`shacl-validation`).
  But because this stage writes its `urn:msr:data` individuals provenance-complete (D8), those
  facts are **born SHACL-valid**: they already satisfy chunk-13's catalog-individual provenance
  shape (`prov:wasGeneratedBy`/`prov:wasDerivedFrom` required), so chunk 8 is not retrofitted
  later — the trust design's "chunks 7–8 are born provenance-complete and SHACL-valid" goal
  (`docs/PROVENANCE_AND_TRUST_DESIGN.md` §5).

## Decisions

### D1 — A one-shot `mine` stage; candidates from a lexical term pass + the chunk-6 formula misses

The extraction package gains a `mine` subcommand (a one-shot Compose run, sibling to chunk
6's `link`), ordered after `link`. Per run it enumerates candidate terms, excludes the
already-known, scores and triages the survivors, and writes proposals + auto-accepted
instances. Candidate terms come from **two sources**, because chunk 6's blank-pipeline linker
does not surface arbitrary novel terminology (Context):

1. **A lexical term-candidate pass over the curated text** — tokenize each curated
   `normalized.txt` / `segments.jsonl` into unigram and short n-gram candidate terms
   (case-folded, stopword- and pure-number-filtered). This is where `solubility` and
   `graphite` come from; they are never in the chunk-6 miss output. A lexical pass (not a
   spaCy noun-chunker) is used deliberately — chunk 6 dropped the statistical model, and a
   document-frequency-scored lexical pass matches how the vocabulary's evidence numbers were
   derived.
2. **The chunk-6 `status:"novel"` misses** (`mentions.jsonl`) — the unresolved
   *salt-formula* spans, contributed as **instance-kind** candidates (a new compound/salt the
   loader never minted).

The miner **does not re-run the chunk-6 spaCy linker**; it reads chunk 6's artifacts and the
graph. For the **exclusion set**, a candidate that already matches a known
concept/altLabel/class/individual is not novel: the miner drops candidates that chunk 6
already linked (`status:"linked"` records / `msr:Mention` triples) *and* any that resolve into
the current **core dataset**, read via the chunk-6 `GraphReader` (which injects the three core
`FROM` graphs) so a term approved in a _prior_ evolution round — now in core — is not
re-proposed. Staging/proposal graphs are deliberately **not** read, so a still-pending proposal
from a prior run is re-emitted with the same deterministic IRI (a set-semantics no-op), never
duplicated.

- _Alternative — re-add `en_core_web_sm` for spaCy noun-chunk candidates:_ rejected for the
  POC; it re-introduces the heavy model chunk 6 dropped, and for precision-biased discovery of
  common domain terms a document-frequency-scored lexical pass is sufficient and
  deterministic.
- _Alternative — rely solely on the chunk-6 miss output:_ rejected because it is
  salt-formula-only; it would never surface `solubility`/`graphite`, the demo targets.

### D2 — Salience = document frequency over the full 637-doc corpus; evidence from the curated set

Each candidate term is scored by the number of the **637 OCR sidecars** (under
`data/corpus/msr-archive/`, chunk 5's LFS-skip clone) whose text contains it — a cheap,
case-folded substring/token scan, matching how the vocabulary's evidence numbers were derived
(the worked example's "solubility 280/637" is this measure). Candidates at or above a
configurable threshold survive; already-linked terms (D1) are excluded first. **Evidence
sentences** — the source spans shown to the reviewer — come only from the curated ~12, where
`segments.jsonl`/`normalized.txt` offsets and `Document` nodes exist; each evidence item
carries sentence text, `msr:citedIn` the report's `Document`, and start/end offsets.

- The threshold is the one build-time tuning knob (see Open Questions); it is a config value
  pinned by tests, not a magic literal. A fixed document-frequency cutoff is used for the POC;
  tf-idf/relative scoring is noted as a future option.

### D3 — Triage: context signals + a stubbed-in-tests Flash classifier on the reused KG-schema prompt

Each surviving candidate is triaged into `property` / `class` / `instance` / `relation`.
Cheap **context signals** propose a kind first (a term co-occurring with a numeric value + a
recognized physical **unit** → `property`; a compound-formula or named-reactor surface →
`instance`; a material/"constructed of X" context → `class`; the candidate co-occurring with a
known entity in a predicate-like frame, e.g. "graphite-moderated" → `relation`), then
**DeepSeek V4 Flash** confirms the kind and proposes placement (broader class, `quantityKind`,
`canonicalUnit`), grounded by evidence and any external (QUDT/INIS) match it asserts. Signals
are lexical/co-occurrence based — chunk 6's `spacy.blank` pipeline has no parser, so there is
no dependency-parse S-V-O extraction. The client is the chunk-6
`disambiguation.FlashClient` (the injected `Completer` protocol, `DEEPSEEK_BASE_URL` /
`LLM_MODEL_EXTRACT` = Flash); **every test uses a stub `Completer`**. As in chunk 6 (D5), the
call uses DeepSeek JSON output mode (`response_format={"type":"json_object"}`), which
guarantees syntactically valid JSON but **not** field-level structure, so the parsed object is
**always validated app-side** (shape check + the allowlist guard of D6); malformed or
schema-violating output drops the candidate rather than emitting a malformed proposal.

- The classifier reuses chunk 6's **KG-schema prompt builder** verbatim
  (`kg_prompt.KGSchemaPromptCache`, imported not re-derived) so triage sees the same schema
  serialization NER did; instance data (candidate term, evidence) reaches the model only as
  per-call context, keeping the prefix cache-stable.
- _Alternative — pure rules, no LLM:_ rejected for triage confirmation/placement (the plan's
  resolved rules-vs-LLM question), but rules still provide the cheap first-pass signal so the
  LLM is a confirmer, not the sole arbiter.

### D4 — The `msr:ChangeProposal` mini-schema lives in the seed ontology; two-graph staging model

The seed T-Box has no governance vocabulary, so this change adds a small, self-contained one
to **`ontology/msr.ttl`** (loaded into `urn:msr:ontology` by the existing `make load-seed`
graph-replace `PUT`), exactly as chunk 6 added its mention TBox:

```turtle
msr:ChangeProposal   a owl:Class ; rdfs:comment "A reviewable proposed ontology change (detection half of the evolution loop)." .
msr:kind             a owl:DatatypeProperty ; rdfs:domain msr:ChangeProposal ; rdfs:range xsd:string . # property|class|instance|relation — primary kind for triage/display
msr:reviewStatus     a owl:DatatypeProperty ; rdfs:domain msr:ChangeProposal ; rdfs:range xsd:string . # pending|approved|rejected
msr:term             a owl:DatatypeProperty ; rdfs:domain msr:ChangeProposal ; rdfs:range xsd:string .
msr:docFrequency     a owl:DatatypeProperty ; rdfs:domain msr:ChangeProposal ; rdfs:range xsd:integer .
msr:hasProposalGraph a owl:DatatypeProperty ; rdfs:domain msr:ChangeProposal ; rdfs:range xsd:anyURI . # → urn:msr:proposal/{id}
msr:hasEvidence      a owl:ObjectProperty ;  rdfs:domain msr:ChangeProposal ; rdfs:range msr:Evidence .
msr:Evidence         a owl:Class .
msr:evidenceText     a owl:DatatypeProperty ; rdfs:domain msr:Evidence ; rdfs:range xsd:string .
# msr:citedIn (chunk 1), msr:startOffset / msr:endOffset (chunk 6) reused for evidence provenance
msr:autoAccepted     a owl:DatatypeProperty ; rdfs:range xsd:boolean . # flags directly-written instances in urn:msr:data
# prov:wasGeneratedBy / prov:wasDerivedFrom / prov:Activity / prov:Agent reused from the provenance-model PROV-O slice (already in the seed ontology) — not re-declared here
```

- **Two graphs per proposal**: the `msr:ChangeProposal` resource (status, kind, term,
  frequency, evidence, `hasProposalGraph`) is written to **`urn:msr:staging`**; the actual
  **proposed triples** (the new class/property/concept axioms + any rides-with individuals)
  go to **`urn:msr:proposal/{id}`**. This is precisely the shape chunk 9 reads: list
  `urn:msr:staging`, render the proposal graph as a diff, route its triples on approval.
- _Why the seed ontology, not staging, for the schema?_ The `ChangeProposal` **schema** is
  pipeline-infrastructure (governance metadata), not a reviewable domain candidate — same
  reasoning chunk 6 used for `msr:Mention`. The proposal _instances_ live in staging; the
  class/predicate _definitions_ live in core ontology (harmless in the schema prompt, like
  `msr:Mention`). Exact predicate spellings are design intent, settled at implementation and
  reflected in the spec — non-blocking.

### D5 — Deterministic proposal IRIs → idempotent re-runs

The `ChangeProposal` resource is `msrd:proposal-{kind}-{term-slug}` and its proposal graph is
`urn:msr:proposal/{kind}-{term-slug}` (the ARCHITECTURE minting pattern), linked by
`msr:hasProposalGraph`; evidence nodes get deterministic IRIs derived from the report# +
offsets, no blank nodes. Because IRIs are a pure function of `(kind, term)` and evidence
location, re-running the miner over the same corpus **re-asserts identical triples** — a set
no-op — so staging/proposal-graph triple counts are unchanged on a second run.

### D6 — Grounding is LLM-asserted, reviewer-verified; QUDT-allowlist guard, and the solubility unit is left unset

The classifier's QUDT/INIS references are **claims presented as evidence** — nothing validates
them against the unloaded catalogs. The single hard check: if a proposal graph would assert a
concrete `qk:`/`unit:` IRI (e.g. the classifier confidently placed a property's
`canonicalUnit`), that IRI **MUST** be in the vendored `ontology/qudt-units.json` allowlist
(`allowedUnits` / `allowedQuantityKinds`), else the whole proposal is **rejected** (dropped
from the run, not written) — the guard that keeps a hallucinated unit out of the proposal
graph.

- **This reconciles the guard with the `solubility` demo.** The corpus expresses solubility
  as mol %, wt %, or g·L⁻¹ by context, so its unit is genuinely ambiguous (the worked
  example's human-judgment moment). The classifier is prompted to **leave an ambiguous or
  not-confidently-known unit unset** (recording the candidate units as evidence text) rather
  than guess — so the solubility proposal asserts `msr:solubility a msr:PhysicalProperty ;
rdfs:label "solubility"` with **no** `canonicalUnit`/`quantityKind` triple, and the reviewer
  sets the unit in chunk 9. With no concrete IRI asserted, the allowlist guard does not fire
  and the proposal is emitted. (`unit:MOL-PER-MOL` is not in the 4-unit NIST allowlist by
  design — the allowlist guards integrity, it does not pre-decide the reviewer's choice.)
- _Alternative — expand the allowlist to include candidate units:_ rejected; it would
  pre-decide the very unit the review gate exists to decide, and chunk 2 owns that file.

### D7 — Typed bundle: kind is primary-for-display, routing is chunk 9's; mixed bundles allowed

A proposal is **one bundle of nodes + edges**. `msr:kind` records the _primary_ kind for
triage and display, but a bundle may mix TBox and instance triples, and **approval routing
(chunk 9) ignores kind** — it routes each triple by what it _is_. Chunk 8's job is to build
the bundle correctly, not to pre-sort by destination graph.

- **`solubility`** → `kind=property`: proposal graph carries the `msr:solubility` property
  (unit unset per D6) + the `voc:solubility` SKOS concept. No instances (parked mentions
  back-populate in chunk 9).
- **`graphite`** → `kind=class`: proposal graph carries the `msr:Moderator` class, the
  `msr:moderatedBy` object property (`rdfs:range msr:Moderator`; **domain left open** — see
  below), and the `msrd:graphite` individual typed by the proposed `msr:Moderator` — a mixed
  TBox + instance bundle. The `graphite` individual depends on the proposed `Moderator` class,
  so it rides this bundle (D8) instead of auto-accepting to data, carrying the same
  `prov:wasGeneratedBy`/`prov:wasDerivedFrom` edges in the proposal graph so chunk 9 routes it
  provenance-complete on approval.
  - **Reconciled with the seed removal (`ground-demo-in-real-docs`):** `msr:MoltenSaltReactor`
    and the `msrd:MSRE` individual were removed with the hand-curated seed and are unbuilt
    chunk-7 relation-extraction work. So the bundle does **not** hand-assert `msrd:MSRE` or the
    `msrd:MSRE msr:moderatedBy msrd:graphite` instance edge — that would fabricate an individual
    the corpus attests but no writer has yet extracted, a Principle-3 violation. `moderatedBy` is
    proposed with its range only; the reviewer (chunk 9) or chunk-7 supplies the reactor domain
    and the concrete reactor→moderator edge from real text. The bundle stays a genuine mixed
    TBox + instance proposal via the `graphite` individual riding with the class.

### D8 — Instance auto-accept, with the rides-with-proposal exception

An `instance`-kind candidate — a new specific salt/compound typed by an **existing** class —
is written **directly to `urn:msr:data`** with a deterministic IRI, flagged
`msr:autoAccepted true`, and **provenance-complete** per the merged `provenance-model` contract:
each individual carries `prov:wasGeneratedBy msrd:activity-mine` and `prov:wasDerivedFrom` the
source `msr:Document` it was mined from, in `urn:msr:data`. The run also types the stable
`msrd:activity-mine a prov:Activity ; prov:wasAssociatedWith agent:mine@<version>` once (with
the ontology `owl:versionInfo`, no timestamps, idempotent) and appends a per-run `prov:Activity`
node `urn:msr:run:mine/<ts>` plus one `prov:wasGeneratedBy` generation edge per auto-accepted
fact into the append-only `urn:msr:provenance` graph — the same two-activity pattern the NIST
loader and extraction use (`cmd/loader/nist.go`). No `msr:citedIn` is asserted on the individual
(that predicate is deferred to chunk-7 citation extraction per `provenance-model`); the
document link that matters here is the `prov:wasDerivedFrom`. It never enters staging (the schema
is unchanged, so there is nothing to review). The exception: an individual that can only be typed
by **proposed** schema (`msrd:graphite` needs the proposed `msr:Moderator`) cannot be
auto-accepted — it is placed **inside that proposal's graph**, carrying the same provenance
edges, and reaches `urn:msr:data` only when chunk 9 approves the bundle. The miner decides
auto-accept-vs-ride by whether the individual's type/edges resolve entirely within the current
core schema.

**Pipeline identity:** `mine` gets its own `msrd:activity-mine` / `agent:mine@<version>` — a
distinct stage of the evolution loop, so its auto-accepted facts have clean, queryable lineage;
reusing `msrd:activity-extraction` is the alternative, rejected for lineage clarity.

### D10 — Staging invisibility via graph membership

Because proposals and auto-accept-excepted individuals live only in `urn:msr:staging` /
`urn:msr:proposal/{id}`, a read through the core-dataset contract (the three `FROM` graphs)
never returns them — no status filtering required. A test asserts a freshly-mined proposal is
absent from a core-dataset read but present in a raw staging query, mirroring chunk 1's
staging-exclusion pin.

### D11 — Test strategy

Hermetic pytest; no live model, and (for units) no GraphDB:

- **Salience scorer** — a small fixture corpus → expected document-frequency counts;
  threshold boundary (kept at/above, dropped below); already-linked terms excluded.
- **Triage** — a **stubbed Flash** returning fixed classifications → the candidate is routed
  to the right kind and the emitted proposal graph validates against the mini-schema; a
  `graphite`-shaped fixture yields the class + relation + rides-with individual bundle; a
  `solubility`-shaped fixture yields a property proposal with the unit **unset**.
- **QUDT-allowlist rejection** — a stubbed classifier asserting a concrete out-of-allowlist
  `unit:`/`qk:` IRI → the proposal is rejected (not written); an in-allowlist IRI is kept.
- **Instance auto-accept** — an instance under an existing class → a direct
  `urn:msr:data` write flagged `msr:autoAccepted`; an instance depending on proposed schema
  → it rides the proposal bundle, nothing in `urn:msr:data`.
- **Provenance on auto-accepted facts** — an auto-accepted individual carries
  `prov:wasGeneratedBy msrd:activity-mine` + `prov:wasDerivedFrom` its source `msr:Document` in
  `urn:msr:data`, the stable activity is typed once (idempotent re-run), and `urn:msr:provenance`
  holds the per-run activity node plus one generation edge per fact (append-only across two
  runs); asserted against a fake SPARQL client.
- **Proposal emission / idempotency** — a fixed candidate → the exact expected `INSERT DATA`
  triples (deterministic IRIs, no blank nodes) against a fake SPARQL client, split correctly
  across `urn:msr:staging` and `urn:msr:proposal/{id}`; a second run yields identical triples.
- **Staging invisibility** — a proposal is absent from a core-dataset read, present in a raw
  staging query.
- **Guarded integration** (opt-in env flag, mirroring chunk 1's `GRAPHDB_REQUIRED`): after
  seed + catalog + a `link` run + a real `mine` run, `solubility` and `graphite` appear as
  proposals with the correct kinds and evidence, an instance candidate is in `urn:msr:data`
  flagged `autoAccepted`, the proposals are invisible via the core client, and a second
  `mine` leaves staging/proposal triple counts unchanged.
- **Manual acceptance run** — a real end-to-end `mine` over the curated corpus with human
  inspection of the emitted proposals is an explicit task; the change is done only after it.

## Risks / Trade-offs

- **Over-eager novelty floods the queue** (every OCR-mangled span becomes a proposal) →
  candidates come only from chunk 6's _precision-biased_ miss output, are filtered by the
  known-entity exclusion set, and must clear the document-frequency threshold; the threshold
  is precision-biased and tuned against the demo targets.
- **Flash mis-triages or hallucinates a placement** → the kind is a reviewer-editable field
  and grounding is presented as _claims_, not truth; the only hard gate is the QUDT-allowlist
  guard on concrete IRIs; malformed/schema-violating output drops the candidate.
- **The allowlist guard could reject a legitimate proposal** (e.g. if the classifier asserts
  `unit:MOL-PER-MOL` for solubility) → the classifier is prompted to leave ambiguous/unknown
  units unset (D6), so the real demo target is emitted with the unit as a reviewer decision;
  the guard only ever fires on a _confidently-asserted_ out-of-allowlist IRI.
- **Instance auto-accept writes to core without review** → by design (schema unchanged, and the
  trust foundation redefines "core = SHACL-valid" — machine-derived triples may write to core if
  well-formed, `docs/PROVENANCE_AND_TRUST_DESIGN.md` §3); scoped to individuals typeable by
  existing classes, flagged `msr:autoAccepted` and provenance-complete (D8) so chunk 9's
  checkpoint/restore reverts them, and excluded when they depend on proposed schema.
- **Editing the seed `ontology/msr.ttl`** (D4) touches a foundational file → additive and
  self-contained (governance classes/predicates), loaded by the existing idempotent
  graph-replace `PUT`, no loader code change; follows chunk 6's precedent.
- **Frequency scan cost over 637 files** → a one-shot, case-folded text scan of ~97 MB;
  cheap, and it runs once per `mine`, not per candidate (build an index of doc→terms once).
- **Precision-gate flakiness from a live model** → Flash is stubbed in all unit tests and the
  demo-target assertions; the guarded integration test is opt-in.

## Migration Plan

Additive on top of chunks 1 and 6 and the merged trust foundation. Bootstrap order becomes
`make up` → `make load-seed` (now including the `ChangeProposal` governance TBox) →
`make load-nist` → `make ingest` → `make link` → `make mine` → `make test`. The
`ontology/msr.ttl` governance-TBox edit loads into `urn:msr:ontology` via `make load-seed`'s
graph-replace `PUT` **at bootstrap, before the data pipeline runs**.

- **`make load-seed` no longer touches `urn:msr:data`.** Since `ground-demo-in-real-docs`
  deleted `ontology/example-flibe.ttl`, `load-seed` loads TBox + vocab only
  (`msr.ttl` → `urn:msr:ontology`, `vocab.ttl` → `urn:msr:vocab`), and `urn:msr:data` is written
  *exclusively* by real-data writers (`loader nist`, `ingest`/`link`, and this `mine` stage) via
  additive `INSERT DATA` — never Graph Store `PUT` (`cmd/loader/seed.go`, `nist.go`). So
  re-running `load-seed` is **harmless** to the NIST catalog, the chunk-6 mentions, and chunk 8's
  `msr:autoAccepted` individuals; the old "a re-seed wipes `urn:msr:data`" hazard no longer
  exists. `load-nist` still runs `load-seed` as a prerequisite, so the governance TBox is picked
  up on the normal bootstrap chain. The demo's precondition is the full real pipeline
  (`load-nist` → `ingest` → `link` → `mine`); there is no static seed to fall back on.

Rollback: delete the mined triples — `DROP GRAPH <urn:msr:proposal/...>`,
`DELETE WHERE { GRAPH <urn:msr:staging> { ?p a msr:ChangeProposal … } }`, and `DELETE` the
`msr:autoAccepted` individuals from `urn:msr:data` — or a full `down -v` + re-bootstrap;
everything is re-creatable from the vendored inputs and the graph. The `urn:msr:provenance`
entries for the run are append-only and clear only on a full `down -v` (as with the loader),
which is acceptable for disposable POC data. Root `Makefile` gains `make mine` (after
`make link`) additively per the parallel-execution contract; the `extraction` image is unchanged
(no new packages).

## Open Questions

All resolved (2026-07-19); none blocking implementation:

- **Salience threshold** (the plan's noted _Open tuning_) — **Resolved: a fixed
  document-frequency cutoff for the POC** (relative/tf-idf scoring deferred). The cutoff is a
  config value, pinned by tests, tuned conservatively so the demo targets clear it —
  `solubility` (280/637) and `graphite` (388/637) — while staying precision-biased against
  low-frequency OCR noise. Consistent with D2.
- **Context-signal vs. LLM weighting in triage** — **Resolved: context signals propose a
  kind first, Flash confirms** (D3); the exact weighting is settled against the triage
  fixtures at implementation. Non-blocking.
- **Exact governance predicate spellings** (D4) — **Resolved: the class + predicates are the
  design intent**; final spellings are settled when `ontology/msr.ttl` is edited and reflected
  in the `change-proposal-schema` spec/tests. Non-blocking.
