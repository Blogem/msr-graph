## ADDED Requirements

### Requirement: Safety-function to property links asserted only from stated dependencies
The system SHALL extract `msr:servedByProperty` edges (`msr:SafetyFunction → msr:PhysicalProperty`) from the safety genre **only** where a source sentence explicitly states that the safety function depends on / is served by the property. A mere co-mention of a function and a property in the same sentence SHALL NOT produce an edge. Each edge's `PhysicalProperty` target MUST already exist in core; an edge to an unknown property IRI SHALL be rejected. No `msr:SafetyFunction → msr:MoltenSalt` and no `msr:SafetyFunction → value` edge SHALL be asserted — the tie to a salt is transitive through the shared `PhysicalProperty`.

#### Scenario: Stated dependency produces an edge
- **WHEN** a source states heat removal relies on the salt's heat capacity and viscosity
- **THEN** `msrd:sf-heat-removal msr:servedByProperty msr:specificHeat , msr:viscosity` is asserted, targeting the existing seed `PhysicalProperty` individuals

#### Scenario: Co-mention without a stated dependency produces no edge
- **WHEN** a sentence names a safety function and a property but states no dependency between them
- **THEN** no `msr:servedByProperty` edge is asserted for that sentence

#### Scenario: No direct safety-to-salt or safety-to-value edge
- **WHEN** the safety linking extractor runs
- **THEN** no triple directly relates a `msr:SafetyFunction` to a `msr:MoltenSalt` or to a numeric value; the only salt tie is the transitive path `SafetyFunction → servedByProperty → PhysicalProperty ← forProperty ← PropertyMeasurement → ofSalt → MoltenSalt`

### Requirement: Requirement to safety-function links
The system SHALL extract `msr:addressesFunction` edges (`msr:Requirement → msr:SafetyFunction`) where a source states that a requirement addresses a fundamental safety function.

#### Scenario: Requirement addresses a function
- **WHEN** a source states a coolant-selection requirement that serves heat removal
- **THEN** `msr:addressesFunction` is asserted from the `Requirement` individual to `msrd:sf-heat-removal`

### Requirement: Linking edges are evidence-bearing and provenance-complete
The system SHALL write, alongside each `msr:servedByProperty` / `msr:addressesFunction` edge, the linking `msr:Mention`(s) for the source span (`msr:surfaceForm`, `msr:inDocument`, `msr:startOffset`/`msr:endOffset`, `msr:linksTo`) and SHALL attach the provenance edges (`prov:wasDerivedFrom` the safety `Document`, `prov:wasGeneratedBy` the safety-extraction `Activity`). Edges and evidence use deterministic IRIs and additive writes so re-runs are no-ops.

#### Scenario: Edge carries resolvable evidence and provenance
- **WHEN** a `msr:servedByProperty` edge is written
- **THEN** its source span is recoverable via the linked `msr:Mention` in a safety `Document`, and the edge carries `prov:wasDerivedFrom` that document and `prov:wasGeneratedBy` the extraction activity

### Requirement: Opportunistic standards alignment
The system SHALL assert `rdfs:seeAlso` from a `msr:SafetyFunction`/`msr:Requirement` to a named IAEA safety-standard identifier **only** where the source text names the standard. Standards SHALL NOT be imported wholesale, and the alignment SHALL NOT be forced where the text does not name a standard.

#### Scenario: Named standard is aligned; unnamed is not
- **WHEN** a source names an IAEA standard (e.g. SSR-2/1) as the basis for a safety function
- **THEN** `rdfs:seeAlso` is asserted to that standard's identifier; **WHEN** no standard is named for a function, no `rdfs:seeAlso` is asserted

### Requirement: Requirement thresholds are soft, extracted only when stated
The system SHALL extract `msr:thresholdValue`, `msr:thresholdComparator` (`lt`/`lte`/`gt`/`gte`), and `msr:thresholdUnit` on a `msr:Requirement` only where the source states a numeric threshold. These thresholds SHALL NOT be enforced by SHACL; requirement satisfaction is computed by the agent (see `analysis-agent`) and reported as a soft criterion.

#### Scenario: Stated threshold is captured
- **WHEN** a source states a liquidus preference below 500 °C for coolant selection
- **THEN** the `Requirement` carries `msr:thresholdValue`, a `msr:thresholdComparator` of `lt`, and the temperature unit

#### Scenario: No threshold stated, none asserted
- **WHEN** a requirement is qualitative with no numeric threshold
- **THEN** no threshold properties are asserted on it
