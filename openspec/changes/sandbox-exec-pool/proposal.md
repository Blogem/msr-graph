# Proposal: sandbox-exec-pool

## Why

The grounded-analysis agent (chunk 4) must run **all** computation in code a reviewer can read in the trace — never in the model and never as SQL side effects — over model-authored Python scripts. Executing untrusted, LLM-authored code demands hard isolation: no network, no write path to the read-only value store, no filesystem persistence between runs, and bounded CPU/memory/time. This change delivers that execution substrate — a warm pool of throwaway sandbox containers — as its own security-sensitive, independently reviewable unit (per the implementation plan's granularity note keeping chunk 3 standalone), so chunk 4 can consume a simple `Run(script)` interface.

## What Changes

- **New `internal/sandbox` Go package** — a channel-based pool of warm sandbox containers. A buffered `chan *Sandbox` (size N, default 3) *is* the pool; acquire is a channel receive; there is no release — after **one** script run the used container is force-removed and a goroutine replenishes the pool with a fresh one (destroy-after-one-use).
- **Public API** `Run(ctx, script) → (stdout, stderr, exitCode, error)` consumed by chunk 4's `run_python` tool. Script source is fed on stdin, a JSON result is expected on stdout, and stderr + exit code are captured for the trace.
- **Hardened container spec** for each sandbox: the chunk-1 sandbox base image, `--network none`, read-only root filesystem + tmpfs `/tmp`, non-root user, CPU/memory/pids limits, and a wall-clock timeout that kills runaway scripts. The SQLite data **directory** is bind-mounted **read-only** (DB visible at `/data/msr.db`; directory mount keeps journal sidecars visible, per the SQLite runtime contract).
- **Injectable container-runtime interface** wrapping the Docker daemon (reached over the already-mounted `/var/run/docker.sock`), so the pool's lifecycle, timeout, and concurrency logic are unit-testable against a fake with no Docker present; a real implementation backs it in production.
- **Server-side stack configuration** so the server can launch sandbox **sibling** containers with a correct host-resolved read-only bind mount of `./data` and a known sandbox image reference.

## Capabilities

### New Capabilities

- `sandbox-execution`: the channel-based warm pool, its destroy-after-one-use lifecycle, the hardened container isolation spec (no network, read-only FS + read-only data mount, non-root, resource + wall-clock limits), the stdin-script / stdout-JSON execution contract, and the `Run` API that chunk 4 consumes.

### Modified Capabilities

- `container-stack`: the `server` service gains the configuration needed to manage sandbox siblings — the host path of the shared `./data` directory (bind sources resolve on the host, not inside the requesting container) and the sandbox image reference — added additively to `docker-compose.yml`, which chunk 1 owns.

## Impact

- **New code**: `internal/sandbox/` (pool, container-runtime interface, real Docker-backed implementation, and tests).
- **Dependencies**: a Docker API client for Go talking to the mounted socket (the `server` image is distroless-static with no `docker` CLI, so isolation is driven over the daemon socket, not by shelling out). No LLM access in this chunk.
- **Config**: `docker-compose.yml` `server` service gains the host data-directory path and sandbox image reference (additive; root config owned by chunk 1). The Docker socket mount already exists from chunk 1.
- **Consumes**: the chunk-1 sandbox base image (minimal Python + numpy/pandas, non-root UID 10001) and the read-only `/data` contract from the measurement store.
- **Downstream**: chunk 4's `run_python` tool depends on the `Run` interface; the pool is the execution half of demo #1 (grounded analysis). No other chunk depends on this one.
