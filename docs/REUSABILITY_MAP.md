# Reusability Map — extracting a generic KG platform from msr-graph

## Purpose

This document classifies every capability spec and code module of msr-graph as
**generic** (reusable platform), **domain** (molten-salt-reactor / chemistry-specific), or
**hybrid** (generic *pattern*, domain *content*). For each hybrid it names the exact seam —
where the reusable code and the domain content are entangled — and the *un-entangle move*
that separates them. The goal is a shopping list for a from-scratch, production-quality
rebuild in a new domain: what to lift, what to replace, and what to refactor into a plug-in.

Target rebuild constraints (from the owner): still RDF/SPARQL; **structured (numeric/tabular)
data lives in external stores reached through pluggable connectors** — not one fixed engine
(DuckDB, Postgres, Databricks, Athena, InfluxDB, … are all connector implementations); LLM via
an OpenAI-compatible API. The division of labour is: the **graph holds *where to look*** (a
locator that names a store + an address within it) and the **connector fetches the values**.
Those choices are reflected throughout (see especially §3.8, the store-connector model).

Two capabilities are treated as **first-class trust pillars**, not incidental features, because
they are what make a self-evolving, LLM-driven KG trustworthy: **provenance everywhere** (§3.5)
and **constraint validation / SHACL** (§3.13). Both must survive a change of graph engine.

## Verified at

- **Commit:** `928936e` (`928936e265f65c39130478dd14d75ba6426b9f70`), branch `main`, clean tree.
- **Date:** 2026-07-21.
- **Method:** seven read-only audit agents over the specs + Go + Python + Svelte trees, each
  grepping for domain leakage to validate (not just assert) the classification. File:line
  references below were verified at this commit.

See §5 for how to refresh this map after further POC changes.

## Links

Code and spec references link to **permalinks pinned to the audited commit** so line numbers
stay valid forever:

```
https://github.com/Blogem/msr-graph/blob/928936e/<path>#L<start>-L<end>
```

Each Part 1 subsection opens with linked **directory entry points**, and §1.6 links the specs by
name; inline `path:NN` citations in the prose are plain text but reconstructable against the same
base (append `#L<start>-L<end>`). Because the links pin to
`928936e`, they always show *exactly what was audited* — when you re-verify against a newer
commit (§5), regenerate the base SHA. (Relative links would track the latest `main` but drift
as line numbers move, which is why pinned permalinks are used here.)

## The big picture

Three layers, along a deliberate language boundary (Python only where spaCy is a hard
dependency; Go everywhere else; SvelteKit for the one frontend):

1. **Generic platform core** — RDF dataset client with named-graph staging isolation, the
   structured value store (behind pluggable connectors), the warm Python sandbox pool, the
   conversational analysis agent, the
   self-evolution proposal/apply engine, checkpoints, the web server + review/chat/admin UI,
   provenance, SHACL enforcement, and the LLM client. *Mechanism is domain-agnostic; MSR
   content is quarantined in description strings, namespace literals, and data files — never
   in control flow.*

2. **Domain plug-in points** — a small, nameable set of things a new domain supplies:
   the ontology + vocab, an entity canonicalizer, a structured-source parser, the seed-source
   queries, a relation schema, controlled value sets, and the structured-store connector(s) +
   locator scheme.

3. **Domain instance (MSR)** — NIST fluoride chemistry: the salt canonicalizer, the NIST CSV
   loader, the MSR ontology, the chemistry SHACL shapes, the safety corpus.

**The natural product** is an *RDF-backed, self-evolving KG platform with LLM-grounded
analysis*, where a new domain fills the plug-in points in layer 2. The strongest evidence
this is real: adding the IAEA **safety** corpus as a second, unrelated source required only
new *content* (a manifest, a PDF→text adapter into the existing normalized format, a `genre`
param, a lower frequency threshold) and reused the entire triage taxonomy, proposal
machinery, staging graphs, and approval routing **unchanged**.

## Legend

- 🟢 **generic** — lift as-is (or with cosmetic rename); no domain concepts.
- 🔴 **domain** — replace wholesale for a new domain.
- 🟡 **hybrid** — generic mechanism + domain content; carries a **Seam** and an **Un-entangle** move.

---

# Part 1 — Functional classification

## 1.1 Generic platform core (Go)

Entry points: [`internal/graph`](https://github.com/Blogem/msr-graph/tree/928936e/internal/graph) · [`internal/store`](https://github.com/Blogem/msr-graph/tree/928936e/internal/store) · [`internal/sandbox`](https://github.com/Blogem/msr-graph/tree/928936e/internal/sandbox) · [`internal/checkpoint`](https://github.com/Blogem/msr-graph/tree/928936e/internal/checkpoint) · [`internal/testutil`](https://github.com/Blogem/msr-graph/tree/928936e/internal/testutil)

| Module | Bucket | Note |
|---|---|---|
| `internal/sandbox/` | 🟢 | Warm single-use hardened Docker pool. Only branding constants (`MSR_SANDBOX_IMAGE`, `msr-sandbox-` prefix, `msr.sandbox` label). Lift as-is. |
| `internal/testutil/` | 🟢 | GraphDB reachability probe + prod-repo guard; repo names env-driven (`graphdb.go:37-43`). See §4.1. |
| `internal/graph/` | 🟡 | RDF client: core-read restriction, `FROM`-injection rejection, SHACL report parsing (all domain-clean); the `urn:msr:` graph IRIs are the only coupling. |
| `internal/store/` | 🟡 | Embedded value store (SQLite). `Open`/`Init`/`Upsert` control flow is generic; the `measurement_value` schema + SQLite pragmas are domain+engine-coupled. **This is the structured-store connector seam — see §3.8.** |
| `internal/checkpoint/` | 🟡 | Whole-store checkpoint/restore. Export/import/rollback/label flow generic; `VACUUM INTO`, the `owl:versionInfo` query, and `msr.db` filename are the coupling. |

**`internal/graph/` — Seam:** the hardcoded named-graph IRIs (`graph.go:32-47`:
`urn:msr:ontology|data|vocab|staging|provenance`), `CoreGraphs`/`knownGraphs` membership
(`graph.go:52,59-64`), and the `"urn:msr:proposal/"` prefix (`repo_ops.go:123`).
**Entanglement:** the client logic never mixes RDF plumbing with chemistry — `Select` iterates
`CoreGraphs`, `PutGraph` gates on `knownGraphs`; the tangle is purely these shared constants.
**Un-entangle:** inject `GraphConfig{Prefix, Core []GraphIRI, Known map[GraphIRI]bool,
ProposalPrefix}` into `graph.New(...)`; methods already read through the variables, so this is
config-injection, not a rewrite.

**`internal/store/` — Seam:** the whole `measurement_value` schema (`schema.sql:1-6` —
`salt`, `property`, `c0..c4`, `t_min/t_max`, `equation_form`, `source CHECK IN('nist','document')`),
the `MeasurementRow` struct (`upsert.go:11-26`), and the column-bound `upsertSQL` (`upsert.go:33-49`);
plus the SQLite driver + DSN pragmas (`store.go:30,38-41`). **Entanglement:** `Upsert` binds
`MeasurementRow`'s fields positionally against the hardcoded SQL, so the row type, DDL, and
INSERT column list must all agree — the generic transaction loop can't be reused without
editing the schema. **Un-entangle:** don't just swap the driver — introduce a **`StructuredStore`
connector interface** (see §3.8) that abstracts *read* (run a query, return rows) and *snapshot*
(for checkpoints) over whatever technology holds the values. The current SQLite code becomes the
`embedded-file` connector; new deployments register connectors for Postgres, Databricks, Athena,
InfluxDB, etc. The write path (`Init`/`Upsert`) is only needed by *embedded* connectors the
pipeline populates itself; external/federated stores (a warehouse, a time-series DB) are
read-only sources the connector queries but never writes.

**`internal/checkpoint/` — Seam:** `sqliteFileName="msr.db"` (`checkpoint.go:36`), the
`versionQuery` embedding `GRAPH <urn:msr:ontology>` + `owl:versionInfo` (`checkpoint.go:44-47`),
and the SQLite-only `VACUUM INTO` snapshot (`checkpoint.go:332`). **Un-entangle:** inject a
`VersionReader` func and a `Snapshotter` interface (`Snapshot(dst)`, `Swap(dst)`) into
`NewEngine`; an embedded-connector build (e.g. DuckDB) supplies its own `Snapshotter`.

## 1.2 Self-evolution engine — the crown jewel (Go)

Entry points: [`internal/proposal`](https://github.com/Blogem/msr-graph/tree/928936e/internal/proposal) · [`internal/agent`](https://github.com/Blogem/msr-graph/tree/928936e/internal/agent)

Verdict: **cleanly extractable.** Every executable path is domain-agnostic mechanism; MSR
content is quarantined in (a) model-facing description/prompt strings and (b)
namespace/predicate literals, never in control flow.

| Module | Bucket | Note |
|---|---|---|
| `internal/proposal/version.go` | 🟢 | Semver bump. Copy verbatim. |
| `internal/agent/tools.go` | 🟢 | `Tool` interface (`Spec()`+`Call()`). Copy verbatim. |
| `internal/agent/config.go`, `events.go` | 🟢 | Loop config; typed trace events (provenance fields are generic KG-grounding). |
| `internal/agent/llm.go` | 🟢 | OpenAI-compatible client, injectable `http.Client`, configurable `BaseURL`. **Already matches the target design.** |
| `internal/agent/sqlguard.go` | 🟢 | Read-only SQL guard (state-machine, not regex). Copy verbatim; re-verify quoting/keyword lists for DuckDB. |
| `internal/proposal/routing.go` | 🟡 | Typed routing by triple type. ~95% generic — keys off standard OWL/SKOS terms; one domain literal `msr:PhysicalProperty` (`routing.go:32`). |
| `internal/proposal/engine.go`+`lifecycle.go` | 🟡 | Approve/reject/edit state machine, atomic, idempotent, SHACL-rollback. Domain only in namespace/predicate literals. |
| `internal/agent/loop.go` | 🟡 | Bounded tool-use loop. MSR appears only in the `SystemInstructions` const (`loop.go:17-36`), appended at `loop.go:103`. |
| `internal/agent/sparql.go` | 🟡 | `sparql_query` tool + provenance-by-variable-name. Domain content entirely in `sparqlToolDescription` (`sparql.go:17-82`). |
| `internal/agent/sql.go` | 🟡 | `sql_query` tool. Domain content in `sqlToolDescription` (`sql.go:27-33`: `measurement_value` schema). |
| `internal/agent/python.go` | 🟡 | `run_python` tool. Domain content in `runPythonDescription` (`python.go:18-24`: `/data/msr.db` + schema). |
| `internal/agent/prompt.go` | 🟡 | Byte-stable KG-schema prompt builder (~60% generic mechanism). Salt-catalog fetch/render + grounding prose is the domain payload. |

**Top un-entangle moves (priority order):**
1. **Hoist the model-facing strings to injected config.** `SystemInstructions` (`loop.go:17`) →
   a `Config`/`RunRequest` field (one-line change at `loop.go:103`); the three tool
   descriptions (`sparql.go:17`, `sql.go:27`, `python.go:18`) → `NewXTool(..., description)`
   params. Executors are already clean.
2. **Parameterize the governance vocabulary.** Inject `GovernanceVocab{Prefixes,
   ReviewStatusPredicate, ProposalResourcePrefix, ApproveActivityPrefix, AgentPrefix}` into
   `NewEngine`; the SPARQL builders (`lifecycle.go:211-239`, `engine.go:90-92`) read fields
   instead of the package consts `sparqlPrefixes`/`turtlePrefixes` (`engine.go:58-84`). Keep
   `owl:versionInfo`/`owl:Ontology` as generic OWL; drop the chemistry-only QUDT `qk:`/`unit:`
   prefixes from the default.
3. **Make routing a config-driven table.** Replace the `vocabFilter`/`ontologyFilter` consts
   with a `[]RoutingRule{DestGraph, TypeClasses, PredicateAllowlist}`; standard SKOS/OWL terms
   are the default rule set, `msr:PhysicalProperty` becomes one caller-supplied ontology entry.
4. **Templatize the prompt.** Extract a `PromptSection` interface (`Fetch`+`Render`); TBox/SKOS
   sections built-in, the salt-catalog section a domain plug-in; intro/grounding prose becomes
   an injected `Preamble` (`prompt.go:71-81,407-425,461-483`).

## 1.3 Web layer (Go + SvelteKit)

Entry points: [`cmd/server`](https://github.com/Blogem/msr-graph/tree/928936e/cmd/server) · [`cmd/chatcli`](https://github.com/Blogem/msr-graph/tree/928936e/cmd/chatcli) · [`webapp/src`](https://github.com/Blogem/msr-graph/tree/928936e/webapp/src)

Verdict: highly reusable; the review-diff UI is **data-driven, not MSR-coupled**.

| Module | Bucket | Note |
|---|---|---|
| `cmd/server/{main,handler,sse,static,checkpoints,apierror}.go` | 🟢 | HTTP mux, SSE, static embed, checkpoints, typed errors. |
| `cmd/server/chat.go` | 🟢 | Stateless `POST /api/chat` → streams `agent.Run` events. (Domain only in test fixtures.) |
| `cmd/chatcli/` | 🟢 | Terminal SSE client. Fully reusable. |
| `webapp/src/lib/api.ts,sse.ts,types.ts` | 🟢 | Typed fetch client + wire types (generic `Triple`/`Evidence`/`Neighborhood`). |
| `webapp/src/lib/chat/` (TraceTimeline etc.) | 🟡 | Timeline dispatches purely on event type — generic. Domain content = `EXAMPLE_PROMPTS` + onboarding heading (`ChatSurface.svelte:39-43,141`). |
| `webapp/src/lib/review/` (DiffView, triples.ts) | 🟡 | `buildDiff()` (`triples.ts:53-95`) overlays arbitrary triples with zero salt/property knowledge. Seam = unit-predicate constants (`triples.ts:107,110`) + placeholder text (`ReviewSurface.svelte:340,349`). |
| `webapp/src/lib/admin/`, `ui/`, `theme.ts`, design system | 🟢 | Admin, app shell, tokens, theming. Only cosmetic branding (`msr-theme` key, page title). |
| `cmd/server/proposals.go` | 🟡 | Review API. JSON response shapes already generic RDF; seam = the `msr:` proposal-schema namespace + predicates (`proposals.go:34-35,83-92,297-306`). |

**The static/API mux gotcha (reuse caveat, keep verbatim):** do NOT register the static
handler at `"/"` on the same `ServeMux` as method-scoped patterns — a `GET` to a `POST`-only
route would fall through to the SPA catch-all instead of net/http's built-in `405`. The fix is
`newAPIOrStaticMux` (`handler.go:61-114`): probe `api.Handler(r)`, empty pattern + 404 → static
fallback, empty pattern + 405 → forward the 405. Documented at `handler.go:16-33`.

## 1.4 Extraction pipeline (Python)

Entry point: [`extraction/src/msr_extraction`](https://github.com/Blogem/msr-graph/tree/928936e/extraction/src/msr_extraction)

Generic skeleton: **acquire → normalize OCR → segment (offsets) → build EntityRuler from a
graph read → layered precision-biased linker (exact→resolver→fuzzy→LLM→novel) → schema-
constrained LLM disambiguation (link-to-existing-IRI-or-declare-novel, validated app-side) →
propose-then-validate-against-closed-sets relations → deterministic idempotent RDF writes +
dual SQLite store.**

Domain-clean (🟢, lift as-is): `sparql.py`, `disambiguation.py`, `disambig_cache.py`,
`seeding.py`, `segmenter.py`, `equations.py`.

| Module | Bucket | Seam / note |
|---|---|---|
| `formula.py` | 🔴 | **The entity-canonicalizer plug-in.** Consumed only via `normalize_salt_span(surface, known) -> IRI\|None` (`formula.py:332`). Replace wholesale; preserve the one-function contract. |
| `graph_reader.py` | 🟡 | **The seed-source plug-in.** Client + core-read guard generic; domain = the SPARQL query set (`graph_reader.py:62-108`) + the `read_known_entities` merge (`:208-211`). Make the query set a config/registry. |
| `relations.py` | 🟡 | **The weakest seam.** Propose→validate→record loop generic; the five relation kinds are hardcoded in the prompt (`:435-483`) and the `validate_relation` dispatch (`:706+`). Needs a `RelationSchema` object (kind names + field spec + prompt fragment + validator + closed-set key). |
| `edges.py` | 🔴 | Emits MSR edge triples + mints reactor individuals. Rewrite alongside the relation schema; keep the deterministic-IRI + reification templates. |
| `linker.py` | 🟡 | Layered driver generic; the formula-candidate regex + composed-salt-supersedes rule (`:116-143,343-391`) is the domain layer. Extract behind a `CandidateResolver` interface. |
| `normalizer.py` | 🟡 | OCR cleanup steps 1/2/4 generic; the intra-word-split table (`:66-70`) and in-place sub/superscript→ASCII (`:103-142`, chemistry/isotope) are domain — inject the split table + a superscript-policy flag. |
| `variants.py` | 🟡 | Separator/case expansion generic; the formula-subscript branch (`:25-81`) is chemistry — make a pluggable variant-generator hook. |
| `measurements.py` | 🟡 | Dual-store write generic; predicate set `msr:ofSalt/forProperty/hasUnit/equationForm` (`:39-47`) is domain — template the predicates. |
| `measurement_store.py` | 🟡 | Upsert generic; `measurement_value` columns (`:13-18`) domain — parameterize table + columns. |
| `units.py` | 🟡 | Mapper/allowlist/dimension-guard generic; `_SURFACE_FORM_TO_PROPERTY` (`:37-49`) domain — load from config. |
| `documents.py`, `manifest.py`, `acquisition.py` | 🟡 | Document-node writer / markdown-manifest parser / corpus clone — generic mechanisms; namespaces, column shape, and source URL are the (already-externalized) seams. |
| `kg_prompt.py` | 🟡 | Generic except `_KIND_ORDER=("concept","class","salt")` (`:33`); prompt text is injected as a prefix (mechanism ≠ content). |
| `curated.py` | 🔴 | Demo scoping: 11 ORNL report IDs + solubility/graphite regexes. Replace wholesale. |
| `cli.py` | 🟡 | Stage orchestration generic; the command→pipeline map + genre wiring is domain. |

## 1.5 Mining / triage / proposal loop (Python)

Entry point: [`extraction/src/msr_extraction`](https://github.com/Blogem/msr-graph/tree/928936e/extraction/src/msr_extraction) (the `novelty` / `triage` / `proposals` / `mine_*` / `safety_*` modules)

Verdict: **cleanly generic in mechanism, domain content isolated at nameable seams.** DF is a
coarse *cost bound*, never a novelty rank; thresholds are all env-config. The four kinds
(property/class/instance/relation + reject) are a domain-neutral ontology-evolution taxonomy
(`mining_types.py:28-44`).

| Module | Bucket | Seam / note |
|---|---|---|
| `mining_types.py` | 🟢 | Dataclasses + kind constants + `safe_type_ref` injection guard. Only `_SAFE_CURIE_PREFIXES` (`:52`) to parameterize. |
| `mine_provenance.py` / `provenance.py` | 🟢* | PROV-O two-activity pattern; the two files differ *only* in pipeline-identity constants — evidence the machinery is generic. Collapse into one factory taking (activity-iri, version, agent, run-namespace). |
| `novelty.py` | 🟡 | Detect+score+exclude generic; domain = `_normalize_salt_label` (`:299-320`), the role/reactor label source (`:826`), and the `genre=="safety"` string branching repeated ~10× — make genre a config struct, extract a per-entity-kind normalizer registry. |
| `triage.py` | 🟡 | Taxonomy + LLM-confirm-then-validate generic; domain = the cheap-signal regexes (`:45-84`, chemistry/reactor) → a domain-supplied `SignalRuleset`, and `_SAFETY_GENRE_GUIDANCE` (`:96-115`) → a `genre→prompt-fragment` map. |
| `proposals.py` | 🟡 | Bundle + two-graph routing + deterministic IRIs generic. **Grounding source IS already pluggable** — the QUDT allowlist is a JSON file loaded by path (`:111-123`, env `MSR_QUDT_UNITS_PATH`) enforced as a frozenset guard; INIS refs are stored unverified (`mining_types.py:216-218`). Remaining seam = hardcoded `w3id.org/msr-kg` namespaces (`:62-69`). |
| `auto_accept.py` | 🟡→🟢 | "Instances skip staging given a TBox/data split" is generic; `core_types` is **already an injectable param** (`:128,148-149`). Only the `CORE_TYPES` default (`:46-53`) + namespaces are domain. |
| `mine_runner.py` | 🟡 | Orchestration generic; `genre=="chemistry"/"safety"` branches (`:251-261`) + `SAFETY_SOURCES` import → lift the genre→(reports, config) mapping into a registry. |
| `safety_acquire.py` | 🟡 | **The reusability proof.** Everything after PDF→text extraction reuses the chunk-5 normalizer/segmenter verbatim (`:67-84`); a new source only supplies a PDF→text step producing the existing format. |
| `safety_manifest.py` | 🔴 | Four specific IAEA/GIF/ORNL docs. Pure per-corpus content; the `SafetySource` dataclass shape (attribution + page scoping) is a generic manifest pattern. |

## 1.6 Domain ingest — NIST loader + ontology (mostly 🔴, generic skeleton inside)

Entry points: [`internal/nist`](https://github.com/Blogem/msr-graph/tree/928936e/internal/nist) · [`cmd/loader`](https://github.com/Blogem/msr-graph/tree/928936e/cmd/loader) · [`ontology`](https://github.com/Blogem/msr-graph/tree/928936e/ontology)

**Generic "structured loader" skeleton (chemistry removed):** `cmd/loader/main.go` dispatch +
`initdb.go` + `seed.go`'s PUT-loop/staging idempotency + `nist.go`'s runX orchestration shape
(load allowlist → transform → open/init SQL → idempotent Upsert → additive catalog
`INSERT DATA` → per-run PROV lineage → summary), keeping the domain-free helpers
`buildProvenanceData`/`quoteLiteral`/`formatFloat` (`cmd/loader/nist.go:355-404`), `slugify`
(`internal/nist/iri.go:15-30`), the `UnitAllowlist` facility (`internal/nist/units.go`), the
robust-CSV reader shape (`parse.go:62-94`), and `Process` as a driver parameterized by
(fileManifest, filterFn, canonicalizeFn, buildFn) with deterministic key-disambiguation
(`process.go:95-146`).

**The four true plug points a new domain replaces:** (1) the source parser (`parse.go` rawRow +
manifest), (2) the scope filter (`filter.go` `IsFluoride`), (3) the canonicalizer + IRI minter
(`canonical.go`, `iri.go` locator half), (4) the triple emitter (`buildInsertData`,
`cmd/loader/nist.go:209-325`).

Pure domain (🔴): `internal/nist/{canonical,filter,equationform,measurement,nist}.go`,
`ontology/{msr.ttl,vocab.ttl}`, and specs
[salt-canonicalization](https://github.com/Blogem/msr-graph/blob/928936e/openspec/specs/salt-canonicalization/spec.md),
[salt-formula-normalization](https://github.com/Blogem/msr-graph/blob/928936e/openspec/specs/salt-formula-normalization/spec.md),
[salt-role-reactor-edges](https://github.com/Blogem/msr-graph/blob/928936e/openspec/specs/salt-role-reactor-edges/spec.md),
[nist-structured-loading](https://github.com/Blogem/msr-graph/blob/928936e/openspec/specs/nist-structured-loading/spec.md).

Generic-mechanism specs (🟢/🟡):
[seed-graph-loading](https://github.com/Blogem/msr-graph/blob/928936e/openspec/specs/seed-graph-loading/spec.md)
(graph-replace PUT + staging idempotency),
[kg-schema-prompt](https://github.com/Blogem/msr-graph/blob/928936e/openspec/specs/kg-schema-prompt/spec.md)
(deterministic serialization + version-gated rebuild),
[qudt-unit-allowlist](https://github.com/Blogem/msr-graph/blob/928936e/openspec/specs/qudt-unit-allowlist/spec.md)
& [unit-qudt-mapping](https://github.com/Blogem/msr-graph/blob/928936e/openspec/specs/unit-qudt-mapping/spec.md)
(vendored allowlist, validate-before-write, values-only).

---

# Part 2 — The framework vs. domain boundary

## Reusable building blocks (the platform to keep)

- **RDF dataset client** with named-graph staging isolation + `FROM`-injection rejection (`internal/graph`).
- **Structured value store** contract: row keyed by `locator`, tagged by `source`+`doc_id`, numbers kept out of RDF (`internal/store`) — schema becomes domain-defined; the engine becomes a pluggable connector (embedded SQLite/DuckDB, or federated Postgres/warehouse/time-series), see §3.8.
- **Warm sandbox pool** (`internal/sandbox`) — lift as-is.
- **Analysis agent runtime** (`internal/agent`) — loop, tool interface, SQL guard, LLM client, events, provenance-by-var-name — all generic; descriptions/prompt injected.
- **Self-evolution engine** (`internal/proposal`) — lifecycle state machine, typed router, version bump — config-parameterized.
- **Checkpoints** (`internal/checkpoint`) — snapshotter interface for the engine.
- **Web server + SvelteKit UI** — chat + trace timeline, data-driven review-diff, admin, design system.
- **Extraction pipeline skeleton** (Python) — acquire→normalize→segment→seed→link→disambiguate→relate→write.
- **Mining/triage/proposal loop** (Python) — detect→score→triage(4 kinds)→ground→package.
- **Structured-loader skeleton** (Go) — parser + filter + canonicalizer + emitter as injected functions.

## Domain plug-in points (what a new domain supplies)

1. **Ontology + SKOS vocab** — see the ontology contract below.
2. **Entity canonicalizer** — Python `normalize_span(surface, known) -> IRI|None` (replaces `formula.py`) + the candidate-finder regex in the linker; Go canonicalizer + IRI minter (replaces `canonical.go`/`iri.go` locator half).
3. **Structured-source parser + scope filter + triple emitter** — replaces `internal/nist` core + `cmd/loader/nist.go` emitter.
4. **Seed-source queries** — the SPARQL query set in `graph_reader.py` deciding what the EntityRuler seeds from.
5. **Relation schema** — *the declarative model of the typed edges the LLM extracts between
   entities.* A "relation" is an edge like *salt→property→value* or *reactor→moderatedBy→
   material*; relations are how the graph gains structure beyond isolated nodes. Today each
   relation *kind* is hardcoded in three places at once — the extraction prompt
   (`relations.py:435-483`), the `validate_relation` dispatch (`relations.py:706+`), and the
   triple emitter (`edges.py`) — so a new domain must edit all three. The plug-in makes it one
   declarative object per kind: `{name, field spec, prompt fragment, per-field validator,
   which closed-set each field resolves against}`. Then a new domain's edges = a config list,
   not a code+prompt rewrite. This is the **weakest-factored seam today** and the highest-value
   one to design cleanly, because relations are exactly what differs most between domains.
6. **Controlled value sets ("allowlists")** — any set of values the domain constrains and
   validates. MSR's is the `qudt-units.json` unit allowlist (already a path-loaded plug-in) +
   the surface-form→property table; generalise to "one canonical file per controlled vocabulary,
   validated at write time (§3.13) and generated into every consumer (§3.9)."
7. **Structured-store connector(s) + locator scheme** — instead of "value-store columns," a
   `StructuredStore` connector per technology and a locator convention the graph uses to name
   *which store* + *the address within it* (see §3.8). The MSR `measurement_value` schema is one
   embedded connector's payload; other domains point locators at a warehouse, a SQL DB, or a
   time-series store.
8. **Governance + graph-name config** — the `urn:msr:` prefix, graph names, and proposal/review CURIEs (one config struct threaded through graph/proposal/checkpoint).

## The ontology contract (what the platform needs from *any* domain model)

The platform does **not** assume physics, chemistry, or "measurements" — those are the MSR
*instantiation*. What it structurally requires is a small set of **roles** a domain ontology
must fill. MSR fills them with `PhysicalProperty` / `PropertyMeasurement` / units, but any domain
supplies its own classes for the same roles.

| Role the platform needs | Why | MSR's instantiation (example only) |
|---|---|---|
| **Entities / individuals** the KG is about | the nodes NER links mentions to and the subjects of relations | `MoltenSalt`, `Constituent`, reactors |
| **A SKOS ConceptScheme** — the domain vocabulary with pref/altLabels | seeds the EntityRuler; the NER target set. *(You confirmed a domain vocabulary is genuinely expected — this role is kept verbatim.)* | `vocab.ttl` (29 INIS concepts) |
| **A relation model** — the typed edges between entities (the domain's *relation schema*, plug-in point 5) | the graph's structure; what the LLM extracts | measurement / role / reactor / safety edges |
| **External-value references** — a class/pattern whose individuals carry a **locator** into a connected structured store, plus whatever typing the domain needs to interpret the value | keeps unbounded/numeric data out of RDF and in the right store (§3.8) — the federation boundary | `PropertyMeasurement` + `dataLocator` (+ property, unit, equation-form) |
| **Controlled value sets** the domain constrains + validates | data quality, enforced via SHACL (§3.13), generated-from-one-source to avoid drift (§3.9) | the QUDT unit allowlist — generalises to *any* declared set of allowed values |
| **A PROV-O slice** (Entity/Activity/Agent + wasGeneratedBy/wasDerivedFrom) | provenance-everywhere (§3.5) — already domain-agnostic, lift as-is | `msr.ttl:113-127` |
| **`owl:versionInfo`** on the ontology node | the cache key for the prompt builder (§3.4) | `msr.ttl:17` |

The generalisation from MSR: "property + measurement + unit + equation-form" is just *one* shape
of **external-value reference + controlled value set**. A different domain might model events with
timestamps in a time-series store, or documents with embeddings in a vector store, filling the
same two roles with entirely different classes. The platform only cares about the roles.

---

# Part 3 — Non-functional / cross-cutting patterns

These are the practices worth carrying regardless of domain — several are easy to lose and
expensive to rediscover.

### 3.1 Integration-test isolation against a disposable GraphDB repo (highest value)

`go test ./...` with GraphDB reachable would otherwise mutate the live `msr` repo. Three
cooperating layers make that structurally impossible:

- **Shell reset guard** (`scripts/ensure-repo.sh:83-90`): `REPO_RESET=1` refuses when
  `REPO_ID=msr` (`exit 1`); defaults are `REPO_ID=msr`, `REPO_RESET=0` (`:44-45`), so `make up`
  is unaffected. Non-`msr` ids get the vendored config TTL sed-swapped to the target id.
- **Go decision layer** (`internal/testutil/graphdb.go`): `RequireGraphDB(getenv)` returns
  `Decision{Run|Skip|Fatal}`; a pre-network guard (`:125-134`) **skips** (not fails) if the
  test repo resolves to the prod name. Reachability trichotomy: connection-refused/timeout →
  Skip (Fatal if `GRAPHDB_REQUIRED`); repo-absent/404 → Skip "run `make test-repo`"; other
  transport error → always Fatal. The package never imports `testing` (`:16-18`) so the guard
  is itself unit-testable with an injected `getenv`.
- **Make wiring** (`Makefile:165-173`): `test-repo` resets+seeds `msr-test`; `test` pins
  `GRAPHDB_TEST_REPO=msr-test go test -p 1 ./...` (`-p 1` because integration tests share the
  one repo). `TestRepo()` (`graphdb.go:187-195`) must be forwarded as `GRAPHDB_REPO` to any
  `cmd/loader` subprocess, or the loader falls back to its own `msr` default.

**Reuse:** carry all three layers; rename only the two repo constants. The load-bearing idea is
the *double guard* — one at the provisioning boundary (shell), one at the test-entry boundary
(Go) — plus the skip/fatal/`REQUIRED` trichotomy so a bare `go test` stays non-destructive.

### 3.2 Dependency injection with test doubles ("never a live model or Docker")

One narrow interface per external dependency, each with an in-memory fake:
`LLMClient.Complete` (`internal/agent/llm.go:70-84`, doc states "no test ever contacts a live
model"), `sandbox.Runtime` + `fakeRuntime` (`fake_test.go`, `-race`-safe, no daemon),
`GraphSelector` (Select-only), injectable `*http.Client` (`graph.go:76`), injected `getenv`.
**Reuse:** make the interface the *narrowest* the consumer needs; keep fakes in `_test.go`;
gate the real integration path behind a `*_REQUIRED` env flag.

### 3.3 Determinism & idempotency as a testable property

Content-derived IRIs + no blank nodes → re-running a stage is a no-op. `TestSeedLoadIsIdempotent`
(`internal/graph/seed_integration_test.go`) asserts identical per-graph triple counts on
double-run. **Cross-language drift guard:** one fixture `testdata/salt-canonicalization.json`
is consumed by *both* the Go (`internal/nist/canonicalize_test.go`) and Python
(`extraction/tests/test_formula_fixture.py`) canonicalizers, guaranteeing they can't silently
diverge. **Reuse:** mint identifiers as pure functions of content; forbid blank nodes; make one
JSON fixture the contract between any two-language implementations.

### 3.4 Prompt-cache stability (cost/latency)

The KG-schema system prompt is a byte-stable, deterministically-ordered prefix (every
collection sorted by IRI — `prompt.go:173,214,264-267,338-343`) rebuilt **only** on an
`owl:versionInfo` bump (one cheap SELECT per chat request — `DetectVersion` `:488-501`,
`PromptCache` `:504-525`; Python mirror `kg_prompt.py:50-110`). This is what makes DeepSeek's
automatic prefix cache hit. **Reuse:** deterministically order any long, slowly-changing prompt
prefix and cache it behind a cheap monotonic version token; put volatile content *after* the
cacheable prefix.

### 3.5 Provenance-everywhere + trace-as-deliverable

PROV-O generation/derivation on every asserted fact; the reasoning trace is a typed SSE stream
(`internal/agent/events.go:10-53`: text/tool_call/tool_result/script_run/provenance/answer/
done/error); and the loop *itself* emits `AnswerEvent{Grounded: anyProvenance}` computed from
whether any provenance event fired this turn (`loop.go:194-202`) — grounding is enforced by the
orchestrator, never self-reported by the model. **Reuse:** typed event stream + loop-enforced
groundedness verdict.

> **Known limitation (do not ship as-is).** `Grounded = anyProvenance` is a coarse OR over the
> whole turn: a **single** provenance event flips the entire answer to "grounded," even if other
> sentences are hallucinated or drawn from the model's parametric memory rather than the graph.
> It is a demo-grade signal, not a guarantee. **Production hardening:** move from turn-level to
> **claim-level** grounding — attribute each factual/numeric assertion to the specific
> tool_result that supports it and stamp any unsupported claim as ungrounded; or add a verifier
> pass asserting every cited number appears verbatim in a tool result. The trace-as-deliverable
> mechanism is sound and reusable; the *verdict function* is the part to strengthen.

### 3.6 Named-graph isolation as a query-layer contract

Core reads inject protocol dataset params and reject self-supplied `FROM`/`FROM NAMED`
(`internal/graph/client.go:26-38`); the agent holds only a `Select`-only `GraphSelector`, so it
*structurally cannot* reach `SelectRaw` (`internal/agent/sparql.go:100-115`). Unreviewed
proposals are "one `FROM` clause away" but unreachable. **Reuse:** enforce read scope at the
client method boundary; expose only the scoped method to untrusted callers.

### 3.7 Batch-not-services operational model

Only `graphdb` + `server` are long-running; loader/extraction/mine are one-shot
`profiles:["tools"]` containers run via `docker compose run --rm` (`docker-compose.yml:131,154`;
`Makefile:135-163`). Back-population = full re-run; the EntityRuler is rebuilt from the graph
each run (no refresh signal). Safe because of §3.3's determinism. **Reuse:** design each stage
as a pure function of inputs → deterministic outputs, so re-running is idempotent and recovery
is trivial.

### 3.8 Structured-data store — from an embedded file to a connector model

**The generalisation:** the POC uses one embedded SQLite file for all numeric values, but the
reusable design is *the graph holds a locator, a connector fetches the values*. Production domains
pull structured data from many technologies — a warehouse (Databricks, BigQuery), a query engine
over object storage (Athena, Trino), a relational DB (Postgres), a time-series DB (InfluxDB), or an
embedded file (SQLite/DuckDB) — so the store must be a **pluggable connector**, not a fixed engine.
"DuckDB instead of SQLite" is just *one more embedded connector*, not the abstraction.

**The abstraction — a `StructuredStore` connector interface with two capabilities:**
- **read** — run a read-only query, return rows. This is what the agent's sandbox scripts and the
  `sql_query` tool call.
- **snapshot** *(optional)* — a consistent point-in-time copy for checkpoints. Federated/external
  stores (a warehouse, a live time-series DB) are **read-only sources you don't own** and often
  can't snapshot; for those a checkpoint records the **query + a timestamp/version pointer**, not a
  data copy, and restore re-reads. Only embedded connectors the pipeline populates itself are fully
  snapshottable.

**The locator is the routing key.** Today `dataLocator` is an opaque string into the one SQLite
file. Generalise it to name **which store** + **the address within it**, e.g.
`store://warehouse/schema.table?filter=…` or `sqlite:///data/msr.db#measurement_value/<key>`. A
**connector registry** resolves scheme → connector. This is precisely "know where to go for data,
then use the right connector": the graph is the catalog of *where*, the connectors are the *how*.

**Capability differences matter.** Connectors are not interchangeable — some push compute down (a
warehouse aggregates server-side), others only return rows (the sandbox does the math, the POC's
model). The interface should advertise capabilities so the agent/planner knows whether to aggregate
in-store or in the sandbox. Auth, cost, and latency also differ per connector and live in its
config, not the core.

**The embedded connector's runtime discipline (the POC/SQLite case, and the DuckDB case).** When a
connector *is* an embedded file mounted read-only into the sandbox, these settings are load-bearing;
a DuckDB embedded connector must re-derive each from the same *constraint*:

| SQLite choice | Why (the constraint) | DuckDB equivalent |
|---|---|---|
| `journal_mode=DELETE`, never WAL (`store.go:33,39`) | WAL's `-wal`/`-shm` sidecars can't be created on a read-only mount → unreadable | Single-file; open the sandbox mount `ACCESS_MODE=READ_ONLY`; mind DuckDB's write-time `.wal` |
| `busy_timeout` on every conn (`:24-25,39-42`) | Avoid "database is locked" under concurrent chat + checkpoint | Single-writer/multi-reader — serialise writes or use separate RO connections |
| Directory-not-file read-only mount | Journal sidecars stay visible to siblings | Mount the directory holding the `.duckdb` file |
| `VACUUM INTO` on a dedicated RW conn (`checkpoint.go:309-332`), never the `mode=ro` chat conn | Consistent snapshot without stopping the server | `EXPORT DATABASE` / `ATTACH`+`COPY FROM DATABASE`, or a checkpointed file copy (no `VACUUM INTO`) |

**Reuse:** design the `StructuredStore` connector interface (read + optional snapshot +
capabilities) and the scheme-based locator + registry *first*; make SQLite/DuckDB the embedded
connector and warehouse/query-engine/time-series the federated read-only connectors. Keep
"checkpoint uses a dedicated RW connection distinct from the RO read connection" for any embedded
connector; for federated ones, checkpoint the query pointer, not the data.

### 3.9 Fail-loud gates + single source of truth (anti-drift)

Validate-before-write (QUDT allowlist, `internal/nist/units.go:54-64`); SHACL at commit; typed
API errors mapping a `*graph.ValidationError` → **422 with structured `violations`**
(`cmd/server/apierror.go:34-119`), never an opaque 500. And one file — `ontology/qudt-units.json`
— drives three consumers: the Go loader's validation, the generated SHACL shape
(`cmd/gen-unit-shape`, regenerated on every `make up` so a hand-edit can't drift), and the
Python mapper. **Reuse:** pick one canonical file per shared vocabulary and *generate* every
downstream artifact from it; surface validation failures as typed structured errors.

### 3.10 Security / safety posture (as one checklist)

For any "LLM runs code + queries a store" system: unconditional sandbox hardening
(`--network none`, read-only rootfs, non-root, `CapDrop:ALL`, `no-new-privileges`, cpu/mem/pids
limits, noexec tmpfs — `sandbox/docker.go:58-95`, deliberately *not* per-call configurable);
fail-closed **state-machine** (not regex) SQL guard (`sqlguard.go` — a regex stripper once let a
stacked `DROP` through via `/* */` across string literals); structural read-only enforcement at
three layers (interface without `SelectRaw` + query-layer `FROM` rejection + `mode=ro`
connection); commit-time SHACL that fails loudly if a pre-SHACL repo is detected; path-traversal-
safe checkpoint labels validated *before* any path is built (`checkpoint/label.go:26-31`);
injection-safe deterministic IRI minting (`iri.go:15-31`) + Graph-Store-Protocol PUT for proposal
edits. **Principles:** make dangerous capabilities structurally unreachable; fix isolation as
non-negotiable policy; parse with a state machine when guards must survive quoting tricks.

### 3.11 Inference: a deliberate choice, and how to enable it

The POC disables inference — but that is a *choice*, and OWL/RDFS reasoning (GraphDB's, or any
reasoner's) is genuinely powerful: subsumption/classification, consistency checking, and richer
queries without hand-written property paths. A generic platform should treat inference as a
**supported mode**, not a permanent constraint. Both branches:

**Why the POC turned it off** (`docs/ARCHITECTURE.md:354-366`): (1) forward-chaining materialises
inferred triples into the *implicit* graph, not their premises' named graph → **breaks the
named-graph staging isolation** (§3.6/§1.2), so a pending proposal could spawn statements outside
its proposal graph; (2) inferred triples carry **no provenance** and silently repair typing
mistakes the review loop should surface; (3) **low payoff** for a shallow TBox that only needs
`rdfs:subClassOf*`, answerable by property paths. Fixed at repo creation
(`deploy/graphdb/msr-repo-config.ttl`, `graphdb:ruleset "empty"`).

**How to build it *with* inference enabled** — address each of the three tensions:
- **Staging isolation:** don't rely on named-graph membership as the isolation boundary when a
  reasoner materialises across graphs. Options: (a) isolate proposals in a **separate repository/
  dataset** (or a reasoning-off overlay) and only merge into the reasoned graph on approval — the
  cleanest fit for the existing typed-routing apply engine; (b) reason over the **core dataset
  only** and keep proposals in a non-reasoned staging store; (c) use a store that scopes reasoning
  per named graph.
- **Provenance of inferred triples:** enable the reasoner's **explanation / axiom-pinpointing** so
  each inferred triple can be traced to the asserted triples + rule that produced it, and treat
  inferred statements as `prov:wasDerivedFrom` their premises. Never let domain/range inference
  *silently* fix data the review loop should see — surface it as a proposal instead.
- **Exactness of tests/checkpoints:** make idempotency and count assertions run against the
  **explicit (asserted) graph** (GraphDB exposes an explicit-only query context), so materialised
  triples don't perturb counts; checkpoint the asserted triples and re-materialise on restore.

**Reuse guidance:** make inference a **config flag on the graph engine**, defaulting off for the
staging-isolated / provenance-strict / exact-count posture, but with the three mechanisms above
available so a deployment that wants classification/consistency-checking can opt in. Note that
some engines fix the ruleset at repo creation (GraphDB does), so decide per deployment and
provision accordingly — starting reasoned is harder to walk back than starting unreasoned.

### 3.12 Build/orchestration surface & secrets hygiene

Makefile as the single self-documenting entrypoint (`up` preflights the license and health-polls
GraphDB; every pipeline stage is a target); Compose splits two long-running services from
profiled one-shot batch jobs; the server launches **sibling** sandbox containers over the host
docker socket and must be told the host data path (`MSR_DATA_HOST_DIR: ${PWD}/data`) because bind
sources resolve on the host daemon. Python tests run via `cd extraction && uv run --extra test
python -m pytest`. Secrets/licenses gitignored with an explicit `!` allowlist for vendored bits;
`graphdb.license` per-registrant and preflighted in `up`; `DEEPSEEK_API_KEY` env-only with an
empty default. **Reuse:** Make-as-facade; preflight required secrets and fail fast; source all
keys from env.

### 3.13 Constraint validation as a first-class, portable trust gate (SHACL)

Alongside provenance (§3.5), **SHACL is a trust pillar** (see the trust-pillars note at the top):
it is what stops the self-evolution loop and the LLM extractors from writing malformed or
out-of-vocabulary data into the graph. In the POC it runs as a **commit-time gate** — GraphDB's
`ShaclSail` validates every transaction *including proposal/staging writes*, so a violating bundle
can't even be staged; the shape catalogue lives in a reserved graph and is regenerated from the
same source the loader uses (§3.9); `ensure-repo.sh` fails loudly if a pre-SHACL repo is detected;
and a rejection surfaces as a typed **HTTP 422 with structured `violations`**
(`cmd/server/apierror.go:34-119`), never an opaque 500.

**Why it needs its own pattern:** the *shapes* are portable, but the *enforcement point* is
engine-specific. If you leave GraphDB, `ShaclSail`'s automatic commit-time validation leaves with
it — and losing the gate silently would be a major regression. So the platform must own the
validation step explicitly rather than delegate it to the store.

**Portability (SHACL without GraphDB).** SHACL is a W3C standard; the shapes are just RDF and port
verbatim. Only the *where/when* changes:
- **Enforce at the application write boundary.** Wrap every graph write in a validate-then-commit
  step using a SHACL library — `pySHACL` (Python), Apache Jena / `rdf4j` SHACL, TopBraid SHACL API
  (JVM), or a JS engine (`shacl-engine`/Zazuko) — and reject on violation, reproducing the 422
  contract. This makes the gate engine-independent (works over Neptune, Blazegraph, Oxigraph, a
  plain triple file, etc.).
- **Keep shapes generated-from-one-source** (§3.9) so controlled-value-set constraints can't drift
  from what the loader/validator enforce.
- **Validate proposal bundles before staging**, exactly as the sail does today, so the "a violating
  bundle can't be staged" invariant survives the engine swap.

**Reuse:** treat "validate against the shape catalogue, reject with structured violations" as a
core platform service with a **pluggable validator backend** (sail-integrated where available,
library-at-the-write-boundary otherwise). It pairs with provenance as the two non-negotiable trust
gates.

---

# Part 4 — Suggested rebuild sequence

A pragmatic order that front-loads the generic core and defers domain choices:

1. **Config spine first** — `GraphConfig` (prefix + graph names), `GovernanceVocab`, and the
   structured-store connector abstraction (§3.8). These unlock everything downstream (§1.1–1.2 seams).
2. **Generic platform core** — graph client, sandbox pool, agent runtime (with injected
   descriptions/prompt), proposal engine (config-driven routing), checkpoints (Snapshotter
   interface), server + UI. Lift with the non-functional patterns baked in (§3).
3. **Structured-store connectors** — implement the `StructuredStore` interface (read + optional
   snapshot + capabilities) + the scheme-based locator registry (§3.8); ship the embedded
   (SQLite/DuckDB) connector first, add federated ones (Postgres, warehouse, time-series) as the
   domain needs them.
4. **Domain plug-in interfaces** — define the seams as interfaces (entity canonicalizer, source
   parser, seed-source queries, `RelationSchema`, grounding allowlist).
5. **First domain instance** — supply the ontology contract + the plug-in implementations.

The safety-corpus experiment (§1.5) is the template for validating step 4: a second domain
source should require only new content, no engine changes.

---

# Part 5 — How to update this map

This map is verified at `928936e`. To refresh after further POC changes:

1. `git diff --stat 928936e..HEAD` to see what moved.
2. Re-audit only the touched slices (the six functional slices in Part 1 + the non-functional
   set map cleanly to directories: `internal/{graph,store,sandbox,checkpoint}`,
   `internal/{proposal,agent}`, `cmd/server`+`webapp`, `internal/nist`+`cmd/loader`+`ontology`,
   `extraction/src/.../*` extraction vs. mining modules).
3. Update the **Verified at** stamp and any changed file:line references.
4. Watch for *new* domain leakage into 🟢 modules — the greps that validated this map are in
   each slice's audit (e.g. `grep -rniE 'salt|fluoride|nist|reactor|molten|flibe' <module>`);
   a new hit in a green module is a regression against reusability.
