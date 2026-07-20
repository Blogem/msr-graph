# admin-ui Specification

## Purpose

Define the admin surface of the frontend: listing, creating, and restoring whole-store
checkpoints so a pre-demo checkpoint can be restored to re-run the evolution demo end-to-end.
This capability consumes the chunk-9 `store-checkpoint-restore` API unchanged and holds no direct
store access.

## ADDED Requirements

### Requirement: Checkpoint list
The admin surface SHALL list existing checkpoints from `GET /api/checkpoints`, showing each
checkpoint's label.

#### Scenario: Existing checkpoints are listed
- **WHEN** the admin surface loads
- **THEN** it requests `GET /api/checkpoints` and shows the returned checkpoints

### Requirement: Create a checkpoint
The admin surface SHALL let the user create a checkpoint by supplying a label and calling
`POST /api/checkpoints`. On success the new checkpoint SHALL appear in the list.

#### Scenario: New checkpoint created and listed
- **WHEN** the user creates a checkpoint named `demo`
- **THEN** the client sends `POST /api/checkpoints` with that label and the checkpoint appears in
  the refreshed list

#### Scenario: Rejected label surfaces an error
- **WHEN** the user supplies a label the API rejects (e.g. containing path-traversal characters)
- **THEN** the UI shows the error and no checkpoint is added to the list

### Requirement: Restore a checkpoint
The admin surface SHALL let the user restore a listed checkpoint via
`POST /api/checkpoints/{label}/restore`, so the store is rolled back to that checkpoint for a
fresh demo run. The action SHALL confirm before restoring, since it replaces live store state.

#### Scenario: Restore rolls the store back
- **WHEN** the user restores the `demo` checkpoint and confirms
- **THEN** the client sends `POST /api/checkpoints/demo/restore` and reports success on completion

#### Scenario: Restore is confirmed before firing
- **WHEN** the user clicks restore
- **THEN** a confirmation is required before the restore request is sent

### Requirement: Admin surface enables end-to-end demo reset
The admin surface SHALL support the demo-reset flow: after an evolution demo has mutated the
store, restoring a pre-demo checkpoint SHALL return the app to a state where the whole demo can be
re-run (the review queue shows the proposals as pending again).

#### Scenario: Post-restore the demo can be re-run
- **WHEN** the user restores a pre-demo checkpoint after approving proposals
- **THEN** the review queue again shows those proposals as pending, ready to re-run the demo
