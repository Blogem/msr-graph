# Provenance & Validation — High-Level Design

Status: **design / intent** (not yet an OpenSpec change; see *Plan integration* for the
chunks this spawns). Companion to `ARCHITECTURE.md` and `IMPLEMENTATION_PLAN.md`.

## Why this document exists

An audit of the specs and implementation found that the project's central principle —
**every fact in the graph and every answer the agent gives must be traceable to a
source** — is *not* actually a requirement anywhere. Provenance appears only as per-artifact
rules (the NIST loader emits `prov:wasDerivedFrom`) and as design prose ("a grounded,
traceable answer"); nothing binds it into a cross-cutting, verifiable invariant. Separately,
the ontology's declared `rdfs:domain`/`rdfs:range` constraints are **never enforced** —
inference is off and there are no SHACL shapes, so malformed triples enter silently.

Concretely today:

- The agent can return an answer — even a numeric one — with **zero** provenance events;
  emission depends on the model choosing to ground and happening to name a SPARQL variable a
  certain way (`internal/agent/loop.go`, `sparql.go`).
- Loader-produced NIST measurements carry `wasDerivedFrom <dataset>` but **no `citedIn`
  document**, and the dataset DOI is load-order-dependent (`cmd/loader/nist.go`).
- Nothing validates triples entering the graph against the ontology's own constraints.

This design makes provenance a **first-class, declaratively-enforced invariant** and adds the
**validation layer** that turns the ontology's constraints into real, write-time gates. It is
deliberately scoped to *provenance + validation* — no new domain schema is invented here (see
§4 on where the safety/requirements ambition actually lives).

## Principles

1. **Provenance everywhere, enforced — not conventional.** No asserted fact enters the core
   dataset, and no answer leaves the agent, without a resolvable link to its source. A
   requirement checked by machinery, not a habit.
2. **Validation is declarative and lives at the write boundary.** Data-quality and provenance
   invariants are SHACL shapes the database enforces on commit, not procedural checks
   scattered through loaders.
3. **Only real data — nothing fabricated for demonstration.** Every node and edge traces to a
   real source: a dataset, a document, or a real human/tool `Activity`. A capability we cannot
   populate from real molten-salt-reactor data is **deferred until a real source exists**, not
   seeded with synthetic examples to make a demo look complete. Non-negotiable for a
   provenance POC — synthetic data in a *traceability* demo is self-defeating.
4. **Human-in-the-loop is demonstrated, not fully built (POC scope).** The *enforcement* gate
   is SHACL: triples may enter the graph as long as they pass validation. The HITL review
   surface (chunk 9) exists to *show how humans participate*; the production governance
   workflow is defined later. "Core = trusted" is redefined for the POC as
   **"core = SHACL-valid."**

## 1. Provenance model

### 1.1 Primary mechanism — property-level PROV-O, SHACL-required

Every **fact-bearing individual** carries explicit provenance edges, and SHACL makes them
mandatory (§2). Adopt a small, standard slice of [PROV-O](https://www.w3.org/TR/prov-o/):

- `prov:wasDerivedFrom` → the `msr:Dataset` or `msr:Document` a fact came from (already
  partly present on measurements; made complete and required).
- `prov:wasGeneratedBy` → the `prov:Activity` that produced it (a loader run, an extraction
  run, an approval), carrying `prov:startedAtTime`/`endedAtTime`, `prov:wasAssociatedWith` a
  `prov:Agent` (`agent:loader@<version>`, `agent:extraction@<version>`, or a human reviewer),
  and the `owl:versionInfo` in effect.
- `msr:dataLocator` is retained as the convenient, queryable surface the agent already uses;
  the gap to close is that it is **complete and required**, not optional. `msr:citedIn` is
  **not** part of this: NIST SRD-27 carries no per-row citation, so the predicate stays
  TBox-declared but unused until chunk-7 citation extraction can derive it truthfully (design
  D3).

Property-level is the enforced baseline because it is minimally disruptive (no graph-layout
refactor) and demonstrates the principle directly: every node the agent touches has a
`wasDerivedFrom` an engineer can follow.

### 1.2 Complementary mechanism — provenance by named graph (batch/audit dimension)

Because GraphDB is a quad store, per-run/per-source audit data lives in a single
append-only graph, **`urn:msr:provenance`** — not a graph per run or per source. This
complements §1.1, does not replace it, and is what gives true **per-run lineage**: "which
run(s) produced fact F?" is answerable by a query, not just "a run happened at time T."

Two activity IRIs split the idempotent (`urn:msr:data`) and audit (`urn:msr:provenance`)
concerns:

- A **stable, per-pipeline** `prov:Activity` — `msrd:activity-<pipeline>` — is typed once in
  `urn:msr:data` (`prov:wasAssociatedWith` its `prov:Agent`, `owl:versionInfo`, no
  timestamps), so it is a set-semantics no-op across re-runs. Every fact keeps its
  deterministic `prov:wasGeneratedBy msrd:activity-<pipeline>` edge in `urn:msr:data` — this
  single, stable edge is what the agent's core-scoped grounding sees.
- Each run additionally mints a **per-run** `prov:Activity` **node** — the run identifier
  `urn:msr:run:<pipeline>/<ts>` used as a node IRI, never a graph name — written into
  `urn:msr:provenance` with `prov:wasAssociatedWith`, `prov:startedAtTime`/`endedAtTime`, and
  `owl:versionInfo`. For every fact the run asserts (including facts already present in
  `urn:msr:data` — "touched," not "first-created," semantics), the run also writes `<fact>
  prov:wasGeneratedBy <urn:msr:run:<pipeline>/<ts>>` into `urn:msr:provenance`. The
  generation edges a fact accumulates across runs — one per run that asserted it — *are*
  its lineage.

`urn:msr:provenance` is excluded from core reads (outside `graph.CoreGraphs`, exactly like
`urn:msr:staging`), so grounding/answer-time queries are unaffected and continue to see
exactly one `wasGeneratedBy` edge per fact; per-run lineage is opt-in via an explicit `GRAPH
<urn:msr:provenance>` query. The graph is explicitly append-only/monotonic and persists
across reseeds of `urn:msr:data` — that persistence is what makes cross-run lineage
meaningful. Since POC data is disposable, a full teardown (`ensure-repo`) clears it along
with everything else. (RDF-star statement-level annotation is available in GraphDB but is
*not* adopted — it complicates the whole SPARQL surface for marginal gain at POC scale.)

**Supersedes design D8.** This single-graph model (`provenance-run-lineage`, design
D1–D2) replaces the archived `provenance-model` design D8, which gave each source or run
its own named graph (`urn:msr:src:nist-srd27`, `urn:msr:run:extraction/<ts>`, …) holding a
single `Activity` record. D8 could record only that a run happened, never *which* facts it
touched, so per-run lineage was unrecoverable; it also left one new `urn:msr:run:*` graph
per load cluttering the graph list. The `urn:msr:src:*` per-source graph is removed
outright, not merged in: the `Dataset` node it duplicated already lives, self-contained, in
`urn:msr:data`.

### 1.3 Three enforcement points

Provenance "everywhere" means all three, not just the graph:

| Point | Today | Target |
|-------|-------|--------|
| **Write-time** (facts entering the graph) | conventional; no check | SHACL rejects any fact-bearing individual lacking required provenance (§2) |
| **Answer-time** (agent → user) | best-effort, prompt-driven; can be absent | the agent **stamps every answer grounded-vs-ungrounded**; a grounded answer carries the provenance chain of the facts it used; ungrounded answers are explicitly marked. A first-class SSE event, enforced in the loop, not left to the model |
| **Compute-time** (`run_python` results) | script visible, but the number is untethered | the `run_python` provenance references the `dataLocator`(s) the script read, so a computed number is tied to the grounded rows it derived from |

## 2. Validation layer — SHACL in GraphDB

**GraphDB supports SHACL natively** via the underlying RDF4J SHACL engine (`ShaclSail`) — a
repository capability, not roll-your-own:

- Enabled **per repository at creation time** (a repo-config flag / the ShaclSail) — so
  `scripts/ensure-repo.sh` must create the `msr` repo with SHACL enabled.
- Shapes live in a **reserved shapes graph**; loading/updating shapes is a graph update.
- Validation runs **on transaction commit**: a violating write is **rejected** with a
  validation report — exactly the write-time gate principle 1 needs.
- Coverage is **SHACL Core plus SPARQL-based constraints**, with some engine limitations;
  sufficient for the shapes below. Bulk loads can be validated incrementally or
  load-then-validate to manage cost. Works fine with inference **off** (our configuration).

> Implementation note: confirm the exact repo-config parameter and shapes-graph IRI against
> the pinned GraphDB version (11.4.2) before relying on it.

### Shape catalogue (initial)

**Provenance invariants** (enforce §1):
- `msr:PropertyMeasurement` — `prov:wasDerivedFrom` minCount 1; `msr:dataLocator` minCount 1;
  `msr:forProperty`, `msr:ofSalt`, `msr:hasUnit`, `msr:equationForm` all required. (No
  `msr:citedIn` constraint — the loader never emits it; citation is deferred to chunk 7 per
  design D3.)
- `msr:Mention` — `msr:inDocument`, `msr:startOffset`, `msr:endOffset`, `msr:surfaceForm`
  required; `msr:linksTo` target-kind constraint.

**Data-quality invariants** (turn declared TBox constraints into real gates):
- Units constrained to the QUDT allowlist (`sh:in` over `ontology/qudt-units.json`).
- Valid-temperature-range present and `validTempMin ≤ validTempMax`.
- `linksTo` may only reference an existing concept/class/individual of the expected kind.

## 3. Human-in-the-loop (chunk 9)

Per principle 4: SHACL is the **enforcement** gate; chunk 9's review UI is a **demonstration**
of human participation, not a hard promotion barrier. Machine-derived triples (NER mentions,
mined candidates, text-derived measurements) **may write to core** provided they pass SHACL —
they no longer need to sit behind a built-out approval workflow to satisfy the trust story,
because provenance + validation already guarantee they are attributable and well-formed. The
review surface still shows a human approving/editing/rejecting proposals and renders the
provenance + ontology-neighbourhood diff (the point of the demo), and the PROV `Agent` on an
approval Activity records who did it. The production governance workflow is out of scope.

## 4. Where the safety / requirements ambition lives

This design does **not** add a requirements/validation/safety schema. That ambition — a
regulatory/safety knowledge branch with real traceability — is realized by ingesting the
**real IAEA safety documentation** (`ingest-iaea-safety`, chunk 11, the self-evolving `Safety`
ontology branch: `SafetyFunction`, `Confinement`, `DefenceInDepth`, `DesignBasis`,
`Requirement`), driven entirely by real IAEA text via the same extraction + evolution loop.
No bespoke "digital thread" schema is invented, and nothing is hand-seeded (principle 3).
When that branch is ingested, it inherits the provenance (§1) and validation (§2) established
here for free. IAEA usage restrictions are acceptable for this non-commercial hobby POC
(attribution, no substantial verbatim redistribution — see `DATA_SCOPE.md` §4).

## 5. Plan integration (see IMPLEMENTATION_PLAN.md)

This intent is **larger than one OpenSpec change**. It inserts a new **Phase P3.5 — Trust
Foundation** = **provenance (12) + SHACL (13)**, which **gates P4**: both operate on the real
data we already hold, so the pipelines that mass-produce facts (chunks 7–8) are born
provenance-complete and SHACL-valid rather than retrofitted.

**Trust sequence:** `ground-demo-in-real-docs` → **12 `provenance-model`** → **13
`shacl-validation`** — *make the data real → make it provenanced → enforce it*.
`ground-demo-in-real-docs` lands first as a prerequisite: it removes the hand-curated seed
A-Box (`ontology/example-flibe.ttl`) and re-grounds the agent on real `msr:Mention →
msr:linksTo → salt` links, so `provenance-model` operates on an all-real, seed-free graph and
only has to layer the provenance invariant on top — no seed-coexistence hedging (see
`openspec/changes/provenance-model/design.md` D9). Within `provenance-model`, the `Activity`
IRI a fact references via `wasGeneratedBy` is deterministic per pipeline/source, keeping that
edge byte-stable across re-runs for fact-store idempotency; the wall-clock-timestamped
`Activity` record (agent, timestamps, ontology version) is asserted separately as a per-run
node in the single append-only `urn:msr:provenance` graph, alongside one
`prov:wasGeneratedBy` lineage edge per fact the run asserts (`provenance-run-lineage`, §1.2,
superseding design D8's per-run/per-source named-graph split).

- **12 `provenance-model`** — PROV-O slice in the ontology; complete + required provenance on
  all fact-bearing individuals; a single `urn:msr:provenance` audit graph with per-run
  `Activity` nodes and generation-lineage edges (§1.2); retrofit the
  NIST loader (self-contained dataset/DOI + provenance edges — no `msr:citedIn`, deferred to
  chunk 7 per design D3) and seed; **answer-time** enforcement in the agent
  (grounded-vs-ungrounded stamp + provenance-chain SSE event, gated in the loop) and
  **compute-time** locator linkage for `run_python`.
- **13 `shacl-validation`** — enable GraphDB ShaclSail (bootstrap change to `ensure-repo.sh`);
  author the shape catalogue (§2); wire validation into the write path; bulk-load strategy.
  Depends on 12 (shapes encode the provenance model).

Milestone **M3.5 — trust foundation:** every asserted fact carries resolvable provenance,
enforced by SHACL at commit (violations rejected); the agent marks every answer
grounded-or-ungrounded and returns the provenance chain of the facts it used.

Downstream impact: chunks 7–8 (P4) inherit the provenance contract and must pass SHACL; chunk
9 (P5) is reframed per §3; chunk 10 (P6) renders the grounded/ungrounded badge and provenance
chips in the trace timeline. Chunk 11 (IAEA safety) benefits automatically (§4).

## 6. Resolved decisions

- **Only real data.** No fabricated/seeded data. Capabilities without a real source are
  deferred (this is why no requirements/safety schema is invented here — it waits for the real
  IAEA ingest, §4).
- **All data adheres; no migration.** POC data is disposable and replaced wholesale; every
  writer emits provenance-complete, SHACL-valid data, no grandfathering (chunk-6 NER is
  retrofitted, not exempted).
- **Provenance is the requirement; standards are opportunistic.** "Show where it came from" is
  non-negotiable — PROV-O throughout. Any further standards alignment (e.g. for the future
  IAEA safety branch) is `rdfs:seeAlso`, asserted only where a clean mapping exists, never
  forced or imported.

Remaining implementation detail (decide at build): **bulk-load validation cost** — validate
incrementally vs. load-then-validate for the NIST/extraction batch writes; measure.
