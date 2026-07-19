## ADDED Requirements

### Requirement: Server configured to manage sandbox siblings
The `server` service SHALL be configured so it can launch sandbox **sibling** containers with a correct, host-resolved read-only mount of the shared `./data` directory. Because bind-mount sources are resolved by the Docker daemon on the **host** (not inside the requesting container), the `server` service MUST be given the **host** path of `./data` via environment configuration, alongside the sandbox image reference to run. The `server` service MUST mount the Docker daemon socket so it can manage siblings. These are additive changes to `docker-compose.yml`.

#### Scenario: Server has the host data path and sandbox image reference
- **WHEN** the Compose stack is brought up
- **THEN** the `server` service environment provides the host path of the `./data` directory and a sandbox image reference, and the Docker socket is mounted into the `server` container

#### Scenario: Sandbox image reference matches the built image
- **WHEN** `make up` builds and tags the sandbox base image
- **THEN** the sandbox image reference configured for the `server` service resolves to that built image tag (default `msr-sandbox-base:latest`)
