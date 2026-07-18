# Tasks: bootstrap-graph-infra

## 1. Repo scaffolding

- [ ] 1.1 Initialize the Go module and create the contract layout: `cmd/loader/`, `cmd/server/`, `internal/graph/`, `internal/store/`, `data/`, `testdata/`, `webapp/` placeholder
- [ ] 1.2 Create the `extraction/` Python 3.12 scaffold (pyproject.toml + empty package with a `--help` entry point)
- [ ] 1.3 Extend `.gitignore`: `graphdb.license`, `data/` (except `data/nist/`), `data/checkpoints/`, `data/corpus/`

## 2. Container stack

- [ ] 2.1 Write the multi-stage Go Dockerfile producing both `server` and `loader` binaries (distroless/alpine final stage)
- [ ] 2.2 Write the `extraction/` Dockerfile (Python 3.12 + pyproject scaffold; builds and runs `--help`)
- [ ] 2.3 Write the sandbox base image Dockerfile (`python:3.12-slim` + pinned numpy/pandas, non-root user) and tag it
- [ ] 2.4 Write `docker-compose.yml`: `graphdb` (pinned 11.x tag, healthcheck, data volume, read-only `graphdb.license` mount), `server` (health endpoint, Docker socket mount declared), `loader` (one-shot, compose profile), `extraction`; shared `./data` host bind mount; fixed non-root UID
- [ ] 2.5 Vendor the GraphDB repository-config TTL for repo `msr` with no ruleset (inference disabled)
- [ ] 2.6 Implement repo bootstrap: check-then-create repo `msr` via the GraphDB REST API using the vendored config (idempotent)
- [ ] 2.7 Write the `make up` target: preflight `graphdb.license` (fail with the Graphwise free-license pointer), compose up, wait for GraphDB healthy, ensure repo `msr`
- [ ] 2.8 Implement the `server` scaffold binary serving `/healthz` only

## 3. Graph client (`internal/graph`)

- [ ] 3.1 Export typed constants for the named-graph IRIs (`urn:msr:ontology`, `urn:msr:data`, `urn:msr:vocab`, `urn:msr:staging`) and the core set
- [ ] 3.2 Implement `Select(ctx, query)`: send the three core graphs as both `default-graph-uri` and `named-graph-uri` protocol parameters
- [ ] 3.3 Implement the dataset-clause guard: case-insensitive token scan rejecting `FROM`/`FROM NAMED` with an error naming `SelectRaw`
- [ ] 3.4 Implement `SelectRaw(ctx, query)` (no dataset restriction) and `Update(ctx, update)`
- [ ] 3.5 Implement `PutGraph(ctx, graphIRI, turtle)` via Graph Store Protocol `PUT`, refusing IRIs outside the exported constant set

## 4. Measurement store (`internal/store`)

- [ ] 4.1 Embed the contract `measurement_value` DDL and implement idempotent init (`CREATE TABLE IF NOT EXISTS`)
- [ ] 4.2 Implement the connection-opening helper pinning `journal_mode=DELETE` and `busy_timeout` on every connection

## 5. Loader and seed load

- [ ] 5.1 Implement `cmd/loader seed`: `PutGraph` each seed file to its named graph (`msr.ttl`→`urn:msr:ontology`, `vocab.ttl`→`urn:msr:vocab`, `example-flibe.ttl`→`urn:msr:data`); ensure `urn:msr:staging` exists without touching existing content
- [ ] 5.2 Implement `cmd/loader init-db` applying the `internal/store` init against the `./data` database path
- [ ] 5.3 Write the `make load-seed` target: one-shot compose run of `loader init-db` + `loader seed`

## 6. Tests

- [ ] 6.1 Write the shared integration-test helper: read `GRAPHDB_URL` (default `http://localhost:7200`), one reachability check; skip on connection-refused/timeout when `GRAPHDB_REQUIRED` is unset, `t.Fatal` when set; responding-but-erroring GraphDB fails in both modes
- [ ] 6.2 Unit tests (table-driven, no GraphDB): dataset-clause rejection (`FROM`, `from named`, case variants, clean queries pass), core-dataset request construction (both protocol parameter sets present), `PutGraph` unknown-IRI refusal without any HTTP request
- [ ] 6.3 Unit tests for `internal/store`: init idempotency (twice against the same file, rows preserved), opened connections report `journal_mode=delete` and non-zero `busy_timeout`, no `-wal`/`-shm` sidecar files after writes
- [ ] 6.4 Integration test — staging exclusion: insert a triple into `urn:msr:staging`; invisible via `Select`, visible via `SelectRaw` (pins why the client exists)
- [ ] 6.5 Integration test — `GRAPH ?g` patterns match within the core set (vocab term found with `?g` bound to `urn:msr:vocab`)
- [ ] 6.6 Integration test — the FLiBe example measurement is returned via the core-dataset client after `make load-seed`
- [ ] 6.7 Integration test — seed-load idempotency: run the seed load twice, per-graph triple counts identical; pre-existing staging triples preserved
- [ ] 6.8 Write the `make test` target running `GRAPHDB_REQUIRED=1 go test ./...`

## 7. Documentation

- [ ] 7.1 Write the README section: one-time Graphwise free-license request, `make up` / `make load-seed` / `make test` bootstrap order, `data/` bind-mount ownership note (macOS vs CI)
