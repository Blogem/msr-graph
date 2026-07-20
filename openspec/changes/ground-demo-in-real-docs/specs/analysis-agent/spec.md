# analysis-agent (delta)

## MODIFIED Requirements

### Requirement: `sparql_query` grounds through the core-dataset client
The agent SHALL expose a `sparql_query` tool that runs SPARQL SELECT queries through the chunk-1 `internal/graph` core-dataset client (`Select`), so queries evaluate against exactly the three core graphs and staging/proposal graphs are invisible. The tool SHALL NOT expose the unrestricted (`SelectRaw`) path. Grounding SHALL resolve a **salt** reference to its `msr:MoltenSalt` individual by matching a real document `msr:Mention`'s `msr:surfaceForm` (optionally expanding the query term through a SKOS `prefLabel`/`altLabel` synonym in the vocab) and following `msr:linksTo` from that Mention to the salt; the matched Mention (with `msr:inDocument` + provenance) is the traceable evidence. Grounding SHALL resolve a **physical property** reference by matching the query's property term against the `rdfs:label` of a `msr:PhysicalProperty` term directly. Grounding SHALL NOT use `skos:closeMatch` at all — neither salt↔concept nor property-term↔concept; the SKOS vocab supplies labels for recognizing/expanding the query term only, and is never traversed as a grounding edge. No salt or property name is hardcoded in the agent.

#### Scenario: A salt reference grounds to a measurement via a real mention
- **WHEN** the agent issues a `sparql_query` to ground the salt reference "LiF-BeF₂ (66-34 mol%)"
- **THEN** the query matches a real `msr:Mention` whose `msr:surfaceForm` denotes that composition, follows `msr:linksTo` to the `msr:MoltenSalt` individual, and returns a `PropertyMeasurement` with its property, unit, equation form, valid temperature range, and a `dataLocator`

#### Scenario: A property grounds by its own label
- **WHEN** the agent grounds the property term "density"
- **THEN** the query matches `?prop a msr:PhysicalProperty ; rdfs:label "density"` directly, with no `skos:closeMatch` traversal

#### Scenario: Grounding uses no closeMatch anywhere
- **WHEN** the agent grounds any salt or property reference
- **THEN** the resolution paths are `Mention.surfaceForm → msr:linksTo → msr:MoltenSalt` (salts) and `rdfs:label → msr:PhysicalProperty` (properties), and no `skos:closeMatch` is required or present in the grounding path

#### Scenario: Staging is invisible to grounding
- **WHEN** a triple exists only in `urn:msr:staging` and the agent grounds via `sparql_query`
- **THEN** the staging triple does not appear in the tool result, because the tool reads through the core-dataset client

### Requirement: End-to-end grounded density answer
The agent SHALL answer "density of FLiBe (the LiF-BeF₂ 66-34 mol% melt) at 900 K" as approximately **1.974 g·cm⁻³**, produced by grounding the salt reference to `msrd:salt-BeF2-LiF-34.0-66.0` (canonical form `BeF2-LiF | 34.0-66.0`) through a real `msr:Mention` — the linker-resolved `"LiF-BeF, (66-34 mole %)"` span from `ORNL-TM-2316`, whose `msr:linksTo` points at that salt — then reading its density measurement, fetching the coefficients (`c0=2.413`, `c1=-4.88e-4`) from `measurement_value` by the `dataLocator` `nist-srd27/density#BeF2-LiF|34.0-66.0`, and evaluating `c0 + c1·T` at T=900 in a sandbox script — with the final number equal to the script output. All grounding data is real: the salt and measurement come from `loader nist` (vendored NIST CSV) and the grounding link is a real document mention (no hand-curated seed, no `skos:closeMatch`). The demo presupposes the real pipeline (`loader nist` + `ingest` + `link`) has built the graph. (Full generation provenance — the extraction `Activity` and the dataset DOI — is added by the follow-on `provenance-model` change; a measurement↔document `msr:citedIn` edge awaits real citation extraction in chunk 7. This change requires only the mention's `msr:inDocument` to make grounding document-traceable.)

#### Scenario: Density question answered from real-mention grounding via a script
- **WHEN** the agent is asked for the density of FLiBe (LiF-BeF₂ 66-34 mol%) at 900 K after `loader nist` + `ingest` + `link` have run
- **THEN** the trace shows SPARQL grounding through a real `msr:Mention` (`surfaceForm → msr:linksTo → msrd:salt-BeF2-LiF-34.0-66.0`) and its density measurement, a coefficient fetch by the `dataLocator`, and a `script_run` evaluating the equation, and the final answer is ≈ 1.974 g·cm⁻³ equal to the script output

#### Scenario: Grounding traces to a real document
- **WHEN** the grounded answer is inspected
- **THEN** the matched `msr:Mention` names its `msr:inDocument` (`ORNL-TM-2316`), so the grounding itself — not just the measurement — is traceable to a real document (the fuller PROV chain is added by `provenance-model`)
