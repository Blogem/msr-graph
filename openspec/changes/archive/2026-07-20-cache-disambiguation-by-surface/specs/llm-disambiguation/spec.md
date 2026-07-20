# llm-disambiguation Specification (delta)

## ADDED Requirements

### Requirement: Disambiguation outcomes are memoized per surface form within a run
The pipeline SHALL cache each layer-5 disambiguation outcome keyed on the
mention surface form for the duration of a single `link` run, and SHALL reuse
the cached outcome for any later span with an identical surface form instead
of issuing another model call. The cache SHALL be in-memory and scoped to a
single run — it MUST NOT be persisted across runs. Because layer-5 candidate
spans are formula-shaped, the surface form determines identity and the
sentence context of the first occurrence is representative for later
identical surfaces. Every reused outcome remains subject to the known-IRI
validation, so memoization can never produce a link to an IRI absent from the
run's known-IRI set.

#### Scenario: Repeated surface reuses the cached outcome
- **WHEN** the same unresolved surface form reaches layer 5 more than once in a run
- **THEN** the model is called only for the first occurrence and later occurrences reuse the cached outcome

#### Scenario: Distinct surfaces each call once
- **WHEN** two different unresolved surface forms reach layer 5 in a run
- **THEN** each surface produces its own model call and neither reuses the other's outcome

#### Scenario: A novel outcome is cached too
- **WHEN** a surface is resolved as novel on its first occurrence
- **THEN** later identical surfaces reuse the novel outcome without another model call

#### Scenario: Cache does not persist across runs
- **WHEN** a new `link` run starts
- **THEN** the disambiguation cache begins empty and no outcome is carried over from a previous run
