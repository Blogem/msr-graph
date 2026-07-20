# llm-disambiguation Specification (delta)

## ADDED Requirements

### Requirement: Distinct unresolved surfaces are resolved concurrently
The pipeline SHALL resolve the distinct unresolved layer-5 surface forms of a
run concurrently, using a bounded worker pool whose size is configurable
(default 8), rather than issuing every layer-5 model call strictly
sequentially. Concurrency MUST NOT change which spans reach layer 5, the
per-surface memoization semantics, or the known-IRI validation of each
outcome: each distinct surface SHALL still be sent to the model exactly once
per run, and the linked/novel result applied to a span SHALL be identical to
that produced by a sequential run.

#### Scenario: Each distinct surface is resolved once despite concurrency
- **WHEN** several distinct unresolved surfaces reach layer 5 in a run
- **THEN** each distinct surface is sent to the model exactly once, and repeated occurrences of a surface issue no additional model call

#### Scenario: Concurrent resolution is transparent to output
- **WHEN** a surface resolves to a link under concurrent resolution
- **THEN** the resulting mention record links to the same IRI it would under sequential resolution, still subject to the known-IRI validation

#### Scenario: More than one call runs at a time
- **WHEN** multiple distinct unresolved surfaces are pending resolution
- **THEN** the worker pool issues more than one model call concurrently rather than one at a time
