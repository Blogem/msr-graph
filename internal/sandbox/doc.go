// Package sandbox implements a warm pool of hardened, single-use Docker
// containers for executing untrusted, LLM-authored Python scripts.
//
// # Purpose
//
// The grounded-analysis agent runs all computation as model-authored Python
// rather than in the model itself or as SQL side effects, so the script and
// its output can appear verbatim in the chat trace. That code is
// effectively untrusted, so it must run with no network, no write path to
// the read-only value store, no filesystem persistence between runs, and
// hard CPU/memory/time bounds. This package is that execution substrate.
//
// # The Run contract
//
// The pool's entire public surface is:
//
//	Run(ctx, script) (stdout, stderr []byte, exitCode int, err error)
//
// script is fed as raw bytes to `python -` on the container's stdin. stdout
// and stderr are returned verbatim and unparsed -- the pool neither
// requires nor interprets any particular output format (e.g. JSON); that is
// the caller's contract, not the pool's. A non-zero exitCode is a normal,
// expected result (the caller surfaces stderr and the code in the trace),
// not a Go error. err is reserved for infrastructure failures: container
// create/exec/daemon errors, or a run that exceeded its wall-clock timeout.
// A timeout is reported as ErrTimeout (wrapped in err via errors.Is) so
// callers can distinguish "script ran and failed" from "script was killed
// for running too long."
//
// # Isolation guarantees
//
// Every sandbox container is created with the same fixed, non-configurable
// isolation controls, each tied to a specific threat:
//
//   - No network (`--network none`): scripts cannot exfiltrate data, call
//     out, or fetch payloads.
//   - Read-only root filesystem, with a size-capped tmpfs mounted `noexec`
//     at /tmp for scratch space: scripts cannot persist tools or tamper
//     with the image, and cannot execute anything they write to /tmp.
//   - Non-root user (the base image's fixed UID 10001): no
//     privilege-escalation path via a root user inside the container.
//   - All Linux capabilities dropped, plus no-new-privileges: reduces the
//     blast radius of any kernel-level escape attempt.
//   - CPU, memory (swap disabled), and pids limits: bound host resource
//     exhaustion and fork bombs.
//   - A wall-clock timeout per run, enforced by force-removing the
//     container on expiry -- Docker exec has no clean way to cancel a
//     running process, so tearing down the container is the kill switch.
//   - The shared SQLite data directory is bind-mounted read-only at /data
//     (exposing the database at /data/msr.db): scripts can query the value
//     store but cannot write to it or to the mounted directory.
//
// Combined with the pool's single-use lifecycle -- a container serves
// exactly one script run, is then always force-removed regardless of
// success, failure, or timeout, and is replaced by a freshly created
// container in the background -- no filesystem artifact, process, or
// mutated state ever survives from one script run into the next.
//
// # Configuration
//
// LoadConfig reads two environment variables:
//
//   - MSR_DATA_HOST_DIR: the HOST path of the data directory bind-mounted
//     read-only at /data in every sandbox. It has no default and LoadConfig
//     fails loudly if it is unset or does not resolve to an existing
//     directory, because sandboxes are Docker siblings created over the
//     mounted /var/run/docker.sock: the Docker daemon resolves bind-mount
//     sources against the HOST filesystem, not against this process's own
//     container mount namespace. A server that only knows its own internal
//     /data path cannot derive the host path from it, so the host path must
//     be supplied explicitly (docker-compose passes ${PWD}/data). Getting
//     this wrong silently mounts an empty or wrong directory into every
//     sandbox.
//   - MSR_SANDBOX_IMAGE: the sandbox image reference to run, defaulting to
//     the tag `make up` builds.
//
// All other settings (pool size, resource limits, timeout, tmpfs size, idle
// TTL) are conservative built-in defaults, not read from the environment.
//
// # Restart and orphan handling
//
// Every sandbox container carries a distinctive label. On a graceful
// shutdown, the pool force-removes its own idle containers. Because a
// crash, OOM, kill, `docker compose restart`, or host reboot skips graceful
// shutdown and can leave containers running, pool initialization first
// force-removes every pre-existing container carrying that label (a
// startup sweep) before warming a fresh pool -- so a restarted server
// always begins from a clean slate, regardless of how its predecessor died.
// As a backstop for a server that never restarts, each sandbox idles on a
// bounded no-op (well above the per-run timeout) and is created with
// auto-remove, so an abandoned, unclaimed container is eventually reaped by
// the Docker daemon on its own even if no server ever sweeps it.
//
// # Trust ceiling
//
// This package talks to the Docker daemon over /var/run/docker.sock, which
// the server process holds mounted. Holding that socket makes the server
// itself host-root-equivalent: it can control the daemon, and therefore the
// host, directly. The isolation controls described above harden the
// sandboxed *script* against a well-behaved server; they do nothing to
// contain a *compromised server process*, since the same socket access that
// creates hardened sandboxes could equally be used to bypass them. This is
// an accepted, documented ceiling for a single-host proof of concept, not a
// gap this package attempts to close.
package sandbox
