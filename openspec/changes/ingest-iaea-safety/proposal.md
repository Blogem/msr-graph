# Proposal: ingest-iaea-safety

## Why

The MSR-safety / requirements / regulatory-traceability ambition (`docs/NOTES.md`,
`docs/PROVENANCE_AND_TRUST_DESIGN.md` §4) is deliberately **not** a hand-authored schema.
It is realized by ingesting **real IAEA/GIF/ORNL safety documentation** as a second NER
genre and growing a `Safety` ontology branch through the *same* evolution loop that grows
the chemistry branch — then linking that branch to the salt-property data we already hold,
so a safety claim can be traced to a measured value and its source.

A feasibility spike (`docs/SAFETY_THREAD_SPIKE.md`) proved one thread end to end on real
data, with nothing fabricated:

- **IAEA SRS-123 (PUB2027) §2.1.2.5** states the three fundamental safety functions —
  *confinement of radioactive material, control of reactivity, heat removal*.
- **GIF (Holcomb) MSR Safety Analysis** ties them to salt thermophysical properties verbatim:
  confinement ← *"low pressure … large margin to boiling"*; heat removal ← *"heat capacity,
  thermal expansion, and viscosity for natural circulation cooling"*.
- **ORNL/TM-2006/12** organises coolant selection by exactly the properties we hold (melting
  point, vapor pressure, viscosity, thermal conductivity, heat capacity), with LiF-BeF₂ values.
- The join key — the **FLiBe salt individual** and its `msr:PhysicalProperty` nodes — already
  exists in the graph (loaded from NIST + the ORNL corpus). FLiBe is grounded across NIST (all
  four property files), ORNL-4658 (liquidus 434 °C, cₚ 0.577 cal g⁻¹°C⁻¹), and ORNL-TM-2316.

This change adds the safety branch and the linking edges; it does **not** invent the
connection — every node and edge is asserted only where a real source sentence supports it.

## Prerequisites (this is a stretch change on not-yet-built foundations)

Per `docs/IMPLEMENTATION_PLAN.md`, chunk 11 depends on chunks 6–10 and inherits the P3.5
trust contract. Built today: chunks 1–6, `provenance-model` (12). **Not yet built and
required before this change is implemented:** 7 `extract-property-relations`,
8 `mine-ontology-candidates`, 9 `apply-ontology-changes`, 10 `web-frontend`, and
13 `shacl-validation`. This proposal is authored now (while the spike sources are fresh and
cached) as the **stretch/post-M6** change; implementation waits on those chunks.

## What Changes

- **Safety-source acquisition (new genre)**: `scripts/fetch-safety-sources.sh` populates the
  gitignored cache `data/safety/` (IAEA SRS-123, GIF Holcomb MSR safety analysis, ORNL/TM-2006/12,
  ORNL MSR technical-&-safety considerations); a pypdf text-extraction step produces `{id}.txt`;
  the existing corpus-normalization + segmentation pipeline (chunk 5) then produces
  `normalized.txt` + `segments.jsonl` per safety document. Only the MSR-relevant sections are
  ingested (SRS-123 §2.1.2.5 / §3.2 / §5.1.8; the GIF/ORNL docs are MSR-specific throughout).
  A **committed, attributed manifest** records source, URL, section scope, and rights — no PDF or
  full text is committed (IAEA © all-rights-reserved).
- **Safety `Document` nodes with attribution**: one `msr:Document` per source keyed by identifier,
  carrying `dcterms:publisher`, `dcterms:rights`, and `dcterms:source` (URL), written to
  `urn:msr:data` with the chunk-12 provenance edges.
- **Safety branch grown via the evolution loop (the headline demo)**: the classes
  `msr:SafetyFunction`, `msr:Requirement`, `msr:Confinement`, `msr:DefenceInDepth`,
  `msr:DesignBasis` are **mined as change proposals** (chunk 8) from the safety genre and approved
  (chunk 9) — **not seeded**. This is the self-evolving-ontology demo on a second, higher-stakes genre.
- **The digital-thread linking edges**: `msr:servedByProperty` (`SafetyFunction → PhysicalProperty`)
  and `msr:addressesFunction` (`Requirement → SafetyFunction`), extracted from safety text and
  **asserted only where a source sentence states the dependency**, each evidence-bearing (linked to
  the source `Mention`/`Document`) and provenance-complete. Optional `rdfs:seeAlso` from a
  `SafetyFunction`/`Requirement` to a named IAEA standard identifier where the text names one
  (the opportunistic standards alignment per `PROVENANCE_AND_TRUST_DESIGN.md` §6). No direct
  safety→salt or safety→value edge is asserted (none is stated in any source); the tie to a salt
  is transitive through the shared `PhysicalProperty`.
- **Agent answers the stakeholder questions**: the schema-generic agent (chunk 4) picks up the
  Safety branch via its per-request KG-schema-prompt version check and answers the regulator/engineer
  questions in `docs/SAFETY_THREAD_SPIKE.md` — evidence-chain, evidence-gap disclosure,
  requirement-satisfaction-with-margin (with the soft-criterion caveat), operating-envelope coverage,
  and cross-salt comparison — each grounded, traced, and honestly caveated.

## Capabilities

### New Capabilities

- `safety-source-acquisition`: fetch + text-extract + normalize/segment the IAEA/GIF/ORNL safety
  sources into the gitignored `data/safety/` cache under a committed attributed manifest, ingesting
  only the MSR-relevant sections, and write attributed `msr:Document` provenance nodes.
- `safety-ontology-evolution`: grow the `Safety` branch (`SafetyFunction`, `Requirement`,
  `Confinement`, `DefenceInDepth`, `DesignBasis`) from the safety genre through the chunk-8 miner and
  chunk-9 approval engine — multi-word safety-concept candidates, genre-aware triage, evidence-bearing
  proposals — without seeding any safety class.
- `safety-property-linking`: the `msr:servedByProperty` and `msr:addressesFunction` relations and the
  optional `rdfs:seeAlso` standards alignment — extracted with evidence + provenance, asserted only
  where the source text supports them, forming the traceable requirement→function→property→value→salt
  thread.

### Modified Capabilities

- `analysis-agent`: answer safety-traceability questions over the grown Safety branch — evidence
  chains, evidence-gap disclosure, requirement-satisfaction with margin and the soft-criterion caveat,
  and cross-salt comparison — reusing the existing tools and grounding/provenance stamping (no new
  hardcoded safety terms; the branch reaches the agent through the KG-schema prompt).

## Impact

- **New code**: a safety-acquisition module + pypdf text extractor in the extraction package (reusing
  the chunk-5 normalizer/segmenter and the chunk-6/7/8 mention/relation/miner stages for the new
  genre); genre-aware candidate extraction for multi-word safety concepts; the two linking relations
  in the relation-extraction stage.
- **Scripts/data**: `scripts/fetch-safety-sources.sh` (tracked) and the gitignored `data/safety/`
  cache; per-source `normalized.txt` + `segments.jsonl` under `data/safety/{id}/`.
- **Ontology**: no seed change — `msr:SafetyFunction` et al. and the `msr:servedByProperty` /
  `msr:addressesFunction` relations enter `urn:msr:ontology` **only** via approved chunk-9 proposals;
  the safety-relevant `msr:PhysicalProperty` individuals they link to (`vaporPressure`, `specificHeat`,
  `thermalConductivity`, `meltingPoint`) already exist in the seed T-Box.
- **Provenance & SHACL**: safety documents, mentions, safety individuals, and the linking edges are
  fact-bearing → carry the chunk-12 provenance edges; the chunk-13 SHACL shape catalogue is extended to
  require provenance + a source on the safety node kinds. Requirement thresholds are **not** SHACL-gated
  (soft criteria).
- **Docs**: `docs/SAFETY_THREAD_SPIKE.md` (the spike + stakeholder questions, already added) is the
  design input; `docs/DATA_SCOPE.md` §4 updated from "stretch/deferred" to the finalized ingested set +
  section scope + attribution.
- **Depends on**: chunks 6–10 and 12–13 (see Prerequisites). **Downstream**: none — this is the final
  stretch genre; it grows the agent's and frontend's answer surface with no change to their contracts.
