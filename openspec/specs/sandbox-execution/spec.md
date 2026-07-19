# sandbox-execution Specification

## Purpose

Define the warm sandbox pool that executes untrusted, model-authored Python scripts under hard isolation: a channel-based pool of throwaway containers with a destroy-after-one-use lifecycle, a hardened container spec (no network, read-only root filesystem, read-only data mount, non-root user, resource and wall-clock limits), a stdin-script / stdout-capture execution contract, and a `Run` API consumed by the grounded-analysis agent.

## Requirements

### Requirement: Warm sandbox pool with single-use lifecycle
The system SHALL provide a Go `internal/sandbox` pool in which a buffered channel of capacity N (default 3) holds warm, ready sandbox containers. Acquiring a sandbox SHALL be a channel receive that blocks when the pool is empty (bounding concurrency at N). After a container serves **one** script run it SHALL be force-removed — never reused — and a fresh container SHALL be created and returned to the pool by a background goroutine, so no state survives between runs.

#### Scenario: Acquire yields a warm container
- **WHEN** the pool is initialized with N warm containers and a run is requested
- **THEN** a ready container is received from the channel without creating one on the request path

#### Scenario: Used container destroyed and replaced after one run
- **WHEN** a script run on an acquired container completes (success, failure, or timeout)
- **THEN** that container is force-removed and a freshly created container is placed back into the pool, restoring the pool to N ready containers

#### Scenario: Concurrent acquires drain and refill without races
- **WHEN** more concurrent runs are requested than the pool size N, exercised under the Go race detector
- **THEN** each run acquires a distinct container, callers beyond N block until replenishment provides one, and no data race or double-use of a container occurs

### Requirement: Script execution interface and result capture
The pool SHALL expose `Run(ctx, script)` that feeds the script source to a sandbox on stdin (executed as `python -`), and returns the process stdout, stderr, and exit code. Stdout SHALL be returned verbatim without the pool parsing or requiring any particular format. A non-zero script exit code SHALL be reported as a normal result (captured stderr + code), not as an infrastructure error; errors SHALL be reserved for runtime/daemon failures.

#### Scenario: Script queries the database and returns JSON
- **WHEN** a script that opens `/data/msr.db` read-only, runs a query, and prints a JSON object to stdout is run
- **THEN** `Run` returns that JSON as stdout with exit code 0 and no error

#### Scenario: Failing script reports stderr and exit code, not an error
- **WHEN** a script that writes to stderr and exits non-zero is run
- **THEN** `Run` returns the captured stderr and the non-zero exit code with a nil infrastructure error

### Requirement: Sandbox network isolation
Each sandbox container SHALL run with no network access (`--network none`) so scripts cannot reach the network.

#### Scenario: Network access fails inside a sandbox
- **WHEN** a script attempts any outbound network connection
- **THEN** the attempt fails and the failure is reflected in the script's stderr / non-zero exit code

### Requirement: Sandbox read-only access to the value store
Each sandbox SHALL mount the SQLite data **directory** read-only, exposing the database at `/data/msr.db`. Scripts SHALL be able to read the database but SHALL NOT be able to write to it or to the mounted directory.

#### Scenario: Read succeeds
- **WHEN** a script opens `/data/msr.db` and issues a SELECT
- **THEN** the query returns rows

#### Scenario: Write attempt fails
- **WHEN** a script attempts to write to `/data/msr.db` (INSERT/UPDATE) or create a file in `/data`
- **THEN** the write fails because the mount is read-only

### Requirement: Resource and wall-clock limits
Each sandbox SHALL be created with CPU, memory, and pids limits, and each run SHALL be bounded by a configurable wall-clock timeout. A run that exceeds the timeout SHALL be terminated by force-removing its container, and `Run` SHALL return a distinguishable timeout error.

#### Scenario: Long-running script killed at the timeout
- **WHEN** a script runs longer than the configured wall-clock timeout
- **THEN** its container is force-removed, the script does not run to completion, and `Run` returns a timeout error distinguishable from a normal non-zero exit

### Requirement: Sandbox filesystem and privilege isolation
Each sandbox SHALL run with a read-only root filesystem, a tmpfs-backed `/tmp` for scratch mounted `noexec`, as a non-root user (the base image's UID 10001), and with reduced privileges (dropped Linux capabilities and no-new-privileges). Combined with single-use lifecycle, no filesystem artifact SHALL persist from one run to the next. The `noexec` scratch mount MUST NOT break importing the base image's Python libraries (numpy, pandas).

#### Scenario: Root filesystem is not writable
- **WHEN** a script attempts to create or modify a file outside `/tmp` (e.g. under `/` or the home directory)
- **THEN** the write fails because the root filesystem is read-only

#### Scenario: Scratch space is available and ephemeral
- **WHEN** a script writes a temporary file under `/tmp` during its run
- **THEN** the write succeeds, and after the run the container is destroyed so the file does not survive into any later run

#### Scenario: noexec scratch does not break library imports
- **WHEN** a script running in a sandbox with `/tmp` mounted `noexec` imports numpy and pandas
- **THEN** the imports succeed

### Requirement: Pool logic verifiable without a Docker daemon
The pool SHALL depend on the container runtime through an injected interface so that its lifecycle, timeout, and concurrency behavior can be unit-tested against a fake runtime with no Docker daemon present. A single integration test MAY exercise the real Docker-backed runtime for the isolation properties.

#### Scenario: Lifecycle and concurrency tested against a fake runtime
- **WHEN** the pool's unit tests run with a fake container runtime and no Docker daemon available
- **THEN** drain/replenish, timeout, and concurrent-acquire behavior are exercised and pass, including under the race detector

### Requirement: No orphaned sandboxes across server restart
The system SHALL NOT leak sandbox containers when the server process stops and restarts. On graceful shutdown the pool SHALL force-remove its idle containers. Because a non-graceful stop (crash, kill, OOM, restart, host reboot) skips graceful shutdown, every sandbox SHALL carry a distinctive label, and pool initialization SHALL force-remove all pre-existing containers carrying that label before warming a fresh pool, so a restarted server begins with no orphans left by its predecessor. As a backstop for a server that never restarts, each sandbox SHALL be created with a bounded idle lifetime and auto-removal so an unclaimed, abandoned container is eventually reaped by the daemon.

#### Scenario: Graceful shutdown removes idle containers
- **WHEN** the pool is closed
- **THEN** all idle containers held by the pool are force-removed and replenishment stops

#### Scenario: Restart sweeps orphans left by a non-graceful stop
- **WHEN** a new pool is initialized while sandbox containers labelled by a previous (crashed or killed) server process still exist
- **THEN** those pre-existing labelled containers are force-removed before the new pool is warmed, so the server starts with no orphaned sandboxes

#### Scenario: Abandoned sandbox self-reaps
- **WHEN** a sandbox container is never claimed and its server never restarts to sweep it
- **THEN** the container exits at its bounded idle lifetime and is auto-removed by the daemon
