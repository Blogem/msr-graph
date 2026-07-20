# analysis-agent (delta)

## ADDED Requirements

### Requirement: Answer-time groundedness stamp enforced in the loop
The agent loop SHALL stamp **every** turn's final answer as grounded or ungrounded, enforced in the loop itself and not left to the model. A turn is *grounded* when the answer drew on facts surfaced through grounding (i.e. at least one provenance event was emitted during the turn); otherwise it is *ungrounded*. When the model returns its final answer (no further tool calls), the loop SHALL emit a first-class answer-stamp trace event carrying the grounded/ungrounded verdict and the aggregated provenance chain (the union of the turn's `dataLocator`s, `citedIn` documents, and dataset DOIs) **before** the terminating `done` event. A numeric answer produced without any provenance chain SHALL be stamped ungrounded so a bare number cannot reach the user unmarked.

#### Scenario: A grounded answer is stamped with its provenance chain
- **WHEN** a turn grounds via `sparql_query`, computes via `run_python`, and returns a final numeric answer
- **THEN** the loop emits an answer-stamp event marked grounded, carrying the union of the `dataLocator`s / `citedIn` documents / dataset DOIs used, before the `done` event

#### Scenario: An answer with no provenance is stamped ungrounded
- **WHEN** a turn returns a final answer without any provenance event having been emitted
- **THEN** the loop emits an answer-stamp event marked ungrounded, regardless of what the model asserted in its text

#### Scenario: The stamp is loop-enforced, not model-driven
- **WHEN** the model produces its final answer
- **THEN** the answer-stamp event is emitted by the loop for every turn, independent of the model naming any variable or restating provenance itself

### Requirement: `run_python` result references the data locators it read
When a `run_python` script runs during a turn, the agent SHALL determine which grounded `dataLocator`(s) the script read by matching the script source against the set of `dataLocator` values surfaced by `sparql_query` earlier in the same turn, and SHALL attach the matched locators to that run's trace, folding them into the turn's aggregated provenance chain. This ties a computed number to the grounded rows it derived from without relying on the model to self-report.

#### Scenario: A computed number is tied to the locator it read
- **WHEN** a script reads coefficients for a locator that was surfaced by grounding earlier in the turn and computes a value
- **THEN** the run's trace records that `dataLocator`, and it appears in the turn's aggregated provenance chain

#### Scenario: Only actually-grounded locators are attached
- **WHEN** a script's source does not contain any locator that grounding surfaced this turn
- **THEN** no locator is attached to the run (the model cannot claim a locator it never grounded)
