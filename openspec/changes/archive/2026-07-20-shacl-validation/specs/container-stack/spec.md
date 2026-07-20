## MODIFIED Requirements

### Requirement: GraphDB repository created idempotently with inference disabled
`make up` SHALL ensure the GraphDB repository `msr` exists via GraphDB's REST API using a vendored repository-config TTL that specifies **no ruleset** (inference disabled) **and enables native SHACL validation** (RDF4J `ShaclSail`). Creation MUST be check-then-create: if the repository already exists it is left untouched. When the repository already exists, the bootstrap MUST verify it is SHACL-enabled (inspecting its configuration) and, if it is not, fail with a clear message instructing the operator to drop the GraphDB data volume and recreate — because SHACL cannot be enabled on an existing repository. After the repository exists (and is SHACL-enabled), `make up` SHALL install the SHACL shape catalogue into the reserved shapes graph (`http://rdf4j.org/schema/rdf4j#SHACLShapeGraph`); this shapes-load step MUST be idempotent (re-running replaces the shapes graph contents without error and without recreating the repository).

#### Scenario: First bring-up creates the repository
- **WHEN** `make up` runs against a fresh GraphDB data volume
- **THEN** repository `msr` exists afterwards, its configuration has no inference ruleset, and it has SHACL validation enabled

#### Scenario: First bring-up installs the shapes
- **WHEN** `make up` runs against a fresh GraphDB data volume
- **THEN** the SHACL shape catalogue is present in the reserved shapes graph and validation is active for subsequent writes

#### Scenario: Re-running is a no-op
- **WHEN** `make up` runs a second time against the same GraphDB instance
- **THEN** the existing `msr` repository is not recreated or modified, the shapes-load step re-applies the same catalogue without error, and the command still succeeds

#### Scenario: Pre-SHACL existing repository is detected
- **WHEN** `make up` runs against a GraphDB instance that already holds an `msr` repository created without SHACL validation enabled
- **THEN** the bootstrap detects that SHACL is not enabled and fails with a message instructing the operator to drop the GraphDB data volume and recreate, rather than silently proceeding with validation inactive
