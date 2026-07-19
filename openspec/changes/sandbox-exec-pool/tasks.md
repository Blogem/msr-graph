# Tasks: sandbox-exec-pool

## 1. Package scaffold and dependencies

- [ ] 1.1 Create the `internal/sandbox/` package
- [ ] 1.2 Add the Docker Go SDK (`github.com/docker/docker/client`) to `go.mod` and run `go mod tidy`; keep the dependency contained to `internal/sandbox`
- [ ] 1.3 Define config with the plan defaults: pool size N (default 3), per-container CPU / memory / pids limits, tmpfs `/tmp` size, and wall-clock timeout; read `MSR_DATA_HOST_DIR` and `MSR_SANDBOX_IMAGE` (default `msr-sandbox-base:latest`) from the environment, failing loudly if the host data dir is unset or not a directory

## 2. Container-runtime interface

- [ ] 2.1 Define the `Runtime` interface — `Create(ctx, ContainerSpec) (id, error)`, `Exec(ctx, id, script) (ExecResult, error)`, `Remove(ctx, id) error` — plus the `ContainerSpec` and `ExecResult{Stdout, Stderr, ExitCode}` types, with no Docker types leaking into the pool
- [ ] 2.2 Implement an in-memory `fakeRuntime` for tests: programmable per-call delays and errors, records create/exec/remove calls, and lets tests script exec output/exit codes and slow/hanging execs

## 3. Docker-backed runtime

- [ ] 3.1 Implement `dockerRuntime` against `unix:///var/run/docker.sock`: `Create` creates + starts a warm container from `MSR_SANDBOX_IMAGE` idling on a bounded no-op (`sleep <ttl>`, TTL ≫ the per-run wall-clock timeout) as PID 1, with a distinctive label (e.g. `msr.sandbox=1`) and `AutoRemove: true`, applying the full `ContainerSpec` — `--network none`, read-only root FS, tmpfs `/tmp` mounted `noexec`, non-root user (UID 10001), CPU/memory (no swap)/pids limits, dropped capabilities + no-new-privileges, and the `MSR_DATA_HOST_DIR → /data:ro` bind mount
- [ ] 3.4 Implement `Reap(ctx)` on the runtime: list all containers carrying the sandbox label and force-remove them (used by the startup sweep in 4.6)
- [ ] 3.2 Implement `Exec`: exec-create/attach `python -` with stdin attached, stream the script in, demultiplex stdout/stderr, and capture the exit code
- [ ] 3.3 Implement `Remove` as a force-remove (kills any live process); label/name every sandbox with a recognizable prefix so orphans are greppable

## 4. Pool

- [ ] 4.1 Implement `Pool` with a buffered `ready chan *Sandbox` of capacity N; `New` eagerly warms N containers and fails fast if the initial fill cannot complete
- [ ] 4.2 Implement `Run(ctx, script)`: acquire via channel receive (blocking when empty), run exactly one script, and return stdout verbatim + stderr + exit code; report non-zero exit as a normal result, reserving `error` for infrastructure/daemon failures
- [ ] 4.3 Implement single-use teardown + replenishment: after every run (success, failure, or timeout) force-remove the used container and spawn a goroutine that creates a fresh one and returns it to `ready`, with bounded-backoff retry + logging on create failure (never deadlock or spin)
- [ ] 4.4 Implement the wall-clock timeout: derive a per-run context deadline, and on expiry or caller cancellation cancel the exec and force-remove the container, returning a distinguishable timeout error
- [ ] 4.5 Implement `Close`: stop replenishment via a done signal and force-remove any idle containers still in the channel, leaving no orphaned sandboxes on graceful shutdown
- [ ] 4.6 Implement the startup sweep: `New` calls `Reap` (3.4) to force-remove any pre-existing labelled containers left by a prior server process *before* warming the pool, so a restarted server starts with no orphans (crash/kill/OOM/reboot recovery)

## 5. Stack configuration (container-stack)

- [ ] 5.1 Add `MSR_DATA_HOST_DIR: ${PWD}/data` and `MSR_SANDBOX_IMAGE: msr-sandbox-base:latest` to the `server` service environment in `docker-compose.yml` (additive; confirm the Docker socket mount from chunk 1 is present)
- [ ] 5.2 Confirm `make up` still builds/tags `msr-sandbox-base:latest` so the configured image reference resolves (no change expected — pin it with a comment referencing the pool's default)

## 6. Tests

- [ ] 6.1 Unit test — drain/replenish (fake runtime): after a run the used container is removed and a fresh one is returned; the pool returns to N ready; assert create/remove call ordering and counts
- [ ] 6.2 Unit test — single-use invariant: no container is ever handed out twice; each `Run` uses a distinct container id
- [ ] 6.3 Unit test — timeout: a hanging exec (fake) is cancelled at the wall-clock deadline, the container is force-removed, and `Run` returns a timeout error distinguishable from a normal non-zero exit
- [ ] 6.4 Unit test — result capture: stdout returned verbatim (unparsed); a non-zero exit returns captured stderr + code with a nil error
- [ ] 6.5 Unit test — concurrency under `-race`: more concurrent `Run` calls than N drain and refill the pool with no data race and no double-use; callers beyond N block until replenished
- [ ] 6.6 Unit test — `Close`: force-removes idle containers and stops replenishment (no goroutine leak / no post-close sends)
- [ ] 6.7 Unit test — startup sweep (fake runtime): `New` calls `Reap` before warming, so pre-existing labelled containers seeded in the fake are force-removed and the pool starts clean
- [ ] 6.8 Integration test (real Docker, gated + skippable like the GraphDB integration tests): a script reads `/data/msr.db` and returns JSON; a DB write attempt fails (read-only mount); an outbound network attempt fails (`--network none`); a root-FS write outside `/tmp` fails; numpy + pandas import successfully with `/tmp` mounted `noexec`; after a run the used container is gone and a fresh one is present (teardown verified); and a fresh `New` sweeps a leftover labelled container created out-of-band (orphan reaping across restart)
- [ ] 6.9 Wire the sandbox tests into the existing `make test` gate; ensure unit tests run and pass without Docker, and the integration test skips with a stated reason when Docker is unreachable and the required flag is unset (and fails when set)

## 7. Documentation

- [ ] 7.1 Document the pool in the package doc comment and the README: the `Run` contract, the isolation guarantees, the `MSR_DATA_HOST_DIR` / `MSR_SANDBOX_IMAGE` config, the sibling-mount host-path gotcha (D5), the restart/orphan-reaping behavior (D9: label + startup sweep + TTL backstop), and the Docker-socket trust ceiling (server = host-root-equivalent)
