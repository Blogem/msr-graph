## ADDED Requirements

### Requirement: Per-term evidence accumulates across mine runs as a promotion signal
The miner SHALL accumulate, per candidate term, the evidence observed for it across mine runs — at minimum its witness-instance count and the set of documents it has appeared in — and SHALL expose this accumulated evidence as a **promotion signal** distinct from the per-run document-frequency cost bound. A type SHALL become eligible for promotion to a class (per `candidate-triage`) only when its accumulated evidence crosses a **configurable promotion threshold**. The threshold MUST be a configuration value, not a hardcoded literal, and the accumulation MUST be deterministic and idempotent so a re-run over the same corpus does not inflate the count.

This is explicitly not a novelty ranking of candidates for selection (which remains governed by the salience floor and ceiling); it is an evidence gate on class-hood.

#### Scenario: A recurring type crosses the promotion threshold
- **WHEN** the accumulated witness count / document coverage for an implied type reaches the configured promotion threshold across one or more runs
- **THEN** the type is marked eligible for promotion to a class

#### Scenario: A thin type stays below the threshold
- **WHEN** an implied type has only a single witness and no further accumulated evidence
- **THEN** it remains below the promotion threshold and no class is minted for it

#### Scenario: Accumulation is idempotent across re-runs
- **WHEN** the miner runs twice over the same corpus
- **THEN** the accumulated per-term evidence and any resulting promotion decision are identical after the second run as after the first
