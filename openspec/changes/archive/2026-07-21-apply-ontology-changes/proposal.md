# Proposal: apply-ontology-changes

## Why

Chunk 8 (`mine-ontology-candidates`) lands the *propose* half of the self-evolving-ontology
demo: it writes reviewable `msr:ChangeProposal` resources to `urn:msr:staging` with their
proposed triples in `urn:msr:proposal/{id}`, all `pending` and invisible to the core dataset.
Nothing yet *disposes* of them — a reviewer cannot see the queue, and an approved concept
never reaches the graphs the analysis agent reads, so the agent still can't answer a
`solubility` question. This change lands the **governance backend** (chunk 9, milestone M5):
an HTTP JSON API that serves the review queue, renders a proposal as a diff, and on approval
**routes the bundle's triples into the right core graphs by type**, bumps the ontology
version, and records the decision — closing the evolution loop at the API level. It also adds
**checkpoint/restore** of the whole store so the whole demo can be rolled back and re-run.
The API surface it defines is the contract chunk 10's review UI consumes.

## What Changes

- **Proposal review + disposition HTTP API (the chunk-10 contract)**: add JSON routes to
  the existing `server` binary — `GET /api/proposals?status=` (the queue, filtered by review
  status), `GET /api/proposals/{id}` (a proposal's proposed triples + its evidence + the
  affected ontology neighborhood, for the diff render), `PUT /api/proposals/{id}/graph`
  (edit — replace the proposal graph's triples), `POST /api/proposals/{id}/approve`, and
  `POST /api/proposals/{id}/reject`. These read staging/proposal graphs through the graph
  client's raw (staging-inclusive) path — never the core-dataset contract — and are stateless
  like `/api/chat`. Handlers are tested against a fake graph client; the graph package's
  wiring stays the only place that knows the endpoint.
- **Typed-routing promotion on approve**: a proposal is **one bundle** of nodes + edges the
  reviewer accepts as a whole, but its triples belong to different core graphs. Approve
  therefore routes **by what each triple is** — `skos:Concept` subjects and SKOS-predicate
  triples → `urn:msr:vocab`; TBox axioms (`owl:Class`/`owl:ObjectProperty`/
  `owl:DatatypeProperty` declarations, `rdfs:subClassOf`, domain/range, and
  `msr:PhysicalProperty` individuals with their `quantityKind`/`canonicalUnit`) →
  `urn:msr:ontology`; everything else (individuals, edges between individuals) →
  `urn:msr:data` — implemented as three filtered `INSERT { GRAPH <dest> … } WHERE { GRAPH
  <proposal> … }` copies. The **proposal graph is kept in place as the audit record** (never
  deleted), and because the copies are additive and IRIs are deterministic, **re-running an
  approval is idempotent** (required so a restored-then-re-approved demo works). The mixed
  `graphite` bundle (a `Moderator` class + `moderatedBy` property → ontology, the `graphite`
  individual → data) is the routing correctness case.
- **Ontology version bump + decision provenance**: on approval the engine **minor-bumps
  `owl:versionInfo` on the ontology header inside `urn:msr:ontology`** (seed `0.4.0` after the
  chunk-7/8 TBox additions) via a scoped DELETE/INSERT, and appends a PROV **approval
  activity** (the reviewer, a timestamp
  supplied by the request, and a link to the approved proposal) to `urn:msr:staging` — the
  audit trail lives with the proposal history, outside the analysis dataset. The version bump
  is the **no-push-signal mechanism**: the live agent rebuilds its cached KG-schema prompt on
  the next request when its per-request `owl:versionInfo` check sees the change (chunk 4), and
  the batch Python jobs read the version at their next run start — so an approved
  `solubility` becomes answerable with no restart and no explicit cache invalidation. Reject
  flips status to `rejected` (triples stay in staging, core untouched, **no version bump**);
  edit replaces the proposal graph's triples in place.
- **Whole-store checkpoint & restore (demo rollback)**: `checkpoint` = a full GraphDB
  repository export (TriG, **all** named graphs incl. staging/proposals) + a copy of the
  SQLite measurement store + the recorded ontology version, written under
  `data/checkpoints/{label}/`; `restore` = clear the repository → import the TriG → put the
  SQLite copy back, so proposal statuses, back-populated instances, and text-derived rows all
  revert together in one atomic move. Exposed as `GET|POST /api/checkpoints` and
  `POST /api/checkpoints/{label}/restore`, plus `make checkpoint` / `make restore` wrappers.
  A checkpoint → approve → restore round-trip must leave graph triple counts and the SQLite
  content identical to the pre-checkpoint state (version back, proposals `pending` again).
- **Repository-level graph ops added to the graph client**: the client currently exposes
  per-graph `PutGraph` and additive `Update`; this change adds the repository-scoped
  export / import / clear primitives checkpoint/restore needs, keeping GraphDB endpoint
  knowledge confined to the `graph` package.

## Capabilities

### New Capabilities

- `proposal-review-api`: the stateless HTTP JSON API the review UI consumes — queue
  (`GET /api/proposals?status=`), detail with proposed triples + evidence + affected
  ontology neighborhood (`GET /api/proposals/{id}`), edit (`PUT /api/proposals/{id}/graph`),
  approve, and reject; staging-inclusive reads only; method/route/error contract; handlers
  tested against a fake graph client.
- `approval-typed-routing`: promote an approved proposal's bundle into the core graphs by
  routing each triple by type (SKOS → vocab, TBox → ontology, individuals/edges → data) via
  three filtered `INSERT { GRAPH <dest> } WHERE { GRAPH <proposal> }` copies, keeping the
  proposal graph as an audit record, idempotent across re-runs, with the mixed TBox+instance
  bundle correct.
- `proposal-lifecycle`: the review-status state machine chunk 8 defers to chunk 9 — approve
  transitions `pending → approved`, minor-bumps `owl:versionInfo` in `urn:msr:ontology`, and
  writes a PROV approval activity (reviewer, timestamp, proposal link) to `urn:msr:staging`;
  reject transitions `pending → rejected` leaving the core graphs and version untouched; edit
  replaces the proposal graph's triples; invalid transitions are refused.
- `store-checkpoint-restore`: checkpoint the whole store (full-repo TriG export of all named
  graphs + SQLite copy + ontology version → `data/checkpoints/{label}/`) and restore it
  (clear → import TriG → put SQLite copy back), with a round-trip that leaves graph triple
  counts and SQLite content identical; exposed as the checkpoint API and `make checkpoint` /
  `make restore` wrappers.

### Modified Capabilities

None. This change **consumes** the chunk-8 contract (`change-proposal-schema` +
`proposal-staging` — the `msr:ChangeProposal` resource, its `msr:reviewStatus` and
`msr:hasProposalGraph` link, and the two-graph staging model) without changing its
requirements — chunk 8's specs explicitly state status transitions are chunk 9's job. It adds
routes to the `server` binary additively (the `chat-api` `/api/chat` contract is unchanged),
reads through the existing `core-dataset-access` client's raw escape hatch, grows the
`container-stack` `server` image additively, and its approval PROV activity **conforms to**
the `provenance-model` vocabulary without adding or altering a shape. It writes into
`urn:msr:ontology`/`urn:msr:vocab`/`urn:msr:data` in shapes the merged `shacl-validation`
sail already validates (routed triples were authored to conform at mine time), so it adds no
shape.

## Impact

- **New code**: proposal review/disposition HTTP handlers and a checkpoint/restore handler in
  `cmd/server/`; a typed-routing approval engine + proposal-lifecycle transitions + a
  checkpoint/restore engine (likely `internal/proposal` and `internal/checkpoint`, resolved
  in design); repository-scoped export / import / clear primitives added to `internal/graph`;
  a Go test suite (handler tests with a fake graph client; lifecycle + routing + checkpoint
  round-trip integration tests against the dockerized GraphDB).
- **Server**: `newMux` gains the `/api/proposals…` and `/api/checkpoints…` routes alongside
  `/api/chat` and `/healthz`; the server process gains write access to the `msr` repo for
  approvals/version-bumps and read/copy access to the SQLite file for checkpoints (the chat
  request path stays read-only per `chat-api`).
- **Graph store**: approval copies proposal triples into `urn:msr:ontology` / `urn:msr:vocab`
  / `urn:msr:data`; `urn:msr:ontology`'s `owl:versionInfo` is bumped; `urn:msr:staging` gains
  a PROV approval-activity node per approval and updated `msr:reviewStatus` values; proposal
  graphs are retained. Restore clears and re-imports the entire repository.
- **SQLite**: checkpoint copies `msr.db`; restore replaces it. No schema change and no
  runtime writes outside checkpoint/restore.
- **Make targets**: `make checkpoint` and `make restore` added additively to the root
  `Makefile`.
- **Reuses (does not author)**: the chunk-1 `graph.Client` (adding repo-level ops), the
  chunk-8 `msr:ChangeProposal` schema + staging model, the `provenance-model` PROV-O
  vocabulary, and the chunk-4 per-request `owl:versionInfo` prompt-cache check (the consumer
  of the bump — unchanged here).
- **Depends on**: chunk 1 (`bootstrap-graph-infra` — the stores, the graph client, the
  core-dataset contract), chunk 8 (`mine-ontology-candidates` — the `ChangeProposal` schema
  and the staged proposals this API disposes), and the trust foundation (`provenance-model` —
  the approval activity's vocabulary; `shacl-validation` — the shapes the routed triples must
  still satisfy). Reads the version consumed by chunk 4 (`analysis-agent`). **Downstream**:
  chunk 10's review UI consumes this API surface verbatim; the density/evolution demo drives
  it end-to-end.
