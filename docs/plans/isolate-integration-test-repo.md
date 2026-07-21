# Plan: Isolate integration tests on a disposable `msr-test` repo

**Status:** Approved 2026-07-21, not yet implemented.
**How to execute:** Start a fresh session and run the `orchestrate` skill pointed at this file
(e.g. *"orchestrate the plan in `docs/plans/isolate-integration-test-repo.md`"*). This is a
direct implementation — **no OpenSpec change/artifacts requested**. Decompose the tasks below
into the waves given, delegate to coder/infra-coder/tester agents, merge after each wave, and
run the Verify & Review gate. This brief is self-contained; you do not need prior chat context.

---

## Why (incident that motivates this)

On 2026-07-21 an integration-test run against the **live `msr` GraphDB repo** destroyed
`urn:msr:data` (74,275 triples → 1). Mechanism:

- `requireGraphDB()` is duplicated in `internal/graph/testhelper_test.go`,
  `internal/proposal/testhelper_test.go`, and `internal/checkpoint/testhelper_test.go`, each
  hardcoding `integrationRepo = "msr"`. It connects whenever GraphDB is reachable (skips only on
  connection failure), so any `go test` against those packages hits the **production** repo.
- `internal/checkpoint/roundtrip_integration_test.go`
  (`TestCheckpointRoundTrip_ApproveThenRestoreReverts`) calls `Restore`, which does a
  **whole-repo `ClearRepo` (DELETE everything) + `ImportRepo`**. Run concurrently with the
  `internal/proposal` approve tests under default `go test ./...` package parallelism, the
  interleaving cleared the repo; the sole survivor in `urn:msr:data` was a concurrent approve
  test's nanosecond-suffixed `graphite`/`Moderator` fixture.

`make test` already pins `-p 1` (serializes packages), but that only reduces cross-package
collisions — it does **not** stop the destructive tests from targeting live `msr`. The real fix
is to point integration tests at a disposable repo and hard-refuse `msr`.

Recovery for reference: `bash backups/backup.sh` snapshots the whole graphdb-data volume +
`data/msr.db` + corpus traces to `backups/<timestamp>/`; each backup's `MANIFEST.txt` has
per-graph counts; `bash backups/restore.sh backups/<timestamp>` restores it.

## Goal

`go test` (any invocation, whenever GraphDB is reachable) must never read or mutate the
production `msr` repo. Integration tests run against a disposable `msr-test` repo, with a hard
guard that refuses to run destructive tests against `msr`.

## Headline acceptance test (proves it's fixed)

Snapshot the production `msr` per-graph counts (ontology/data/vocab/staging/provenance) →
run a full `make test` (with GraphDB reachable) → the `msr` counts are **byte-identical**
afterward. Additionally: with `GRAPHDB_TEST_REPO=msr` (or unset such that it resolves to the
prod repo), the destructive integration tests **skip with a loud message**, never run.

---

## Design decisions

- **D1 — Test repo from env.** The shared helper resolves the target repo from
  `GRAPHDB_TEST_REPO` (default **`msr-test`**), never a hardcoded `"msr"`. `GRAPHDB_URL` still
  selects the server (default `http://localhost:7200`).
- **D2 — Hard safety guard.** If the resolved test repo equals the production repo — literally
  `"msr"`, or whatever `GRAPHDB_REPO` is set to — the helper **skips with a loud, explicit
  message** ("refusing to run destructive integration tests against the production repo %q; set
  GRAPHDB_TEST_REPO to a disposable repo (see make test-repo)"). This alone would have prevented
  the incident. (Skip, not fatal, so a bare `go test ./...` on a dev box without a test repo
  provisioned is non-destructive and green-by-skip, consistent with the existing
  reachable-but-absent behavior — but see D2a.)
  - **D2a — reachable-but-absent test repo.** Preserve the existing D6 contract nuance: if
    GraphDB is reachable but the *test* repo doesn't exist, skip with "run `make test-repo`
    first" (unless `GRAPHDB_REQUIRED=1`, then fatal). Do not treat an absent test repo as a
    broken environment the way the current helper treats an absent `msr`.
- **D3 — Consolidate the 3 duplicated helpers into `internal/testutil`.** Chunk-1 design D6
  already anticipated this ("later chunks may promote this helper to a shared package such as
  internal/testutil"). Put the shared logic in a normal (non-`_test`) package
  `internal/testutil` that does **not** import `testing`: expose a function that returns
  `(client *graph.Client, action Decision)` where `Decision` conveys run / skip(reason) /
  fatal(reason). Each package keeps a tiny `testhelper_test.go` wrapper (`requireGraphDB(t)`)
  that calls it and does `t.Skip`/`t.Fatal`. This removes the drift and gives one home for the
  D1/D2 logic. `internal/testutil` may import `internal/graph`.
- **D4 — Provisioning.** Generalize `scripts/ensure-repo.sh` to take a `REPO_ID` env var
  (default `"msr"`, so `make up`'s call is unchanged) so it can create a SHACL-enabled
  `msr-test` from `deploy/graphdb/msr-repo-config.ttl` (the config's repo id may need
  templating — the config TTL currently names `msr`; parameterize or generate it for the test
  repo). Add a **`make test-repo`** target that: (a) resets/creates `msr-test` via
  `REPO_ID=msr-test scripts/ensure-repo.sh` (drop-then-create so each test run starts clean),
  and (b) seeds ontology/vocab into it via `cmd/loader seed` with `GRAPHDB_REPO=msr-test`.
- **D5 — `make test` wiring.** `make test` first runs `make test-repo`, then
  `GRAPHDB_TEST_REPO=msr-test GRAPHDB_REQUIRED=1 SANDBOX_DOCKER_REQUIRED=1 go test -p 1 ./...`.
  Keep `-p 1` (cheap defense-in-depth; and collisions now only harm the throwaway repo).
- **D6 — Docs.** README + `docs/ARCHITECTURE.md`: integration tests run against `msr-test`
  (provisioned by `make test-repo`); never point them at `msr`; explain `GRAPHDB_TEST_REPO`.

## Non-goals

- Do not change the production `make up` / `ensure-repo.sh` behavior for `msr` (REPO_ID must
  default to `msr`).
- Do not rewrite the integration tests themselves; only redirect which repo they target.

---

## Task breakdown (files)

1. **`internal/testutil` (new package):** shared reachability/guard/repo-resolution helper
   (D1/D2/D2a/D3), no `testing` import; returns a decision struct. Unit test with an `httptest`
   server for the resolution + guard logic (repo resolves from `GRAPHDB_TEST_REPO`; guard trips
   when it equals `GRAPHDB_REPO`/`"msr"`).
2. **`scripts/ensure-repo.sh` (+ `scripts/ensure-repo_test.go`):** `REPO_ID` env (default
   `msr`); ensure the config TTL is applied for the chosen repo id; add a reset path for the
   test repo. Keep idempotent-create for `msr`.
3. **`Makefile`:** add `test-repo` target (reset+create+seed `msr-test`); make `test` depend on
   it and export `GRAPHDB_TEST_REPO=msr-test`.
4. **`internal/graph/testhelper_test.go`, `internal/proposal/testhelper_test.go`,
   `internal/checkpoint/testhelper_test.go`:** replace the duplicated bodies with thin wrappers
   delegating to `internal/testutil` (drop the hardcoded `integrationRepo = "msr"`).
5. **`README.md`, `docs/ARCHITECTURE.md`:** document the test-repo convention.

## Waves

- **Wave 1 (parallel):**
  - `infra-coder` — tasks 2 + 3 (`scripts/ensure-repo.sh`, `scripts/ensure-repo_test.go`,
    `Makefile`) + task 5 docs.
  - `coder` — task 1 (`internal/testutil` + its unit test).
  (Independent; path-disjoint.)
- **Wave 2 (parallel):**
  - `coder` — task 4 (swap the 3 `testhelper_test.go` copies onto `internal/testutil`).
  - `tester` — verification (see below), written against the acceptance criteria.
- **Verify & Review gate** (verifier optional since no OpenSpec artifacts; run code-reviewer +
  security-reviewer — the guard and repo provisioning are the security-relevant surface).

## Validation / Definition of done

- `go build ./...`, `go vet ./...` pass.
- `make test-repo` provisions a SHACL-enabled, seeded `msr-test`.
- `make test` runs the full suite green **against `msr-test`**, with `-p 1`.
- **Headline:** production `msr` per-graph counts are byte-identical before vs. after a full
  `make test` run (query `SELECT (COUNT(*) AS ?n) WHERE { GRAPH <urn:msr:g> { ?s ?p ?o } }` for
  each of ontology/data/vocab/staging/provenance).
- With the test repo resolving to `msr` (guard input), the destructive integration tests skip
  with the loud refusal message (assert in a testutil unit test).
- Docs updated.

## Gotchas / notes for the implementer

- `requireGraphDB`'s current reachability probe hits `/repositories/{repo}/size`; keep that but
  against the resolved test repo. Distinguish "GraphDB down" (skip/fatal per `GRAPHDB_REQUIRED`)
  from "test repo absent" (skip: run `make test-repo`).
- `deploy/graphdb/msr-repo-config.ttl` hardcodes the repo id `msr`; creating `msr-test` needs
  either a templated config or a copy with the id swapped — handle in `ensure-repo.sh`.
- The SHACL shapes load into the reserved `http://rdf4j.org/schema/rdf4j#SHACLShapeGraph`;
  `ensure-repo.sh` already does this for `msr` — make sure it targets the chosen `REPO_ID`.
- Keep `internal/testutil` free of `testing` so it isn't flagged; the `_test.go` wrappers own
  the `t.Skip`/`t.Fatal` calls.
- After implementing, a full `make test` will create/reset `msr-test` — that's fine and
  intended; just never let `GRAPHDB_TEST_REPO` default to `msr`.
