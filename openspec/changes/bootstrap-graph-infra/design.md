# Design: bootstrap-graph-infra

## Context

The repo currently holds only the materialized seed artifacts (`ontology/msr.ttl`, `ontology/vocab.ttl`, `ontology/example-flibe.ttl`) and documentation. Chunks 2–10 of the POC all assume running stores, an established repo layout, and a shared graph client that enforces the core-dataset contract. This change builds that foundation.

Binding contracts (from `docs/ARCHITECTURE.md` → *Runtime contracts* and `docs/implementation_plan.md` → *Cross-cutting contracts*):

- Named graphs: core = `urn:msr:ontology` + `urn:msr:data` + `urn:msr:vocab`; staging = `urn:msr:staging` + `urn:msr:proposal/{id}`. GraphDB evaluates a no-dataset query against the union of **all** graphs, so core-only reads are a query-layer contract, not a store setting.
- SQLite: one shared `measurement_value` table; journal mode `DELETE` (WAL would break the sandboxes' read-only mounts); `busy_timeout` on every connection; batch jobs are the only writers.
- Seed files load with graph-replace semantics (Graph Store `PUT`); re-runs are idempotent.
- Run model: everything in containers (Compose); one-shot jobs behind `make` targets; only GraphDB and the server are long-running.

## Goals / Non-Goals

**Goals:**

- `make up` brings up the whole solution: GraphDB (repo `msr`, inference disabled), `server` and `extraction` image scaffolds, the sandbox base image built, shared data volume mounted.
- `make load-seed` loads the three seed files into their named graphs idempotently and ensures `urn:msr:staging` exists.
- SQLite initialized with the `measurement_value` DDL and pinned runtime settings via an idempotent init script later chunks extend.
- `internal/graph`: the shared Go client every later chunk uses — core reads see exactly the three core graphs; writes target explicit named graphs.
- Repo layout per the contracts (`cmd/`, `internal/`, `extraction/`, `webapp/` placeholder, `data/`, `testdata/`).
- Go tests pinning the two load-bearing behaviors: staging exclusion and seed-load idempotency.

**Non-Goals:**

- No NIST data loading or salt canonicalization (chunk 2 — including `internal/store` query logic; chunk 1 only creates the schema).
- No sandbox pool logic (chunk 3) — only the base *image* is built here.
- No agent, chat API, LLM config, or prompt builder (chunk 4).
- No extraction pipeline code (chunks 5–8) — the `extraction/` project is a scaffold (pyproject + empty package) proving the image builds.
- No frontend (chunk 10); the `server` scaffold serves a health endpoint only.
- No checkpoint/restore (chunk 9).

## Decisions

### D1 — Core-dataset enforcement via SPARQL protocol dataset parameters

The contract is "FROM injection": every core read is evaluated against exactly the three core graphs. Implementation: the client sends the three core graphs as **both** `default-graph-uri` **and** `named-graph-uri` SPARQL 1.1 Protocol parameters on every core read, and **rejects** queries that carry their own `FROM`/`FROM NAMED` clause (case-insensitive token scan) so a query can't smuggle in a wider dataset. The rejection error names `SelectRaw` as the escape hatch for deliberately wider reads.

- *Why also `named-graph-uri`?* With only `default-graph-uri`, the dataset's named-graph set is empty, so any `GRAPH ?g { … }` pattern silently matches nothing — the worst failure mode for agent-generated SPARQL. Passing the same three graphs as `named-graph-uri` keeps `GRAPH` patterns working within the core set (e.g., "does this term live in vocab or ontology?") while changing nothing about isolation: named set = default set.
- *Why reject rather than override?* The SPARQL 1.1 Protocol says protocol dataset parameters take precedence over query-string dataset clauses — so a smuggled `FROM <urn:msr:staging>` would be silently ignored, returning confusing results. A loud error that points at `SelectRaw` is defense-in-depth (no reliance on GraphDB implementing that precedence correctly) and better DX.
- *Why not textual `FROM` injection?* Splicing clauses into arbitrary SPARQL text requires locating the insertion point (after the projection, before `WHERE`) and breaks on subqueries and comments. Protocol parameters achieve the identical dataset per SPARQL 1.1 Protocol semantics with zero parsing. The acceptance test pins the observable behavior (staging invisible), which is the actual contract.
- *Why not a GraphDB store setting?* None exists — GraphDB's no-dataset default is union-of-all-graphs (documented). That's the entire reason this client exists.
- *Why not a separate staging repository (or store)?* Store-level isolation is real, but promotion stops being atomic: approving a proposal is currently one SPARQL UPDATE copying triples between graphs in one transaction; cross-repo it becomes two transactions with a half-applied state on crash. The review surface's proposal-vs-core diffs would need federation (`SERVICE <repository:…>`), and chunk 9's checkpoint/restore would have to snapshot two repos consistently. Graph-level ACLs would remove the client-discipline residual risk, but GraphDB's fine-grained access control is Enterprise-only (confirmed unavailable in the 11.x Free edition) and the POC pins the free tier.

API surface (consumed by chunks 2, 4, 6–9):

- `Select(ctx, query)` — core-dataset read (the default; the agent and all normal reads use this).
- `SelectRaw(ctx, query)` — no dataset restriction; needed by the review/staging surfaces (chunk 9) and by the acceptance test that proves the difference.
- `Update(ctx, update)` — SPARQL UPDATE (writers name explicit `GRAPH` targets).
- `PutGraph(ctx, graphIRI, turtle)` — Graph Store Protocol `PUT` (graph-replace, for seed loading).
- Graph IRIs exported as typed constants — no string literals at call sites.

### D2 — GraphDB repository created idempotently at bootstrap, inference disabled

`make up` (after compose health) ensures repo `msr` exists via GraphDB's REST API using a vendored repository-config TTL with **no ruleset**. Check-then-create, so re-running is a no-op. Inference is disabled per the architecture decision (staging isolation, traceability, low payoff) and is **fixed at creation** — changing it later means recreating the repo, which is deliberate: start disabled, opt in only by explicit rebuild.

- *Alternative — GraphDB's autocreate/import directory:* rejected; repo config as a committed TTL is explicit, reviewable, and pins the no-ruleset choice.

### D3 — Seed loading is a Go command using `internal/graph`, not curl in the Makefile

`make load-seed` runs `cmd/loader seed` (one-shot compose run), which `PUT`s each seed file to its named graph and ensures `urn:msr:staging` exists (creating it empty if absent). Graph Store `PUT` replaces the graph wholesale, so editing a seed file and re-running never leaves stale IRIs behind, and running twice yields identical triple counts (the acceptance criterion).

- *Why the loader binary and not curl?* It exercises `internal/graph`'s write path (the thing later chunks depend on), keeps HTTP details in one place, and gives the idempotency test a real code path. `cmd/loader` grows a `nist` subcommand in chunk 2; chunk 1 ships `seed` and `init-db`.

### D4 — SQLite init: embedded DDL in `internal/store`, applied via `cmd/loader init-db`

The `measurement_value` DDL (exactly the contract schema) lives as embedded SQL in `internal/store`, applied with `CREATE TABLE IF NOT EXISTS` semantics by `cmd/loader init-db` (invoked by `make load-seed` or standalone). The store package exposes the connection-opening helper that pins `journal_mode=DELETE` and sets `busy_timeout` — later writers (chunks 2, 7) open through it, so the runtime contract is code, not convention.

- *Why not a `.sql` file piped to the sqlite3 CLI?* Container images are minimal and may lack the CLI; an embedded-DDL Go path is the same code path later chunks extend (the contract says chunk 1 owns the idempotent init script and later chunks extend it).

### D5 — Compose topology and images

| Service | Image | Chunk-1 state |
|---------|-------|---------------|
| `graphdb` | `ontotext/graphdb` (pinned 11.x tag) | full — healthcheck, data volume, license mount |
| `server` | multi-stage Go build (distroless/alpine final) | scaffold — `/healthz` only; Docker socket mount declared for chunk 3 |
| `loader` | same Go build image, one-shot (compose profile) | `seed` + `init-db` subcommands |
| `extraction` | Python 3.12 + pyproject scaffold | builds and runs `--help`; real pipeline lands chunks 5–8 |
| sandbox base | `python:3.12-slim` + numpy/pandas, non-root user | image built + tagged; pool logic is chunk 3 |

Since GraphDB 11.0 even the Free edition requires a license file (the built-in free license was removed; a free license is requested from the Graphwise website). The developer places it at `graphdb.license` in the repo root — gitignored, never committed — and compose mounts it read-only into the container's GraphDB home. Free-tier limits (max 5 repositories, 2 concurrent queries, no fine-grained access control) are fine for this single-user POC.

One multi-stage Dockerfile builds both Go binaries (`server`, `loader`); `server` and `loader` are two compose services over the same image. The shared data directory is a **host bind mount** (`./data`) rather than a named volume: tests and host tools need to see the SQLite file and corpus cache directly, and chunk 3's sandboxes bind-mount the same directory read-only. `data/` stays gitignored except `data/nist/` (vendored in chunk 2).

### D6 — Test strategy: integration tests against the compose GraphDB, guarded by env

The chunk's acceptance tests (staging exclusion, FLiBe measurement reachable via the client, load idempotency) need a real GraphDB — the exclusion behavior *is* a GraphDB behavior. Tests read `GRAPHDB_URL` (default `http://localhost:7200`); a shared test helper checks reachability once, and what happens when GraphDB is unreachable depends on `GRAPHDB_REQUIRED`:

- `GRAPHDB_REQUIRED` unset (bare `go test ./...` without the stack): integration tests `t.Skip` with the reason — the casual path stays green.
- `GRAPHDB_REQUIRED=1` (set by `make test`): unreachable GraphDB is `t.Fatal`, not a skip — the acceptance gate cannot go green without actually running the acceptance tests.

Skipping applies only to connection-refused/timeout. A GraphDB that responds but errors (HTTP 5xx, missing repo) fails the test in both modes — that is a broken environment, not an absent one. Pure-Go unit tests (dataset-clause rejection, request construction) run everywhere unconditionally.

- *Alternative — testcontainers-go:* rejected for the POC; the compose stack already provisions GraphDB, and a second provisioning path means a second repo-config to keep in sync.

## Risks / Trade-offs

- **The client is convention-enforced** — any code doing raw HTTP to GraphDB bypasses the core-dataset contract. → Mitigation: `internal/graph` is the only package importing the SPARQL endpoint config; the staging-exclusion acceptance test pins the behavior; `SelectRaw` exists so nobody has a reason to go around the client.
- **Ruleset is fixed at repo creation** — enabling inference later requires recreating the repo. → Accepted deliberately (architecture decision); chunk 9's checkpoint export makes a rebuild cheap if ever needed.
- **Graph Store `PUT` is destructive by design** (replaces the whole target graph) — a wrong graph IRI wipes good data. → Mitigation: graph IRIs are typed constants in `internal/graph`; `PutGraph` refuses IRIs outside the known set.
- **Protocol-parameter dataset vs. the plan's "FROM injection" wording** — same observable contract, different mechanism. If GraphDB's parameter handling ever surprises us, the fallback is textual injection behind the same client API; the acceptance test would catch a semantic difference. → Mitigation: the test asserts behavior, not mechanism.
- **Host bind mount for `data/`** — file ownership/permissions differ across host platforms (macOS dev vs CI). → Mitigation: containers run with a fixed non-root UID; the init script creates directories with group-writable permissions; documented in the README.
- **Scaffold drift** — `server`/`extraction` scaffolds ship placeholder behavior that later chunks replace; their Dockerfiles could ossify wrong assumptions. → Mitigation: scaffolds kept minimal (health endpoint, `--help`), no speculative structure.
- **GraphDB license file is per-registrant and must never be committed** — since 11.0 the Free edition needs a requested license file, so a fresh clone won't start GraphDB out of the box. → Mitigation: `graphdb.license` is gitignored; `make up` preflights its existence and fails with a message pointing at the Graphwise free-license request form; the README documents the one-time request step.

## Migration Plan

Greenfield — no existing deployment. Bootstrap order: `make up` (compose up → wait healthy → ensure repo `msr`) → `make load-seed` (init SQLite, `PUT` three seed graphs, ensure staging) → `make test`. Rollback = `docker compose down -v` plus deleting `data/` contents; everything is re-creatable from the repo. Root config (`Makefile`, `docker-compose.yml`) is owned by this chunk; later chunks extend it additively per the parallel-execution contract.

## Open Questions

- **GraphDB image tag** — pin the latest `ontotext/graphdb` 11.x tag at implementation time (docs reference 11.2). Note the free tier does **not** run license-less on 11.x: a requested free-license file is required and provided gitignored per D5.
- **Go module path** — set at implementation (`github.com/…/msr-graph` vs a local module name); no downstream contract depends on it.
- **Sandbox base image contents** — numpy/pandas pinned versions; final list is chunk 3's to adjust, chunk 1 just needs the image to build and import both.
