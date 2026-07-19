# Design: sandbox-exec-pool

## Context

Chunk 4's analysis agent runs every computation as a model-authored Python script rather than doing arithmetic itself or pushing it into SQL — the script and its output appear verbatim in the chat trace. That makes the executor a trust boundary: the code is LLM-authored and effectively untrusted, so it must run with no network, no write path to the value store, no persistence between runs, and hard CPU/memory/time bounds.

Chunk 1 already delivered the pieces this change builds on:

- The **sandbox base image** `msr-sandbox-base:latest` (`docker/sandbox/Dockerfile`): `python:3.12-slim` + pinned numpy/pandas, fixed non-root UID/GID `10001`, `PYTHONDONTWRITEBYTECODE=1`. `make up` builds and tags it.
- The **`server` service** already mounts `/var/run/docker.sock` (declared in `docker-compose.yml` for this chunk) and runs as UID `10001` from a **distroless-static** image — no shell, no `docker` CLI.
- The **SQLite runtime contract**: journal mode `DELETE` (no `-wal`/`-shm` sidecars), so the data **directory** can be bind-mounted read-only; the DB lives at `/data/msr.db`.

Binding contracts (implementation plan → _Cross-cutting contracts_; `docs/ARCHITECTURE.md` → _Analysis execution — sandboxed Python pool_):

- A buffered channel `chan *Sandbox` (size N, default 3) _is_ the pool; acquire = receive; after **one** run the container is force-removed and a goroutine replenishes.
- Container spec: `--network none`, read-only root FS + tmpfs `/tmp`, non-root, CPU/mem/pids limits, wall-clock timeout; data directory bind-mounted read-only.
- Script contract: source on stdin (`docker exec -i … python -`), JSON on stdout, stderr + exit code captured.
- Sandboxes are **sibling** containers managed via the Docker socket.

## Goals / Non-Goals

**Goals:**

- `internal/sandbox` exposes `Run(ctx, script) → (stdout, stderr, exitCode, error)` — the whole surface chunk 4's `run_python` tool consumes.
- A warm pool of N containers; acquire is a channel receive; each container serves exactly one script then is force-removed and replaced by a fresh one, so no state survives between runs.
- Every sandbox is hardened: no network, read-only root FS + tmpfs `/tmp`, non-root, CPU/memory/pids limits, wall-clock timeout, and the data directory mounted **read-only**.
- The container-runtime dependency is an **injected interface** so pool lifecycle, timeout, and concurrency logic are unit-tested against a fake with no Docker present (and pass under `-race`); one integration test exercises the real isolation properties against Docker.
- The `server` service is configured to launch sandbox siblings with a correct host-resolved read-only `./data` mount and a known sandbox image reference.

**Non-Goals:**

- No agent loop, `run_python` tool wiring, LLM client, or trace/SSE events (chunk 4) — this change stops at the `Run` interface.
- No parsing or validation of the script's JSON result — the pool passes stdout through verbatim; interpreting it is the caller's job.
- No SQLite schema, seeding, or write path (chunks 1/2) — sandboxes only read `/data/msr.db`.
- No change to the sandbox **image** contents (chunk 1 owns the Dockerfile) beyond consuming it; no new Python libraries.
- No autoscaling, cross-host scheduling, or a general job queue — a single fixed-size local pool is the whole scope.

## Decisions

### D1 — The buffered channel _is_ the pool; destroy-after-one-use with goroutine replenishment

`Pool` holds `ready chan *Sandbox` of capacity N. `New` eagerly creates N warm sandboxes and sends them into the channel. `Run` receives one (`<-ready`, blocking when empty — this is the intended backpressure that bounds concurrency at N), execs the script, then **always** force-removes that container and, in a separate goroutine, creates a fresh sandbox and sends it back into `ready`. There is deliberately **no release/return-to-pool path** — a used container is never reused, so no artifact, tmpfs residue, or mutated state can leak from one script run to the next.

- _Why a channel instead of a mutex-guarded slice + condvar?_ The channel already encodes "block until one is available" and "hand exactly one owner each item"; it is the smallest correct primitive and keeps the race surface to a single well-tested Go construct. Reviewers of a security-sensitive component get less bespoke synchronization to audit.
- _Why destroy-after-one-use rather than reset-and-reuse?_ Guaranteeing a pristine environment by _resetting_ a container (clear tmpfs, kill stray processes, reset env) is a checklist that can silently rot; destroying it makes cleanliness structural, not procedural. The base image is small and containers are pre-warmed, so the cost is a background create, off the request path.
- _Alternative — `docker run` per request (no pool):_ rejected; container create + start on the request path adds latency to every agent step, and "warm pool" is an explicit contract. The pool moves that cost into replenishment goroutines.

### D2 — Container runtime behind an injected interface

All Docker interaction goes through a narrow interface the pool depends on:

```go
type Runtime interface {
    Create(ctx context.Context, spec ContainerSpec) (id string, err error) // create + start a warm, idle container
    Exec(ctx context.Context, id string, script []byte) (ExecResult, error) // one script on stdin; ExecResult{Stdout, Stderr, ExitCode}
    Remove(ctx context.Context, id string) error                            // force-remove (kills any live process)
    Reap(ctx context.Context) error                                         // force-remove all containers carrying the sandbox label (startup sweep, D9)
}
```

The pool contains no Docker types. Unit tests inject a `fakeRuntime` (in-memory, programmable delays/errors) to drive drain/replenish ordering, timeout behavior, and concurrency under `-race` with **no Docker daemon required**. Production injects `dockerRuntime`.

- _Why this seam and not mock the Docker SDK directly?_ A three-method domain interface is stable and expresses exactly what the pool needs; mocking the SDK's large surface couples tests to the client library and its call shapes.
- _Trade-off:_ the real `dockerRuntime` itself is only covered by the single Docker-backed integration test, not unit tests — accepted, because its logic is thin translation to the SDK; the risky logic (lifecycle, timeout, concurrency) lives in the pool and is fully unit-tested.

### D3 — Reach the daemon over the mounted socket via the official Docker Go SDK, not the CLI

`dockerRuntime` uses `github.com/docker/docker/client` against `unix:///var/run/docker.sock`. Create + start yields a warm container idling on a blocking no-op as PID 1 (e.g. `sleep infinity`); `Exec` uses the exec-create/attach API with stdin attached to stream the script in and demultiplex stdout/stderr out; `Remove` calls container-remove with `Force: true`.

- _Why not shell out to `docker exec -i`?_ The plan's `docker exec -i … python -` phrasing describes the **semantics** (exec into a warm container, feed the script on stdin), not the transport. The `server` image is **distroless-static** — no shell and no `docker` binary — so shelling out would mean adding a package manager/CLI to a deliberately minimal image. Talking to the socket directly keeps the image unchanged.
- _Why the official SDK over a hand-rolled unix-socket HTTP client?_ Exec attach uses Docker's hijacked, length-framed multiplexed stream for stdout/stderr; the SDK implements that framing correctly. Re-implementing it by hand is exactly the kind of subtle parsing bug to avoid in a security-sensitive path. Cost: a heavier dependency tree than the repo's current lean set — accepted for correctness.
- _Idle PID 1:_ a bounded `sleep <ttl>` (coreutils, present in `python:3.12-slim`; TTL ≫ the per-run timeout per D9's backstop) keeps the warm container alive under a read-only root FS with no writable state; the script then runs as a separate `exec` of `python -`.

### D4 — Hardened container spec, each control tied to a threat

`ContainerSpec` fixes every isolation control the runtime applies at create time:

| Control           | Setting                                              | Prevents                                                        |
| ----------------- | ---------------------------------------------------- | --------------------------------------------------------------- |
| Network           | `--network none`                                     | Exfiltration / callbacks / fetching payloads                    |
| Root FS           | read-only                                            | Persisting tools or tampering with the image at runtime         |
| Scratch           | tmpfs `/tmp` (size-capped, `noexec`)                 | Needing a writable FS while denying a persistent/executable one |
| User              | non-root (image UID `10001`)                         | Privilege escalation inside the container                       |
| Data mount        | `${host}/data → /data:ro`                            | Any write to the value store; DB is read-only, full stop        |
| CPU               | `--cpus` cap                                         | CPU exhaustion of the host                                      |
| Memory            | `--memory` (+ no swap) cap                           | Memory exhaustion / OOM of the host                             |
| PIDs              | `--pids-limit`                                       | Fork bombs                                                      |
| Time              | wall-clock timeout (D7)                              | Infinite loops / hangs                                          |
| Caps / privileges | drop all Linux capabilities, `no-new-privileges`     | Broadening the blast radius via kernel features                 |

The specific numeric limits (pool size N, CPU/mem/pids values, timeout, tmpfs size) are config with conservative defaults (N=3); this is a controlled POC, so the values are chosen for sanity, not tuned — tests assert the _properties_ (a write fails, network fails, a runaway is killed), not the numbers. `noexec` on `/tmp` is enabled; the integration test verifies numpy/pandas still import under it (see Resolved decisions).

### D5 — Sibling bind mounts resolve on the **host**, so the server is told the host data path

When the `server` container asks the daemon to create a sandbox with a bind mount, the bind **source** is interpreted by the Docker daemon against the **host** filesystem — not against the server container's mount namespace. The server knows the directory only as its internal `/data`; it cannot know the host path (`${PWD}/data`) unless told. So `docker-compose.yml` passes it explicitly:

```yaml
server:
  environment:
    MSR_DATA_HOST_DIR: ${PWD}/data # host path used as the sandbox bind source
    MSR_SANDBOX_IMAGE: msr-sandbox-base:latest
```

The pool reads `MSR_DATA_HOST_DIR` and mounts it read-only at `/data` in each sandbox; it reads `MSR_SANDBOX_IMAGE` for the image to run (default matches the tag `make up` builds). This is the classic docker-socket sibling-container gotcha; getting it wrong yields an empty mount or a mount of the wrong directory, so it is pinned here rather than discovered in chunk 4.

- _Why not a named volume shared by name (which resolves host-side without a path)?_ The stack contract mandates `./data` as a **host bind mount, not a named volume** (container-stack spec) so host tools and tests read the SQLite file directly; sandboxes therefore reference the same host directory.
- _Why mount the directory, not the file?_ Per the SQLite runtime contract, a directory mount keeps journal sidecars visible; with journal mode `DELETE` there are no `-wal`/`-shm` files, but mounting the directory read-only is the contract and avoids surprises if a sidecar ever appears.

### D6 — One exec per container; result contract is pass-through

`Run` performs exactly one `Exec` on the acquired container: the script bytes are written to the exec's stdin, the process is `python -`, and stdout/stderr/exit-code are captured. The pool returns `stdout, stderr, exitCode` **verbatim** — it neither requires nor parses JSON. A non-zero exit is a normal return (the agent surfaces stderr + code in the trace), not a Go `error`; `error` is reserved for infrastructure failures (create/exec/timeout/daemon errors).

- _Why not parse/validate JSON in the pool?_ Separation of concerns: the pool is an execution substrate; whether output is well-formed JSON is the `run_python` tool's contract (chunk 4). Keeping the pool payload-agnostic makes it reusable and its tests simpler.

### D7 — Timeout via context deadline plus force-remove

Each run derives a context with the configured wall-clock timeout. On expiry (or caller cancellation), the exec context is cancelled and the container is **force-removed** — since the process runs inside that container, removal is the kill switch, and destroy-after-one-use means we were going to remove it anyway. `Run` returns a distinguishable timeout error so the caller can render "script exceeded time limit" in the trace.

- _Why rely on force-remove rather than signalling the exec?_ Docker exec has no clean cancel/kill of the exec'd process; tearing down the container guarantees the process and any children die (belt-and-braces with the pids limit). It also composes with D1 — one code path removes the container whether the run succeeded, failed, or timed out.

### D8 — Replenishment, degradation, and shutdown

Replenishment runs in a goroutine after each acquire. If `Create` fails (daemon hiccup, image missing), it retries with bounded backoff and logs; a persistently failing daemon shrinks the effective pool, so `Run` callers block longer rather than the pool deadlocking or spinning. `New` fails fast if it cannot warm the **initial** N (misconfiguration surfaces at startup, not mid-demo). `Close` stops replenishment via a done signal and force-removes any idle containers still in the channel so a **graceful** server shutdown leaves no orphaned sandboxes. Cleanup after a **non-graceful** stop (crash, `docker kill`, OOM, `docker compose restart`, host reboot) — where `Close` never runs — is handled by D9.

### D9 — No orphaned sandboxes across a server restart (label + startup sweep, TTL backstop)

`Close` only helps on a graceful exit. A crash, OOM, `docker kill`, `docker compose restart`, or host reboot skips it, leaving idle warm containers (which run `sleep infinity` — i.e. forever) and any in-flight sandbox behind. Docker has **no** native "reap my sibling containers when I die" for socket-managed siblings, so the pool reaps its own predecessors:

- **Primary — label + startup sweep.** Every sandbox is created with a distinctive label (e.g. `msr.sandbox=1`). Before warming the pool, `New` lists all containers carrying that label and force-removes them. So whatever the previous server process left behind is gone *by the time the new pool is ready* — the restarted server always starts from a clean slate. This is the mechanism that answers "no orphaned sandboxes across restart," and it works regardless of *how* the previous process died, because cleanup runs on the *next* start rather than depending on the dying one.
- **Backstop — bounded idle lifetime + auto-remove.** Each sandbox is created with `AutoRemove: true` and idles on a bounded no-op (`sleep <ttl>`, TTL ≫ the per-run wall-clock timeout) instead of `sleep infinity`. A container that is never claimed and whose server never comes back exits when its TTL elapses and is auto-removed by the daemon — so even "server dies and is never restarted" leaves no permanent orphans. Because containers are single-use and normally removed right after their one exec, the TTL only ever fires for true orphans; setting it far above the run timeout means it never races a legitimate run.

Between a crash and the next start, orphans exist but are inert (`--network none`, read-only, resource-capped) and bounded in number (≤ N idle + in-flight); the startup sweep bounds their lifetime to "until the server restarts," the TTL bounds it independently. For a single-host POC that is the right cost/robustness trade-off.

- *Why not rely on `AutoRemove` alone (drop the sweep)?* AutoRemove fires on container **exit**; a `sleep`-idling warm container doesn't exit on server death, so without a TTL it never triggers, and with only a TTL orphans linger for the whole TTL window. The startup sweep removes them promptly on the (normal) restart path; the TTL is the catch-all for the abnormal "never restarts" path. The two compose.
- *Why not tie sandbox lifetime to the server container (e.g. cgroup/pid namespace share)?* Siblings created over the socket are independent containers by design (that is the whole sibling model); Docker offers no parent-death cascade for them. Self-reaping is the portable mechanism.

## Risks / Trade-offs

- **Docker socket access = host root-equivalent.** The `server` mounting `/var/run/docker.sock` can control the daemon; a server compromise is game over regardless of sandbox hardening. → Accepted for the POC (single-host demo); the sandbox hardening protects against the _script_, and the socket-holder is our own trusted server. Documented as the known ceiling.
- **Heavier dependency tree** from the Docker SDK vs. the repo's current lean deps. → Accepted for correct exec-stream handling (D3); isolated behind `dockerRuntime`.
- **Warm-pool cost when idle** — N containers sit running. → N defaults to 3 and each is a tiny bounded `sleep`; negligible for a demo, and pool size is config.
- **Orphaned sandboxes after a non-graceful stop** — a crash/kill/reboot skips `Close`, leaving idle/in-flight containers. → D9: a label + startup sweep reaps them on the next server start (the normal recovery path), and a bounded idle TTL + `AutoRemove` self-reaps any whose server never returns. Orphans in the gap are inert (no network, read-only, capped) and bounded to ≤ N + in-flight.
- **Replenishment lag under burst load** — sustained concurrency > N makes callers block. → Intended backpressure (D1); raise N if the demo needs more parallelism.
- **`${PWD}` in compose** depends on invocation from the repo root. → `make up` already runs compose from the repo root; documented, and the pool fails loudly if `MSR_DATA_HOST_DIR` is unset or not a directory.
- **Real-Docker integration test needs a daemon.** → Gated like the existing GraphDB integration tests: skip with a reason when Docker is unreachable and `*_REQUIRED` is unset; fail when set. Unit tests (the bulk) need no Docker.

## Migration Plan

Purely additive; nothing to migrate. New `internal/sandbox/` package plus two additive env vars on the `server` service in `docker-compose.yml` (root config owned by chunk 1, changed additively per the cross-cutting contract). No schema, API, or existing-behavior changes. Rollback = drop the package and the two env lines; no consumer exists until chunk 4 wires in `run_python`.

## Resolved decisions

Previously open, now settled (this is a controlled POC — values are chosen for sanity, not tuned):

- **Resource-limit values** — conservative CPU / memory / pids / tmpfs-size caps and wall-clock timeout, pinned as config defaults. Not tuned; the tests assert properties (a write fails, network fails, a runaway is killed), not the numbers.
- **Pool size N default 3** — confirmed; revisit only if chunk 4's demo needs more concurrency.
- **tmpfs `noexec`** — enabled. The integration test verifies numpy/pandas still import with `/tmp` mounted `noexec` (they should, since imports don't exec from `/tmp`); if a genuinely needed library ever breaks under it, drop `noexec` then.
