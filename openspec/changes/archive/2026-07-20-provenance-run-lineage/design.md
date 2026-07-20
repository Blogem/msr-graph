# Design — provenance-run-lineage

Companion to the archived `provenance-model` change. This change revisits that
change's design **D8** (idempotent stable activity + timestamped per-run *graph*),
which knowingly precluded per-run lineage. The goal here is per-run lineage while
preserving the `urn:msr:data` idempotency that D8 protected.

## The core insight

`urn:msr:data` idempotency is a property of the **fact triples**: deterministic,
content-derived IRIs mean a re-run re-asserts identical triples, a set-semantics
no-op. Per-run lineage triples are the opposite by construction — a per-run activity
IRI carries the run timestamp, so the activity node and every `<fact> wasGeneratedBy
<run>` edge referencing it are **net-new every run** and never duplicate. They cannot
break idempotency; they only *accumulate*. The only question is **where the growing
lineage data lives** so that `urn:msr:data` stays byte-stable. Answer: a single
separate graph.

## Decisions

### D1 — Two activity IRIs: stable (in data) + per-run (in provenance)

- `urn:msr:data` keeps, per fact, `prov:wasGeneratedBy msrd:activity-<pipeline>` (the
  **stable** per-pipeline IRI). This IRI is additionally typed once in `urn:msr:data`
  — `msrd:activity-<pipeline> a prov:Activity ; prov:wasAssociatedWith
  <agent:<pipeline>@<version>> ; owl:versionInfo "<version>"` — with **no timestamps**,
  so it stays a set-semantics no-op across re-runs. This is the edge the agent's
  core-scoped grounding sees, unchanged from the archived model.
- Each run additionally mints a **per-run** activity IRI, reusing the existing run
  identifier as a node: `urn:msr:run:<pipeline>/<ts>` (e.g.
  `urn:msr:run:loader/2026-07-20T…`). It is written into `urn:msr:provenance` typed
  `a prov:Activity` with `prov:wasAssociatedWith <agent:<pipeline>@<version>>`,
  `prov:startedAtTime`/`prov:endedAtTime`, and `owl:versionInfo`. These are the same
  facets the archived run-graph `Activity` record carried; the difference is the IRI is
  now per-run (timestamp in the IRI) and it is a **node**, not a graph name.

Relating the two is optional; both share the same `agent:<pipeline>@<version>`. No hard
`Activity`→`Activity` edge is required (PROV has no clean activity-specialization
predicate and the lineage query does not need one).

### D2 — One `urn:msr:provenance` graph, not a graph per run/source

A distinct named graph per run bought nothing for lineage: the fact→run edge's
**object** (`urn:msr:run:<pipeline>/<ts>`) already identifies the run, so "what did run
R assert" is `?f prov:wasGeneratedBy <R>` regardless of which graph the edge sits in.
Per-run graphs only added the graph-list clutter that motivated this change. So all
per-run activity records and all generation edges go in a single `urn:msr:provenance`
graph, and `urn:msr:run:<pipeline>/<ts>` / `urn:msr:src:*` are removed as *graph* names.

The `urn:msr:src:*` `Dataset` write was redundant — the self-contained
`msrd:nist-srd27 a msr:Dataset ; dcterms:identifier "doi:…"` node already lives in
`urn:msr:data` (loader `buildInsertData`) and re-asserts idempotently there — so it is
simply dropped, not moved.

**Trade-off:** rollback of a single run is no longer `DROP GRAPH <run>`; it becomes a
pattern delete `DELETE WHERE { GRAPH <urn:msr:provenance> { ?f prov:wasGeneratedBy <R> .
<R> ?p ?o } }`. Acceptable at POC scale, and rolling back the *facts* was never clean
anyway (they are deduped in `urn:msr:data` and may have been asserted by other runs).

### D3 — "Touched"/asserted semantics, not "first-created"

A run emits `<fact> prov:wasGeneratedBy <run>` for **every** fact it asserts, whether or
not that fact was already present in `urn:msr:data`. Rationale:

- It is the honest, verifiable claim: "this run asserted this fact at this time."
- It needs **no read-before-write** — the writer already has the fact IRIs it is
  emitting; it emits a parallel generation edge for each.
- It yields full history: a fact asserted by three runs carries three generation edges.

Rejected for now: **"which run first *created* the fact"** semantics. That requires an
existence check (a pre-write diff) per fact, answers a strictly narrower question, and
would model a no-op run's touch as `prov:used` rather than `prov:wasGeneratedBy`. Defer
until a concrete consumer needs "creating run" specifically; the touched-semantics log is
a strict superset from which "earliest run" is derivable by `MIN(startedAtTime)` anyway.

### D4 — The idempotency boundary moves to `urn:msr:provenance`

- `urn:msr:data` — byte-stable across re-runs (fact triples, `wasDerivedFrom`, the stable
  `wasGeneratedBy` edge, the typed stable `Activity`, the `Dataset` node — all
  deterministic). The existing "triple count unchanged after a second run" tests hold.
- `urn:msr:provenance` — **explicitly append-only / monotonic**: a re-run appends a new
  per-run `Activity` plus its generation edges. This is the store the archived model
  exempted as `urn:msr:run:*`; it is now `urn:msr:provenance`. Within a single run the
  provenance write is deterministic given that run's `<ts>`, so a genuine re-send of the
  same run is still a no-op; only a new wall-clock run appends.

### D5 — Core reads and the agent are unaffected

`urn:msr:provenance` is not added to `graph.CoreGraphs`, so the client's core-read
enforcement excludes it exactly as it excludes `urn:msr:staging`. Grounding and
answer-time queries continue to see the single stable `wasGeneratedBy` per fact — the
multi-valued lineage never leaks into a grounding result and the answer-time provenance
chain is unchanged. Per-run lineage is opt-in via an explicit `GRAPH <urn:msr:provenance>`
query (or `SelectRaw`). A typed `graph.Provenance = "urn:msr:provenance"` constant is
added for call sites; writes use additive SPARQL `Update` with an explicit `GRAPH`
target (never `PutGraph`), so no known-graph allowlist change is required.

Example lineage queries (opt-in, provenance-scoped):

```sparql
# Which runs asserted fact F, and when?
SELECT ?run ?t WHERE {
  GRAPH <urn:msr:provenance> {
    <F> prov:wasGeneratedBy ?run . ?run prov:startedAtTime ?t
  }
} ORDER BY ?t

# What did run R assert?
SELECT ?f WHERE {
  GRAPH <urn:msr:provenance> { ?f prov:wasGeneratedBy <R> }
}
```

### D6 — Lifecycle

`urn:msr:provenance` persists across loads — that persistence is what makes cross-run
lineage meaningful — and is **not** cleared when `urn:msr:data` is wholesale-replaced by
a reseed. A generation edge whose fact was later removed from `urn:msr:data` is retained
as historical audit truth ("run R asserted F at T"); dangling references into a
replaced data graph are acceptable for an append-only audit log. A full teardown (repo
recreation via `ensure-repo`) clears it along with everything else.
