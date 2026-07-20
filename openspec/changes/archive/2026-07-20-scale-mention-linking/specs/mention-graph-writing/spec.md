# mention-graph-writing Specification (delta)

## ADDED Requirements

### Requirement: Mention writes are split into bounded batches
The mention writer SHALL split a report's mentions into bounded batches and
send one additive `INSERT DATA` per batch to `urn:msr:data` (mention
triples), and likewise one additive `INSERT DATA` per batch to
`urn:msr:provenance` (per-run generation edges), rather than a single
request containing all of a report's mentions. The batch size SHALL be
configurable (default 500). Because every batch is additive `INSERT DATA`
over deterministic, blank-node-free IRIs, the union of batches SHALL be
identical to a single unbatched write — batching MUST NOT change the
resulting triples, the re-run idempotency of `urn:msr:data`, or the
append-only accumulation in `urn:msr:provenance`. An empty mention list
SHALL still send zero updates.

#### Scenario: A large mention set is written across multiple requests
- **WHEN** a report has more linked mentions than the configured batch size
- **THEN** the writer sends multiple `INSERT DATA` requests, each carrying at most one batch of mentions, and every mention appears in exactly one `urn:msr:data` batch and gets exactly one per-run generation edge in a `urn:msr:provenance` batch

#### Scenario: Batching does not change the written triples
- **WHEN** the same mentions are written with any batch size
- **THEN** the union of the batched `INSERT DATA` requests contains exactly the same mention triples and generation edges as a single unbatched write, preserving re-run idempotency of `urn:msr:data`

#### Scenario: Empty input sends nothing
- **WHEN** the writer is given an empty mention list
- **THEN** it sends zero SPARQL updates
