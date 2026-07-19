# Proposal: bootstrap-graph-infra

## Why

Every chunk of the MSR knowledge-graph POC (structured loading, NER, ontology evolution, the analysis agent) depends on running stores, a seeded ontology, and a safe read path — none of which exist yet. This change stands up the local infrastructure and loads the already-materialized seed ontology/vocabulary/A-Box so the design becomes live and queryable, unblocking both the structured and unstructured tracks (P2+).

## What Changes

- **Docker Compose for the whole solution**: GraphDB (repository `msr`, inference disabled), `server` and `extraction` image scaffolds, the sandbox base image (minimal Python + numpy/pandas), and a shared data volume — per the run-model contract in `docs/implementation_plan.md`.
- **Repo layout** established per the cross-cutting contracts (`cmd/`, `internal/`, `extraction/`, `data/`, `testdata/`, `ontology/`).
- **SQLite initialization**: idempotent init script creating the shared `measurement_value` table, journal mode pinned to `DELETE` (WAL would break the sandboxes' read-only mounts), `busy_timeout` on every connection.
- **Named-graph bootstrap**: `msr.ttl` → `urn:msr:ontology`, `vocab.ttl` → `urn:msr:vocab`, `example-flibe.ttl` → `urn:msr:data`, loaded with graph-replace semantics (Graph Store `PUT`); `urn:msr:staging` created empty.
- **Shared `internal/graph` client with core-dataset `FROM` injection**: GraphDB has no store-side graph exclusion, so this client *is* the enforcement that keeps staging/proposal graphs invisible to core reads. Every later chunk reads and writes through it.
- **Make targets**: `make up` (stores live) and `make load-seed` (idempotent seed load).

## Capabilities

### New Capabilities

- `container-stack`: Docker Compose services, images, shared data volume, and the `make up` entry point that brings the whole solution up locally.
- `seed-graph-loading`: named-graph bootstrap of the seed ontology, vocabulary, and A-Box with graph-replace (idempotent) semantics via `make load-seed`, plus creation of the staging graph.
- `measurement-store`: SQLite initialization — `measurement_value` DDL, `DELETE` journal mode, `busy_timeout`, idempotent init script that later chunks extend.
- `core-dataset-access`: the shared Go graph client that injects the three core `FROM` clauses on reads (staging exclusion) and provides the write path to named graphs.

### Modified Capabilities

None — this is the first change; no existing specs.

## Impact

- **New code**: `internal/graph/` (Go client + tests), SQLite init script, `docker-compose.yml`, `Makefile`, Dockerfiles for `server`/`extraction`/sandbox base images.
- **Data**: `ontology/msr.ttl`, `ontology/vocab.ttl`, `ontology/example-flibe.ttl` (already materialized) become the loaded seed; `data/` volume layout established.
- **Dependencies**: Docker/Compose, GraphDB image, Go toolchain, SQLite. No LLM access needed in this chunk.
- **Downstream**: produces the compose file, Makefile, initialized stores, and `internal/graph` — the read/write path every later chunk (2–10) uses. Root config (`Makefile`, `docker-compose.yml`) is owned by this chunk; later chunks extend it additively.
