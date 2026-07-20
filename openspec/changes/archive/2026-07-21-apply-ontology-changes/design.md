# Design: apply-ontology-changes

## Context

Chunk 8 (landed on `main`) writes `msr:ChangeProposal` resources to `urn:msr:staging` carrying
`msr:kind`, `msr:reviewStatus "pending"`, `msr:term`, `msr:docFrequency`, `msr:hasEvidence`
`msr:Evidence` nodes (which reuse `msr:citedIn` + `msr:startOffset`/`msr:endOffset`), and an
`msr:hasProposalGraph` link (an `xsd:anyURI` **literal**, not an object property), with the
proposed triples in a dedicated `urn:msr:proposal/{id}` named graph. IRIs are deterministic:
the resource is `msrd:proposal-{kind}-{term-slug}` and the proposal graph is
`urn:msr:proposal/{kind}-{term-slug}`, so the API's `{id}` path segment is `{kind}-{term-slug}`
(e.g. `property-solubility`). Both staging and proposal graphs are deliberately excluded from
the core-dataset read (`graph.Client.Select` restricts to
`urn:msr:ontology`/`urn:msr:data`/`urn:msr:vocab`; they are reachable only via `SelectRaw` or
an explicit `GRAPH` scope). The proposal schema states plainly that **status transitions and
promotion are chunk 9's responsibility**.

Chunk 8 is the Python extraction service, so it never touched the **Go** `graph.Client`: that
client still exports only `Ontology`/`Data`/`Vocab`/`Staging`/`Provenance` constants and a
`PutGraph` allowlist of the first four — there is **no** `Proposal` constant and proposal
graphs are dynamic (`urn:msr:proposal/{kind}-{term-slug}`). This change therefore reaches
proposal graphs through `Update` (explicit `GRAPH` target, not allowlist-checked) and
`SelectRaw`, never `PutGraph`.

The existing `server` binary already serves stateless `POST /api/chat` (SSE) and `/healthz`
via `newMux` (`cmd/server/handler.go`), backed by a `graph.Client` that is the only component
knowing the GraphDB endpoint. The ontology header inside `urn:msr:ontology` carries
`owl:versionInfo "0.4.0"` (bumped from the `0.3.0` seed by the chunk-7/8 TBox additions); the
agent's `DetectVersion` runs one cheap SELECT for that value at
the start of every chat request and rebuilds its cached KG-schema prompt when it changes — so
a version bump is the only signal needed to make an approved concept answerable. The PROV-O
TBox (`prov:Activity`, `prov:Agent`, `prov:wasAssociatedWith` "…human reviewer",
`prov:startedAtTime`) is already in `ontology/msr.ttl`. The `graph.Client` exposes core/raw
`Select`, additive `Update` (which already classifies GraphDB SHACL rejections into a typed
`ValidationError`), and destructive per-graph `PutGraph`; it has **no** repository-level
export/import/clear yet.

Constraints: writes to the `msr` repo pass the merged `shacl-validation` `ShaclSail` at commit
time; the chat request path must stay read-only on SQLite (`chat-api`); GraphDB endpoint
knowledge stays confined to the `graph` package; clients/handlers are tested against fakes,
integration tests run against the dockerized GraphDB.

## Goals / Non-Goals

**Goals:**
- Serve the proposal review queue + a diff-ready proposal detail over a stateless JSON API,
  reading only through the staging-inclusive path.
- Promote an approved proposal's bundle into the correct core graphs **by triple type**, as
  one atomic, idempotent operation that also bumps the ontology version and records the
  decision.
- Support reject and edit as the remaining lifecycle transitions.
- Checkpoint and restore the whole store (graph + SQLite) for demo rollback, with a byte-level
  round-trip guarantee.
- Define the API surface as the chunk-10 contract.

**Non-Goals:**
- The review **UI** (chunk 10) — this change is the backend only.
- Instance auto-accept — chunk 8 writes instance-kind candidates straight to `urn:msr:data`;
  they never enter this engine.
- EntityRuler push signals or back-population triggers — both are covered by the next batch
  re-run reading the bumped version (run-model contract); nothing here pushes.
- Per-change undo — checkpoints are the demo rollback path (per-change DELETE-where-in-proposal
  stays possible but unbuilt).
- Authn/authz on the API — out of scope for the POC (noted as a risk).

## Decisions

### D1 — Typed routing as three filtered `INSERT … WHERE` copies in one UPDATE
Approve routes each proposal triple to its destination graph **in-store**, never round-tripping
triples through Go:
- **vocab** ← subjects that are `skos:Concept` and SKOS-predicate triples (`skos:prefLabel`,
  `skos:altLabel`, `skos:broader`, `skos:definition`, …).
- **ontology** ← TBox axioms: `owl:Class`/`owl:ObjectProperty`/`owl:DatatypeProperty`
  declarations, `rdfs:subClassOf`, `rdfs:domain`/`rdfs:range`, and `msr:PhysicalProperty`
  individuals with their `msr:quantityKind`/`msr:canonicalUnit`.
- **data** ← everything else (individuals and edges between individuals).

Each is `INSERT { GRAPH <dest> { ?s ?p ?o } } WHERE { GRAPH <urn:msr:proposal/{id}> { ?s ?p ?o }
FILTER(<classifier>) }`, the three ops plus the version bump, decision provenance, and status
flip concatenated with `;` into **one** SPARQL UPDATE request — GraphDB runs a single request
as one transaction, so the SHACL sail validates the whole promotion atomically and a rejection
rolls back everything (proposal stays `pending`). The **proposal graph is not deleted** — it is
the audit record. *Alternative rejected:* parse the proposal graph in Go and route triple-by-
triple — needless data round-trip, and re-implements classification the store can express
declaratively.

### D2 — Version bump by scoped DELETE/INSERT, guarded on the status transition
The bump is `DELETE { GRAPH <urn:msr:ontology> { ?o owl:versionInfo ?old } } INSERT { … ?new }
WHERE { GRAPH <urn:msr:ontology> { ?o a owl:Ontology ; owl:versionInfo ?old } }` with `?new`
computed in Go: parse `major.minor.patch` (dropping any `-seed`/pre-release suffix), increment
**minor**, reset patch (`0.4.0 → 0.5.0`). The bump fires **only on a real `pending → approved`
transition** — re-approving an already-`approved` proposal (or approving after a restore that
reset it to `pending`) is guarded so the version is never double-bumped for one decision, which
is what keeps re-approval idempotent (see D5). *Alternative rejected:* `PutGraph` the whole
ontology graph — destructive graph-replace requiring a full re-serialization just to touch one
literal.

### D3 — Approval provenance goes to `urn:msr:staging`, not `urn:msr:provenance`
The decision record is `urn:msr:run:approve/{id}` a `prov:Activity`, `prov:wasAssociatedWith` a
reviewer `prov:Agent`, `prov:startedAtTime` a request-supplied timestamp, linked to the
approved `msr:ChangeProposal`. It is written into `urn:msr:staging` so the governance audit
trail lives with the proposal history, **outside** the analysis dataset (`urn:msr:provenance`
is the pipeline-generation lineage graph; approvals are human governance events). This reuses
the existing PROV-O TBox (no new vocabulary) and conforms to `provenance-model`.

### D4 — Repository-level ops added to `graph.Client`; SQLite copied via `VACUUM INTO`
Checkpoint/restore needs whole-repo primitives the client lacks, added inside the `graph`
package to keep endpoint knowledge contained, all against the RDF4J
`/repositories/{repo}/statements` endpoint:
- **Export** — `GET` with `Accept: application/x-trig` → all named graphs (incl. staging/
  proposals) as one TriG document.
- **Clear** — `DELETE` (no subject/predicate/object/context) → empties the repo.
- **Import** — `POST` with `Content-Type: application/x-trig` → loads the TriG back.

SQLite is snapshotted with **`VACUUM INTO '<target>'`** on a **dedicated** connection (not the
chat path's `mode=ro&query_only` connection): it produces a consistent single-file snapshot
regardless of concurrent readers, is supported by `modernc.org/sqlite`, and needs no C backup
API. Restore replaces the live `msr.db` with the checkpoint copy. A checkpoint manifest records
the ontology version. *Alternative rejected:* raw file copy — not guaranteed consistent under a
concurrent writer; `VACUUM INTO` is the documented hot-snapshot.

### D5 — Idempotency across the board (the restore→re-approve demo requires it)
Routing copies are additive `INSERT`; proposal IRIs are deterministic (chunk 8) so re-copying
inserts no duplicates. The version bump is guarded on the status transition (D2). Status flips
are set-to-constant. Together, running an approval twice — or after a restore that reset the
proposal to `pending` — yields exactly one bump per genuine decision and stable triple counts.
The checkpoint round-trip (checkpoint → approve → restore) must return graph triple counts and
SQLite content to the pre-checkpoint state; this is the headline demo-rollback test.

### D6 — Package layout: thin handlers, engines in `internal/`
`cmd/server/` gains proposal + checkpoint HTTP handlers (JSON), registered in `newMux`
alongside `/api/chat`. The promotion/lifecycle engine lands in `internal/proposal` and the
checkpoint/restore engine in `internal/checkpoint`; handlers depend on **small interfaces**
(the subset of graph/SQLite ops they use) so they are unit-tested against a fake graph client —
mirroring how `internal/agent` tools are tested — while lifecycle/routing/round-trip correctness
is covered by integration tests against the dockerized GraphDB.

### D7 — Proposal detail returns a bounded, one-hop ontology neighborhood
`GET /api/proposals/{id}` returns three parts for the diff render: the proposal graph's triples
(`SelectRaw` over `GRAPH <urn:msr:proposal/{id}>`, the graph IRI taken from the request `{id}`
and cross-checked against the resource's `msr:hasProposalGraph` literal), the evidence (the
resource's `msr:hasEvidence` `msr:Evidence` nodes — sentence text plus the reused
`msr:citedIn` document and `msr:startOffset`/`msr:endOffset`), and the **affected ontology
neighborhood** — a one-hop `SelectRaw`/CONSTRUCT of core-graph triples about the IRIs the
proposal references (e.g. a proposed subclass's broader class, a proposed property's
`quantityKind`). Bounded to one hop so the payload stays diff-sized.
*Alternative rejected:* return the whole ontology and diff client-side — unbounded payload for a
focused change.

### D8 — Checkpoint label is filesystem-sanitized
`{label}` becomes a path segment under `data/checkpoints/{label}/`, so it is validated to a
conservative charset (alphanumerics, dash, underscore) and rejected otherwise, preventing path
traversal / escape out of the checkpoints directory.

## Risks / Trade-offs

- **A routed triple violates SHACL mid-approval** → the single-transaction UPDATE (D1) rolls
  back entirely; the handler surfaces the typed `ValidationError` (already produced by
  `graph.Update`) and the proposal stays `pending`. Core graphs are never left half-promoted.
- **Double version bump on re-approval / restore-then-approve** → guarded on the real status
  transition (D2/D5); re-approval is a no-op on the version.
- **Restore while a batch job is writing** (extraction/mine) → graph clear+import and the
  SQLite swap race a concurrent writer. Mitigation: batch jobs are one-shot and not running
  during the interactive demo; documented as an operational constraint, not enforced with
  locking for the POC.
- **`VACUUM INTO` target already exists** → treated as an error / removed first; checkpoints
  are per-label directories so labels must be fresh or explicitly overwritten.
- **Version-string parsing on a non-semver value** → the parser tolerates a missing patch and
  drops pre-release suffixes; a value it cannot parse fails the approval loudly rather than
  writing a malformed version.
- **No API authn** → acceptable for the POC/demo; the server is not internet-exposed. Flagged
  for any production hardening.
- **Large-repo TriG import cost on restore** → acceptable at demo scale (thousands of triples);
  not optimized.

## Migration Plan

Additive. New routes register beside the existing ones in `newMux`; no existing endpoint,
schema, or spec requirement changes. The ontology `owl:versionInfo` moves from `0.4.0` only
when a reviewer approves a proposal at runtime — no migration of stored data. `make checkpoint`
/ `make restore` are new wrappers. Rollback of the *feature* is removal of the new routes/
packages; rollback of *data* is exactly the checkpoint/restore this change introduces.

## Open Questions

- Whether `PUT /api/proposals/{id}/graph` (edit) should re-run the QUDT-allowlist guard that
  chunk 8 applies at mine time, or defer all validation to the SHACL sail at approve time.
  Leaning **defer to approve-time SHACL** (single validation gate; edits are reviewer-driven),
  but the chunk-8 final pass may argue for echoing the guard for faster reviewer feedback.
- Exact response JSON field names for the proposal detail neighborhood — to be aligned with
  chunk 10's rendering needs during the joint final pass over the three sibling specs.
