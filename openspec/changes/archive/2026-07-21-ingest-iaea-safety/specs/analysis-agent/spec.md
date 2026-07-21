## ADDED Requirements

### Requirement: Safety-traceability answers over the grown Safety branch
The agent SHALL answer safety-traceability questions over the approved `Safety` branch using its existing tools and grounding, with no hardcoded safety terms — the branch reaches the agent through the KG-schema system prompt rebuilt on the post-approval `owl:versionInfo` bump. Given a safety function, the agent SHALL return the evidence chain to a measured value: `SafetyFunction → servedByProperty → PhysicalProperty ← forProperty ← PropertyMeasurement → ofSalt → MoltenSalt`, together with the `prov:wasDerivedFrom` source of each fact used.

#### Scenario: Evidence chain for a safety claim
- **WHEN** the user asks what measured evidence supports the confinement (or heat-removal) safety function for FLiBe
- **THEN** the agent traverses `servedByProperty` to the property, follows `forProperty`/`ofSalt` to the FLiBe measurement, and returns the value plus the provenance chain (safety `Document` for the function→property link, and the NIST/ORNL source for the measurement)

### Requirement: Evidence-gap disclosure
The agent SHALL answer which safety-relevant properties lack a measured value for a given salt by a negation query (`FILTER NOT EXISTS` for a `PropertyMeasurement` of a `servedByProperty`-linked property), and SHALL report the gap rather than fabricate a value.

#### Scenario: Missing measurement is disclosed as a gap
- **WHEN** a safety function is served by a property for which no measurement exists for the salt in question
- **THEN** the agent reports that property as an evidence gap and does not present a numeric value for it

### Requirement: Requirement satisfaction computed in the sandbox with the soft-criterion caveat
When a `Requirement` carries a stated threshold, the agent SHALL compute satisfaction and margin in a sandbox `run_python` script (threshold vs the measured value) and SHALL present the result as a soft criterion — stating that the threshold is a selection preference, not a licensing limit. The agent SHALL NOT present a satisfaction verdict without a resolvable threshold source, and SHALL stamp such an answer ungrounded.

#### Scenario: Liquidus preference checked with margin and caveat
- **WHEN** the user asks whether FLiBe satisfies the coolant liquidus preference
- **THEN** a sandbox script compares the measured FLiBe liquidus (434 °C) to the stated 500 °C preference, the agent reports the 66 °C margin, and the answer states the 500 °C figure is a selection preference rather than a regulatory limit

#### Scenario: Missing threshold source is stamped ungrounded
- **WHEN** no resolvable threshold source exists for a requirement-satisfaction question
- **THEN** the agent does not assert satisfaction and stamps the answer ungrounded

### Requirement: Grounded cross-salt comparison for a safety function
The agent SHALL answer a comparative safety question (e.g. best natural-circulation decay-heat performance among the fluoride salts we hold) by aggregating the relevant `servedByProperty`-linked measurements across salts in a sandbox script, refusing to include a salt for which a required measurement is absent rather than guessing it.

#### Scenario: Comparison ranks only salts with real measurements
- **WHEN** the user asks which fluoride salt is best for the heat-removal function
- **THEN** a sandbox script ranks the salts using their real heat-capacity/viscosity/density measurements, and any salt lacking a required measurement is reported as excluded, not estimated
