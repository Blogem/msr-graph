# Design: ingest-iaea-safety

## Context

The safety/requirements ambition is realized by **real data through the existing pipeline**,
not a bespoke schema (`docs/PROVENANCE_AND_TRUST_DESIGN.md` §4, principle 3 "only real data").
A feasibility spike (`docs/SAFETY_THREAD_SPIKE.md`) established, with cached real sources, that:

- the requirement layer exists in real text — IAEA SRS-123 §2.1.2.5 (the three fundamental safety
  functions) and the GIF/ORNL docs that tie those functions to coolant thermophysical properties;
- the value layer already exists in the graph — NIST + ORNL property measurements for the FLiBe
  salt individual and its `msr:PhysicalProperty` nodes (`density`, `viscosity`, `vaporPressure`,
  `specificHeat`, `thermalConductivity`, `meltingPoint` are all in the seed T-Box);
- the tie is a **cross-document join on shared salt + property entities**, legitimate for a KG
  digital thread because each edge is individually grounded — no single sentence says
  "requirement R needs property P of salt S", and none is fabricated.

This change is the plan's **chunk 11**, deferred until chunks 6–10 + 13 land (see the proposal's
Prerequisites). It reuses, per genre, the chunk-5 corpus pipeline, the chunk-6 NER/mention layer,
the chunk-7 relation extractor, the chunk-8 novelty miner, the chunk-9 approval engine, and the
chunk-4 agent — adding only what the safety genre needs.

Binding contracts (unchanged, inherited):

- **Write path** — Python extraction writes via SPARQL UPDATE over the GraphDB HTTP endpoint with
  explicit `GRAPH` targets and deterministic IRIs (chunk 5 D6).
- **Provenance** — every fact-bearing individual carries `prov:wasDerivedFrom` (a `Document`) +
  `prov:wasGeneratedBy` a stable `Activity`, with the per-run activity in `urn:msr:provenance`
  (chunk 12 / `provenance-run-lineage`).
- **Grounding** — mentions resolve via `msr:linksTo`; properties resolve by `rdfs:label` match; no
  `skos:closeMatch` hop (chunk 4 / `ground-demo-in-real-docs`).
- **Evolution** — novel concepts enter core only via approved chunk-9 proposals; instance-kind
  candidates may write directly to `urn:msr:data` flagged `msr:autoAccepted` (chunk 8).

## Goals / Non-Goals

**Goals:**

- Acquire, text-extract, and normalize/segment the four cached safety sources (MSR-relevant sections
  only) under a committed attributed manifest; write attributed `msr:Document` nodes.
- Grow the `Safety` branch (`SafetyFunction`, `Requirement`, `Confinement`, `DefenceInDepth`,
  `DesignBasis`) from the safety genre via the miner + approval engine — nothing seeded.
- Extract the `msr:servedByProperty` and `msr:addressesFunction` edges with evidence + provenance,
  asserted only where a source sentence states the dependency; optional `rdfs:seeAlso` to named IAEA
  standards.
- Let the unchanged agent answer the six stakeholder questions (spike doc), each grounded and honestly
  caveated (soft criteria, cross-document join, gap disclosure).
- Extend the SHACL catalogue to require provenance + a source on safety node kinds.

**Non-Goals:**

- No hand-authored safety schema — every safety class/relation enters core via an approved proposal
  (the demo _is_ the growth). <<this relies on the security domain to surface via the ontology candidates. if this doesn't happen well enough, we can author a special ontology for saftey>>
- No safety→salt or safety→numeric-value edge — the tie is transitive through `PhysicalProperty`; no
  source states a direct requirement→value link, so none is asserted.
- No SHACL gate on requirement satisfaction — thresholds are soft criteria evaluated by the agent, not
  database constraints.
- No re-OCR / no committing PDFs or full text — attribution + short evidence quotes only (IAEA ©).
- No new agent tools — the Safety branch reaches the agent through the KG-schema prompt (chunk 4).
- No INIS thesaurus load (would make safety terms "known" and kill the mining demo — `DATA_SCOPE.md`).

## Decisions

### D1 — Safety-source acquisition: tracked script + manifest, gitignored PDF/text cache

`scripts/fetch-safety-sources.sh` (already added by the spike) downloads the four sources into
`data/safety/` (gitignored, like `data/corpus/`). A pypdf-based `safety extract` step converts each
cached PDF to `{id}.txt`; the existing chunk-5 normalizer + segmenter then produce
`data/safety/{id}/normalized.txt` + `segments.jsonl` — the identical pipeline-input format the NER
stages already consume, so the safety genre is "just another corpus" downstream.

- **Section scoping** — a committed per-source manifest names the ingested page/section ranges
  (SRS-123 §2.1.2.5 MSRs, §3.2 Design, §5.1.8 safeguards; the GIF/ORNL docs whole). Scoping keeps the
  genre focused and stops 292 pp of general standards text from flooding the miner and the cached
  KG-schema prompt.
- **Why pypdf, not the chunk-5 OCR path** — the safety sources are text-layer PDFs, not scanned OCR
  sidecars; a text extract is cleaner than OCR. The extractor is a thin new stage; everything after it
  reuses chunk 5.
- **Why not commit the text** — IAEA SRS-123 is © all-rights-reserved; committing the PDF or full text
  is redistribution. The tracked artifacts are the fetch script + the attributed manifest; the cache is
  reproducible via the script. Mirrors how the msr-archive corpus is handled.

### D2 — Attributed `Document` nodes

One `msr:Document` per source keyed by a stable identifier (`msrd:PUB2027-SRS-123`,
`msrd:GIF-Holcomb-MSR-safety`, `msrd:ORNL-TM-2006-12`, `msrd:ORNL-MSR-tech-safety`), carrying
`rdfs:label` (title), `dcterms:identifier`, `dcterms:date`, and — new for this genre —
`dcterms:publisher`, `dcterms:rights`, and `dcterms:source` (URL). Written additively to `urn:msr:data`
with the chunk-12 provenance edges. Attribution is mandatory (D5) so any surfaced quote is attributable.

### D3 — The Safety branch is grown, not seeded (headline demo)

The five safety classes and the two linking relations enter the ontology **only** via approved chunk-9
proposals mined by chunk 8 over the safety genre. Two genre-specific needs the miner must gain:

1. **Multi-word candidate extraction.** Chemistry novelties are largely single tokens (`solubility`,
   `graphite`); safety concepts are noun phrases (_"confinement of radioactive material"_, _"defence in
   depth"_, _"removal of residual heat"_). The miner's salient-term extraction is extended to noun-phrase
   candidates for this genre (chunk phrases, not just unigrams), with the same document-frequency scoring
   over the safety set and evidence sentences from the sources.
2. **Genre-aware triage.** The chunk-8 DeepSeek-Flash triage classifier is prompted with the safety
   genre so it proposes the `SafetyFunction`/`Requirement`/… class kinds; the ChangeProposal
   mini-schema and staging/approval routing are unchanged.

- **Why grown, not seeded** — seeding safety classes would violate principle 3 and, worse, remove the
  demo: the whole point is that a _new domain_ (safety) grows the ontology through the same reviewed
  loop. The reviewer approves `SafetyFunction` the way they approve `Moderator`.
- **Risk** — safety-concept mining is harder and lower-precision than single-term chemistry mining
  (see Risks). The reviewer gate (chunk 9) absorbs precision misses; the acceptance criteria require the
  three fundamental safety functions to surface as proposals, not a precision bar on all safety terms.

### D4 — The digital-thread relations, asserted only where text supports them

Two object properties, grown with the branch and written by the chunk-7 relation extractor over the
safety genre:

- `msr:servedByProperty` : `SafetyFunction → PhysicalProperty`. Asserted only when a source sentence
  states the dependency. Grounding examples (real): `msrd:sf-heat-removal msr:servedByProperty
msr:specificHeat , msr:viscosity` (GIF Holcomb: _"heat capacity … and viscosity for natural
  circulation cooling"_); `msrd:sf-confinement msr:servedByProperty msr:vaporPressure` (GIF Holcomb:
  _"low pressure … large margin to boiling"_).
- `msr:addressesFunction` : `Requirement → SafetyFunction`. A requirement statement addresses a
  fundamental safety function (e.g. a coolant-selection requirement addresses heat removal).

Each edge is **evidence-bearing and provenance-complete**: the extractor writes, alongside the edge, the
linking `msr:Mention`(s) for the source span (reusing the chunk-6 mention layer: `surfaceForm`,
`inDocument`, `startOffset`/`endOffset`, `linksTo` the safety individual and the property), and the edge
carries the chunk-12 `prov:wasDerivedFrom` the safety `Document` + `prov:wasGeneratedBy` the
safety-extraction `Activity`. The **tie to a salt is transitive**, never asserted directly:

```
SafetyFunction ─servedByProperty▶ PhysicalProperty ◀forProperty─ PropertyMeasurement ─ofSalt▶ MoltenSalt
```

- **Optional standards alignment** — `rdfs:seeAlso` from a `SafetyFunction`/`Requirement` to a named
  IAEA standard identifier (e.g. an IRI/literal for "IAEA SSR-2/1", "IAEA SF-1") **only** where the
  source text names the standard. This is the opportunistic alignment of `PROVENANCE_AND_TRUST_DESIGN.md`
  §6 — never forced, never imported wholesale.
- **Why a new relation, not `rdfs:seeAlso` for the property link** — `servedByProperty` is a _domain
  relation extracted from real text with evidence_, not a schema-mapping assertion; it is exactly the
  kind of relation chunk 7 already extracts (salt→property→value), applied to a new subject kind. Modeling
  it as `seeAlso` would discard its evidence/provenance semantics.

### D5 — Requirement thresholds are soft; satisfaction is an agent computation, never a gate

Some requirements carry a numeric threshold (_"liquidus preferably lower than 500 °C"_,
ORNL/TM-2006/12). When explicitly stated, a `Requirement` may carry `msr:thresholdValue`,
`msr:thresholdComparator` (`lt`/`lte`/`gt`/`gte`), and `msr:thresholdUnit` — extracted only when the
text states them. **Requirement satisfaction is computed by the agent** (a sandbox script comparing the
extracted threshold to the measured value, e.g. FLiBe liquidus 434 °C vs the 500 °C preference →
66 °C margin) and reported **with the soft-criterion caveat**: the 500 °C figure is a selection
_preference_, not a licensing limit. It is never a SHACL constraint — the database does not reject a salt
for exceeding a preference.

### D6 — Provenance & SHACL inheritance (extend, don't reinvent)

Safety documents, mentions, safety individuals, and the two linking edges are fact-bearing and follow
the chunk-12 model unchanged: stable `Activity` IRI referenced by `prov:wasGeneratedBy` in
`urn:msr:data`, per-run `Activity` (agent, timestamps, ontology version) appended to `urn:msr:provenance`,
`prov:wasDerivedFrom` the safety `Document`. The chunk-13 SHACL catalogue is **extended** with shapes
requiring: every `SafetyFunction`/`Requirement`/safety `Mention` carries `wasDerivedFrom` + a source;
every `servedByProperty` edge has a `PhysicalProperty` target that exists in core; every
`addressesFunction` edge targets a `SafetyFunction`. No threshold/satisfaction shape (D5).

### D7 — The agent answers the stakeholder questions with no new tools

The Safety branch reaches the agent through the cached KG-schema system prompt, rebuilt on the
`owl:versionInfo` bump the chunk-9 approval emits (chunk 4 mechanism) — so the schema-generic agent sees
`SafetyFunction`, `servedByProperty`, etc. without code change. The six spike questions map to existing
tool paths:

- **Evidence chain / gap disclosure** — `sparql_query` traversals: function → `servedByProperty` →
  property → `forProperty` measurement → `ofSalt` salt, plus the `prov:wasDerivedFrom` chain; a _gap_ is
  a `FILTER NOT EXISTS` for a measurement of a linked property for a given salt.
- **Requirement satisfaction / envelope / comparison / composition trade-off** — `sparql_query` to fetch
  thresholds + measurements, then `run_python` in the sandbox to compute margins, check `validTempMin/Max`
  coverage, and rank salts. All arithmetic stays in the sandbox (chunk 4 contract).

The agent's existing grounded-vs-ungrounded stamp (chunk 12) already forces the honest caveats: a
requirement-satisfaction answer without a resolvable threshold source is stamped ungrounded; a comparison
naming a salt with no measurement is refused, not guessed.

### D8 — Package layout, CLI, run model

The extraction package gains a `safety` subcommand group mirroring `ingest`: `safety fetch` (calls the
tracked script), `safety extract` (pypdf → `{id}.txt`), and a `safety ingest` umbrella that runs
extract → normalize/segment → document-nodes, then the shared NER → relation → miner stages over the
safety genre. `make ingest-safety` is a one-shot Compose run of the extraction container. Config
(source list, section scope, cache path) is read from the committed manifest, injected for tests.

### D9 — Test strategy: hermetic units + a guarded integration, committed short-quote fixtures

- **pypdf extractor** — a tiny committed text-layer PDF fixture → expected text (no network).
- **Section scoping** — manifest-driven page/section selection picks the right span from a fixture.
- **Multi-word candidate extraction** — fixture safety sentences → the expected noun-phrase candidates
  (`"confinement of radioactive material"`, `"defence in depth"`), single-token noise excluded.
- **Genre-aware triage** — stubbed-Flash returns fixed classifications → proposal graphs validate against
  the chunk-8 mini-schema with the `SafetyFunction`/`Requirement` kinds.
- **Linking extraction** — stubbed-Flash fixture sentences → the expected `servedByProperty` /
  `addressesFunction` edges + evidence mentions + provenance; a sentence that does **not** state a
  dependency yields **no** edge (precision guard); an edge to an unknown property IRI is rejected.
- **Threshold extraction** — the ORNL/TM-2006/12 liquidus-preference sentence → `thresholdValue 500`,
  `comparator lt`, `unit K/°C`; a sentence with no threshold yields none.
- **Agent** (stubbed LLM + fake pool) — evidence-chain traversal returns the provenance chain; the gap
  query returns the missing-measurement set; requirement-satisfaction computes the 434 vs 500 margin in a
  sandbox script and the answer carries the soft-criterion caveat; an ungrounded safety claim is stamped
  ungrounded.
- **SHACL** (opt-in, GraphDB-required) — a safety individual missing `wasDerivedFrom` is rejected;
  valid safety facts load.
- **Guarded corpus integration** (opt-in env flag) — after a real `make ingest-safety`: the four safety
  `Document` nodes present with attribution; the three fundamental safety functions surfaced as proposals;
  after approval, `msrd:sf-heat-removal msr:servedByProperty msr:specificHeat` resolvable and traceable to
  a salt measurement; a second run leaves `urn:msr:data` triple counts unchanged.

Committed fixtures use **short** attributed quotes only (respecting D5/IAEA ©), version-controlling the
exact evidence the spike relied on.

## Risks / Trade-offs

- **Safety-concept mining is lower-precision than single-term chemistry mining** (multi-word phrases,
  standards boilerplate). → Mitigation: noun-phrase candidates + genre-aware triage (D3); the chunk-9
  reviewer gate absorbs misses; acceptance requires the three fundamental functions to surface, not a
  blanket precision bar.
- **Over-asserting the digital-thread edge** where the text only _co-mentions_ a function and a property.
  → Mitigation: the extractor asserts `servedByProperty` only on an explicit dependency statement, pinned
  by the negative test (co-mention ≠ edge); every edge is evidence-bearing and reviewer-visible.
- **IAEA licensing** — verbatim redistribution is disallowed. → Mitigation: no PDF/full-text commit
  (D1); mandatory attribution (D2/D5); short evidence quotes only; fetch-on-demand cache.
- **PUB2027 is thin on MSR specifics** (a standards-gap analysis, not a property source). → Accepted &
  designed for: SRS-123 supplies the _safety-function taxonomy_ (top of the thread); the property-level
  requirement text comes from the GIF/ORNL sources. The manifest scopes SRS-123 to its MSR sections.
- **A GIF MSR-specific Safety Design Criteria (SDC) report is not yet public** (only VHTR/LFR SDC exist).
  → Accepted: the GIF Holcomb MSR safety analysis is the public stand-in for the requirement-function
  layer; when an MSR SDC lands it is a new source added to the manifest, no schema change.
- **Depends on five not-yet-built chunks** (7–10, 13). → Accepted: authored now as the stretch change so
  the cached sources and grounded thread are captured; implementation is sequenced after M6 + P3.5.

## Migration Plan

Additive and greenfield for the safety genre; no change to existing seed, loader, or agent code paths.
Order (once prerequisites are green): `make ingest-safety` runs fetch → extract → normalize/segment →
document-nodes → NER → relations → mine; the reviewer approves the safety proposals via the chunk-9 API;
the agent picks up the branch on the version bump. Re-running is idempotent (deterministic IRIs;
`INSERT DATA` no-ops; per-run provenance appends). Rollback = restore a pre-ingest checkpoint (chunk 9)
or delete `data/safety/` + the safety triples; nothing outside `data/safety/`, `urn:msr:data`/
`urn:msr:provenance`, the mined proposals, and the `DATA_SCOPE.md` edit is touched.

## Open Questions

- **`servedByProperty` cardinality and evidence modeling** — whether to reify each edge as a small
  evidence node (edge + `citedIn` + span) or keep the edge plus separate linking `Mention`s (current
  design, D4). Resolve at build against how chunk 7 ends up modeling measurement evidence, to stay
  consistent with the built relation extractor.
- **Standard-identifier IRIs for `rdfs:seeAlso`** — mint local IRIs for named IAEA standards vs. link to
  an external scheme (e.g. an IAEA/OSTI identifier). Decide when the first standard is actually named in
  the ingested sections; keep it opportunistic, not a loaded standards catalogue.
