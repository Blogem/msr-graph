# store-checkpoint-restore Specification

## Purpose

Define whole-store checkpoint and restore for demo rollback: capture the entire GraphDB
repository (all named graphs, including staging and proposals) plus the SQLite measurement
store and the ontology version into a labelled checkpoint, and restore that checkpoint
atomically so proposal statuses, promoted schema, back-populated instances, and text-derived
rows all revert together. This is the demo path that lets the evolution loop be re-run.

## Requirements

### Requirement: Checkpoint captures the full graph, SQLite, and version
Creating a checkpoint SHALL write, under `data/checkpoints/{label}/`, a full TriG export of the
GraphDB repository covering **all** named graphs (core, staging, and proposal graphs), a
consistent copy of the SQLite measurement store, and the current ontology `owl:versionInfo`
value. The SQLite copy SHALL be taken with a consistent-snapshot mechanism (`VACUUM INTO`) on a
connection separate from the read-only chat connection, so it is valid regardless of concurrent
readers.

#### Scenario: Checkpoint writes all three artifacts
- **WHEN** a checkpoint named `demo` is created
- **THEN** `data/checkpoints/demo/` contains the TriG export of all named graphs, a SQLite copy, and the recorded ontology version

### Requirement: Restore clears then re-imports the whole store
Restoring a checkpoint SHALL clear the GraphDB repository, import the checkpoint's TriG, and put
the checkpoint's SQLite copy back in place of the live measurement store. The restore SHALL
return the ontology version to the checkpointed value and every named graph to its checkpointed
contents in one operation, so no core ABox is left referencing rolled-back schema.

#### Scenario: Restore reverts graph and SQLite together
- **WHEN** a checkpoint is restored
- **THEN** the repository's named graphs match the checkpoint, the SQLite store matches the checkpoint copy, and `owl:versionInfo` is back to the checkpointed value

### Requirement: Checkpoint → change → restore round-trip is exact
A checkpoint → approve → restore round-trip SHALL return the graph triple counts per named
graph and the SQLite content to be identical to the pre-checkpoint state: after creating a
checkpoint, approving a proposal (which routes triples into core and bumps the version), and
restoring that checkpoint, the approved proposal is `pending` again, the promoted triples are
gone from the core graphs, and the version is back. The approval SHALL then be re-runnable to
identical effect.

#### Scenario: Approve then restore reverts everything
- **WHEN** a checkpoint is taken, the `solubility` proposal is approved, and the checkpoint is restored
- **THEN** `msr:solubility` is absent from `urn:msr:ontology`, the proposal is `pending`, `owl:versionInfo` is back to its pre-approval value, and the SQLite content matches the checkpoint

#### Scenario: The demo can be re-run after restore
- **WHEN** the same proposal is approved again after a restore
- **THEN** the approval succeeds and produces the same core-graph and version result as the first approval

### Requirement: Checkpoint API and make wrappers
Checkpoint/restore SHALL be exposed as `GET /api/checkpoints` (list), `POST /api/checkpoints`
(create), `POST /api/checkpoints/{label}/restore` (restore), and `DELETE
/api/checkpoints/{label}` (delete), and as `make checkpoint` / `make restore` / `make
delete-checkpoint` wrappers on the root Makefile. The `{label}` SHALL be validated to a
conservative filesystem-safe charset and a label outside it SHALL be rejected before any path
is touched, preventing path traversal outside `data/checkpoints/`.

#### Scenario: Create and list a checkpoint over the API
- **WHEN** a client `POST`s a checkpoint named `demo` and then `GET /api/checkpoints`
- **THEN** the created checkpoint appears in the returned list

#### Scenario: An unsafe label is rejected
- **WHEN** a client requests a checkpoint whose label contains path-traversal characters (e.g. `../etc`)
- **THEN** the request is rejected and no file outside `data/checkpoints/` is written or read

### Requirement: Delete removes a checkpoint's stored artifacts
Deleting a checkpoint SHALL remove its `data/checkpoints/{label}/` directory and all its
artifacts (the TriG export, the SQLite copy, and the manifest), exposed as `DELETE
/api/checkpoints/{label}`. The `{label}` SHALL be validated to the conservative filesystem-safe
charset before any path is touched, and an unknown label SHALL be rejected as not-found without
removing anything. Delete SHALL NOT touch the live store (GraphDB repository or SQLite
measurement store) — only the checkpoint's own on-disk snapshot.

#### Scenario: Delete removes a checkpoint
- **WHEN** a client `DELETE`s an existing checkpoint `demo`
- **THEN** `data/checkpoints/demo/` no longer exists and `demo` no longer appears in `GET /api/checkpoints`

#### Scenario: Deleting an unknown checkpoint is not-found
- **WHEN** a client `DELETE`s a label with no checkpoint directory
- **THEN** the request is rejected `404 not_found` and no filesystem entry is removed

#### Scenario: An unsafe label is rejected on delete
- **WHEN** a client `DELETE`s a label containing path-traversal characters (e.g. `../etc`)
- **THEN** the request is rejected `400 invalid_label` and no file outside `data/checkpoints/` is touched
