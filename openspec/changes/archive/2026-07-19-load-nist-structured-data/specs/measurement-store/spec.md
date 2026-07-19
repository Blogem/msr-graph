# Spec: measurement-store

## ADDED Requirements

### Requirement: Idempotent upsert by locator
`internal/store` SHALL expose an idempotent write path that upserts `measurement_value` rows keyed on the `locator` primary key (`INSERT … ON CONFLICT(locator) DO UPDATE`, equivalently `INSERT OR REPLACE`), so re-running a batch loader with the same locators leaves the row count unchanged and updates any changed columns in place. All batch writers (the chunk-2 NIST loader and the chunk-7 extraction writer) MUST write through this helper so the upsert-by-locator contract and the pinned connection settings are enforced in code, not convention.

#### Scenario: First write inserts the row
- **WHEN** a measurement row with a new locator is upserted
- **THEN** `measurement_value` contains exactly one row for that locator with the written column values

#### Scenario: Re-upserting the same locator is a no-op on count
- **WHEN** the same locator is upserted a second time with identical values
- **THEN** the total row count is unchanged and the row's values are unchanged

#### Scenario: Re-upserting updates changed columns
- **WHEN** a locator already present is upserted with a changed coefficient value
- **THEN** the existing row is updated in place, no duplicate row is created, and the row count is unchanged
