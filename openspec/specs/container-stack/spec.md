# container-stack Specification

## Purpose

Define the Docker Compose container stack, single-command bring-up, GraphDB repository provisioning, license handling, shared data directory, repository layout, and the acceptance-test gate for the MSR graph solution.

## Requirements

### Requirement: Single-command stack bring-up
The system SHALL provide a `make up` target that brings up the whole solution via Docker Compose: the GraphDB service (pinned `ontotext/graphdb` 11.x tag, with healthcheck, data volume, and license mount), the `server` scaffold, and builds the `extraction` and sandbox base images. `make up` MUST wait for GraphDB to report healthy before returning success.

#### Scenario: Stack comes up healthy
- **WHEN** a developer runs `make up` on a clean checkout with a valid `graphdb.license` in the repo root
- **THEN** GraphDB is reachable on its configured port, the `server` container answers on `/healthz`, and the `extraction` and sandbox base images are built

#### Scenario: Sandbox base image is usable
- **WHEN** the sandbox base image built by `make up` is run with `python -c "import numpy, pandas"`
- **THEN** the command exits 0 as a non-root user

#### Scenario: Extraction scaffold builds and runs
- **WHEN** the `extraction` image is run with its `--help` entry point
- **THEN** it exits 0, proving the Python 3.12 + pyproject scaffold builds

### Requirement: GraphDB repository created idempotently with inference disabled
`make up` SHALL ensure the GraphDB repository `msr` exists via GraphDB's REST API using a vendored repository-config TTL that specifies **no ruleset** (inference disabled). Creation MUST be check-then-create: if the repository already exists it is left untouched.

#### Scenario: First bring-up creates the repository
- **WHEN** `make up` runs against a fresh GraphDB data volume
- **THEN** repository `msr` exists afterwards and its configuration has no inference ruleset

#### Scenario: Re-running is a no-op
- **WHEN** `make up` runs a second time against the same GraphDB instance
- **THEN** the existing `msr` repository is not recreated or modified and the command still succeeds

### Requirement: License preflight
`make up` MUST check that `graphdb.license` exists in the repo root before starting the stack, and on absence fail with a message pointing at the Graphwise free-license request form. The license file MUST be gitignored and mounted read-only into the GraphDB container.

#### Scenario: Missing license fails fast
- **WHEN** `make up` runs and `graphdb.license` is absent
- **THEN** the command fails before starting containers, with an error explaining how to request a free license

#### Scenario: License never committed
- **WHEN** `git status` is inspected with `graphdb.license` present in the repo root
- **THEN** the file is ignored by git

### Requirement: Shared data directory as host bind mount
The Compose stack SHALL mount the repo-local `./data` directory into containers as a host bind mount (not a named volume) so host tools and tests can access the SQLite file and corpus cache directly. Containers MUST run with a fixed non-root UID, and `data/` MUST be gitignored except `data/nist/`.

#### Scenario: Host visibility of container-written data
- **WHEN** a one-shot container job writes the SQLite database under `/data`
- **THEN** the file is readable on the host at `./data` without entering a container

### Requirement: Repository layout per cross-cutting contracts
The change SHALL establish the repo layout defined by the cross-cutting contracts: `cmd/` (Go binaries `loader`, `server`), `internal/`, `extraction/` (Python project scaffold), `webapp/` (placeholder), `data/`, `testdata/`, alongside the existing `ontology/`. One multi-stage Dockerfile MUST build both Go binaries, with `server` and `loader` as two Compose services over the same image; `loader` runs as a one-shot job behind a Compose profile.

#### Scenario: Both Go binaries from one image
- **WHEN** the Go image is built
- **THEN** both the `server` and `loader` binaries are produced from the same multi-stage Dockerfile and each Compose service starts its respective binary

### Requirement: Acceptance test gate
The system SHALL provide a `make test` target that runs the Go test suite with `GRAPHDB_REQUIRED=1`, so integration tests fail (rather than skip) when GraphDB is unreachable. A bare `go test ./...` without the stack running MUST stay green by skipping integration tests with a reason; a GraphDB that responds with errors (HTTP 5xx, missing repository) MUST fail the tests in both modes.

#### Scenario: Gate cannot pass without the stack
- **WHEN** `make test` runs while GraphDB is not reachable
- **THEN** the integration tests fail instead of skipping

#### Scenario: Casual path stays green
- **WHEN** `go test ./...` runs without `GRAPHDB_REQUIRED` set and without the stack
- **THEN** integration tests skip with a stated reason and unit tests still run

### Requirement: Server configured to manage sandbox siblings
The `server` service SHALL be configured so it can launch sandbox **sibling** containers with a correct, host-resolved read-only mount of the shared `./data` directory. Because bind-mount sources are resolved by the Docker daemon on the **host** (not inside the requesting container), the `server` service MUST be given the **host** path of `./data` via environment configuration, alongside the sandbox image reference to run. The `server` service MUST mount the Docker daemon socket so it can manage siblings. These are additive changes to `docker-compose.yml`.

#### Scenario: Server has the host data path and sandbox image reference
- **WHEN** the Compose stack is brought up
- **THEN** the `server` service environment provides the host path of the `./data` directory and a sandbox image reference, and the Docker socket is mounted into the `server` container

#### Scenario: Sandbox image reference matches the built image
- **WHEN** `make up` builds and tags the sandbox base image
- **THEN** the sandbox image reference configured for the `server` service resolves to that built image tag (default `msr-sandbox-base:latest`)
