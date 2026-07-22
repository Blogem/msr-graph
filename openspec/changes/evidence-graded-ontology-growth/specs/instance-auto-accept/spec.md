## ADDED Requirements

### Requirement: A new-type instance is retained as a promotion witness, not dropped
Under the instances-first model, an individual whose only candidate type is not yet in the core schema SHALL be **retained as a promotion witness** rather than dropped. The miner SHALL record such an individual (with its `prov:wasGeneratedBy`/`prov:wasDerivedFrom` edges and its evidence) as accumulated evidence for the implied type, so the type can later cross the promotion threshold. It SHALL NOT be auto-accepted to `urn:msr:data` (its type does not yet exist there) and SHALL NOT force a class to be minted on the strength of that single witness.

This refines the prior behavior where an instance typed only by a not-yet-proposed class was discarded: the witness now feeds evidence accumulation (`novelty-detection`) instead of being lost.

#### Scenario: A witness for an unmodeled type is retained
- **WHEN** a mined individual can only be typed by a class that is neither in the core schema nor an existing pending proposal
- **THEN** it is retained as a promotion witness for that implied type (with its provenance and evidence), not dropped, and nothing is written to `urn:msr:data` for it

#### Scenario: Witnesses accumulate toward promotion rather than minting a class each
- **WHEN** several individuals across runs imply the same unmodeled type
- **THEN** they accumulate as witnesses for one implied type (rather than each minting its own class), and a class is proposed only once that type crosses the promotion threshold
