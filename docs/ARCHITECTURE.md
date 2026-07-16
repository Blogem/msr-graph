# MSR Knowledge-Graph POC — Architecture

Status: **draft for review.** Ties together the data scope, vocabulary, and seed
ontology into a runnable pipeline. Two behaviours are the point of the POC and each gets
a concrete worked example below:

- **Self-evolving ontology** — new classes/properties detected from incoming data,
  proposed, human-reviewed, then merged. → worked example: *thermal conductivity*.
- **AI analysis grounded by graph + real data** — an LLM that understands the domain
  (graph) and computes over real values (table). → worked example in
  [ONTOLOGY.md](ONTOLOGY.md#how-the-ai-analysis-uses-it), recapped below.

## Components & data stores

| Component | Tech | Role |
|-----------|------|------|
| Structured loader | **Go** | Parse NIST CSVs, filter to fluoride subset, split salt formula+composition into constituents, load coefficients → SQLite, emit catalog triples → GraphDB. |
| NER / relation extraction | **Python + spaCy** | Link known entities (EntityRuler seeded from the SKOS vocab) and mine unknown terms; extract salt↔property↔value and salt↔reactor↔role relations. |
| Novelty miner + triage | **Python + LLM** | Score unlinked terms; classify candidates (property / class / instance / relation) and propose ontology placement. Python *only* because it reads spaCy's `Doc`/span output directly — see language boundary. |
| Review app | **Go + SvelteKit** | Render each proposal as a *visual* ontology diff + evidence; capture approve/edit/reject; commit approved changes via SPARQL graph ops. |
| Graph store | **GraphDB (Docker)** | Ontology (TBox) + instances (ABox) + SKOS vocab + provenance. RDF/SPARQL. |
| Value store | **SQLite** | Numeric coefficients (NIST + text-derived), keyed by `dataLocator`. The federated numbers. |
| Analysis agent | **Go + LLM** | Two tools — SPARQL over GraphDB, SQL over SQLite — plus equation evaluation. No ML dependency → follows the Go default. |

**Language boundary.** The rule: **Python only where there's a hard ML dependency
(spaCy); Go everywhere else.** NER + novelty mining + triage are one Python service —
they share spaCy `Doc`/span objects, and re-implementing that in Go would mean
serializing spaCy internals for no gain — and it emits finished *candidate proposals* as
data. Everything downstream (structured loader, review app, analysis agent) is Go, because
none of them touch spaCy; the LLM calls in triage and in the agent are just HTTPS to the
model and don't pull anything toward Python. Alternative seam if you want even less
Python: Python emits raw candidates + context and Go does the triage LLM step too — I'd
keep triage in Python for cohesion, but it's a clean cut either way.

## Pipeline

```
STRUCTURED                                   UNSTRUCTURED
NIST CSVs (fluoride subset)                  msr-archive OCR (~12 curated docs)
      │                                            │
      ▼                                            ▼
[Structured loader · Go]                     [spaCy NER + relation extraction]
      │                                       │                     │
      │  coefficients                  known entities         unknown terms
      ▼                                       │                     ▼
   SQLite  ◄───────────────┐                  │              [Novelty miner]
      │                    │ text-derived     │                     │
      └──► GraphDB catalog  values            │                     ▼
             (salts, PropertyMeasurement, mentions)         [Triage + LLM classifier]
                         ▲                                          │
                         │ back-populate                            ▼
                         │                                   Review queue ──► human (approve/edit/reject)
                         │                                          │
                         └──── [Apply: +ontology +vocab +EntityRuler ; version++] ◄┘

ANALYSIS:  [LLM agent] ──SPARQL──► GraphDB   +   ──SQL──► SQLite   ⇒ grounded answer
```

### Stages

0. **Acquisition** — NIST CSVs; msr-archive OCR sidecars for the ~12 curated docs
   (per [DATA_SCOPE.md](DATA_SCOPE.md)). IAEA safety docs are the stretch source.
1. **Structured ingest** — filter to fluoride rows; coefficients → SQLite; catalog
   triples (`MoltenSalt`, `Constituent`, `PropertyMeasurement` with `dataLocator`) →
   GraphDB. No numbers in the graph.
2. **Unstructured ingest + NER** — spaCy `EntityRuler`/`PhraseMatcher` seeded from the
   vocab (prefLabels + altLabels + chemical formulas) links *known* entities to concepts/
   classes with high precision; a statistical/noun-chunk pass surfaces *unknown* terms.
   Relation patterns produce salt↔property↔value and salt↔reactor↔role edges.
3. **Graph population** — linked entities/relations → ABox triples; text-derived property
   values → `PropertyMeasurement` (source = document) with the value stored in SQLite
   *alongside the NIST coefficients* (a `source` column distinguishes them — one uniform
   federation boundary).
4. **Self-evolution loop** — see next section (the centerpiece).
5. **Analysis** — the LLM agent answers questions using SPARQL + SQL + evaluation.

### Matching & OCR robustness (how fuzzy spaCy needs to be)

The corpus is OCR'd and spans five decades, so surface forms vary ("LiF-BeF2" /
"LiF·BeF₂" / "2LiF-BeF2", "THERMAL-STRE SS", spacing/case). Fuzziness is layered and
biased toward *linking to a known concept* (a fuzzy hit should resolve to an existing
concept, not spawn a false novelty candidate — otherwise the queue floods):

1. **OCR normalization pre-pass** — de-hyphenate line breaks, collapse stray spaces,
   normalize sub/superscripts and common OCR confusions. Removes most of the fuzz cheaply.
2. **Expanded exact matching** — feed the vocab's altLabels *plus generated variants*
   (hyphen/no-hyphen, spacing, case via `attr="LOWER"`) into spaCy `PhraseMatcher`. This
   turns most "fuzziness" into many cheap exact patterns — high precision.
3. **Chemical-formula normalizer** — salts get a dedicated parser, *not* fuzzy string
   matching: parse `LiF-BeF2` into (compound, fraction) sets so `BeF2-LiF` ≡ `LiF-BeF2`
   and composition variants unify structurally. Chemistry has structure; use it.
4. **Bounded fuzzy matcher** — for the long tail, a `rapidfuzz`/`spaczz` pass with a high
   threshold (~90) and a minimum token length catches OCR-mangled multi-word terms.
5. *(stretch)* embedding similarity for concept linking when lexical matching misses.

Net: **high-precision linking with bounded fuzziness.** Over-fuzzy matching pollutes both
the graph and the novelty queue, so the formula normalizer + expanded exact patterns do
most of the work and true fuzzy matching is a bounded fallback.

## Self-evolution mechanism

Nothing mutates the ontology automatically — the loop *proposes*, a human *disposes*.

1. **Detect.** A term extracted by NER that matches no known concept/altLabel/class is
   parked in a novelty queue instead of being discarded.
2. **Score.** Keep candidates above a corpus-salience threshold (document frequency —
   the same measure used to build the vocabulary).
3. **Triage by contextual signal** into a proposed change kind:
   - **Property** — co-occurs with a numeric value + a recognized physical **unit**
     (its dimension identifies the quantity), or matches a QUDT `QuantityKind` / INIS
     "thermodynamic properties" descriptor → propose a new `msr:PhysicalProperty`.
   - **Class** — appears in material/'`constructed of X`' or process contexts → propose a
     new subclass under an existing class.
   - **Instance** — matches a compound-formula or named-reactor pattern → a new individual.
     **Auto-accepted** straight into `<urn:msr:data>` (flagged `msr:autoAccepted true`,
     provenance kept) since the schema is unchanged; only property/class/relation changes
     hit the review gate.
   - **Relation** — recurring subject–verb–object between known types → propose a new
     object property.
4. **Ground & package.** An LLM classifier confirms the kind and proposes placement
   (broader class, `quantityKind`, `canonicalUnit`), justified by evidence: frequency,
   example sentences with document citations, and any external match (QUDT / INIS).
5. **Review gate.** The review app (Go + SvelteKit) renders the proposal as a **visual
   diff** — the affected ontology neighborhood with the new node/edges highlighted, the
   proposed `quantityKind`/`unit`/placement as editable fields, and an evidence panel of
   source sentences with highlighted spans and document links. (The underlying triples are
   available as a raw view, but the reviewer works with the rendered diff.) Approve / edit
   / reject.
6. **Apply.** On approval the candidate's named graph is promoted with a single graph op
   (`ADD <urn:msr:proposal/{id}> TO <urn:msr:ontology>`), status → `approved`, the ontology
   version is bumped with a PROV record (who / when / evidence), and the spaCy `EntityRuler`
   gains the new pattern so future mentions link automatically.
7. **Back-populate.** Previously-parked mentions are re-processed into instances now that
   a target exists.

### Where candidates live — staging by named graph

Candidates are **already in GraphDB the moment they're detected** — just isolated in
named graphs so they're trivially filterable:

| Named graph | Contents | In the default dataset? |
|-------------|----------|--------------------------|
| `<urn:msr:ontology>` / `<urn:msr:data>` / `<urn:msr:vocab>` | approved TBox / ABox / SKOS | **yes** |
| `<urn:msr:proposal/{id}>` | the proposed triples for one candidate | **no** |
| `<urn:msr:staging>` | `msr:ChangeProposal` resources (status, kind, evidence, provenance, link to the proposal graph) | **no** |

Because graph membership *is* the filter, the analysis agent and every normal query run
against the default dataset (the three core graphs) and **never see pending candidates** —
no status-flag filtering required. The review app queries `<urn:msr:staging>` to list
what's pending. Lifecycle:

- **detected** → proposed triples → `<urn:msr:proposal/{id}>`; a `ChangeProposal`
  (`msr:reviewStatus "pending"`) → `<urn:msr:staging>`.
- **approve** → `ADD <urn:msr:proposal/{id}> TO <urn:msr:ontology>` (or `…/data`); status → `approved`.
- **edit** → modify the proposal graph, then approve.
- **reject** → status → `rejected`; triples stay put (audit trail), never reach core.

This is exactly the property you asked for: everything is in the graph and queryable, but
the unreviewed material is one `FROM` clause away from being included or excluded.

## Worked self-evolution example — the birth of *solubility*

Seed state: the ontology carries eight properties and the vocabulary its 29 concepts —
neither contains **solubility**. NER is running over the MSR chemistry reports.

1. **Extract & miss.** Phrases like *"…the solubility of PuF₃ in the LiF-BeF₂ solvent is
   about 2 mol % at 565 °C…"* recur. "solubility" matches no seed concept or altLabel →
   parked in the novelty queue (not dropped).
2. **Score.** Document frequency = **280 / 637** — well above threshold, never linked.
   Strong candidate.
3. **Triage → property (with a genuine judgment call).** It sits next to a value + a unit,
   so it triages as a `PhysicalProperty`, and grounds to the **INIS descriptor SOLUBILITY**
   (RT dissolution, crystallization). But its *unit is ambiguous* — the corpus expresses
   solubility as mol %, wt %, or g·L⁻¹ by context. The LLM classifier flags this rather
   than guessing; this is exactly where human review earns its place (not rubber-stamping).
4. **Package** for review: frequency, example sentences with citations, the INIS grounding,
   and the proposed triples — with the unit deliberately left as a decision.
5. **Review gate** — the SvelteKit app renders a visual diff: a new `solubility` property
   node under `PhysicalProperty`, its evidence panel, and a **unit dropdown** the reviewer
   sets to *mole fraction*. Conceptually the change is:
   ```turtle
   + msr:solubility a msr:PhysicalProperty ;
   +     rdfs:label "solubility" ;
   +     msr:quantityKind qk:AmountOfSubstanceFraction ;   # reviewer's choice: mol fraction
   +     msr:canonicalUnit unit:MOL-PER-MOL ;
   +     rdfs:comment "Added by evolution loop; 280/637 docs; unit set by reviewer." ;
   +     skos:closeMatch voc:solubility .
   + voc:solubility a skos:Concept ; skos:inScheme voc:msr-scheme ;
   +     skos:prefLabel "solubility"@en ; skos:altLabel "miscibility"@en .
   ```
   → **approve.**
6. **Apply.** The proposal's named graph is promoted (`ADD <urn:msr:proposal/{id}> TO
   <urn:msr:ontology>`); ontology `0.1.0-seed → 0.2.0` with a PROV activity
   (`prov:wasAssociatedWith` the reviewer, `prov:used` the evidence); the EntityRuler gains
   `"solubility" → msr:solubility`.
7. **Back-populate.** Parked mentions become measurements — e.g. PuF₃ solubility in the
   fuel salt, value in SQLite (`source = document`):
   ```turtle
   msrd:m-flibe-puf3-solubility a msr:PropertyMeasurement ;
       msr:ofSalt msrd:msre-coolant ; msr:forProperty msr:solubility ;
       msr:hasUnit unit:MOL-PER-MOL ; msr:equationForm msr:DiscretePoint ;
       msr:dataLocator "chem-report/solubility#PuF3-in-LiF-BeF2" ; msr:citedIn msrd:ORNL-TM-2316 .
   ```

**Why this one matters:** solubility is **doubly new** — absent from *both* the structured
NIST DB and the seed vocabulary — so it's a genuine discovery, not a gap-fill. It also
forced a real human decision (which unit convention), showing the review gate contributes
judgment rather than rubber-stamping. And it gates reactor design (how much fissile the
salt can hold), so the graph grew a decision-relevant dimension purely from documents.

### Same mechanism, a new *class* + *relation* (not just a property)

The goal names classes too, and the loop generalizes. Candidate **"graphite"** (388/637
docs; "graphite-moderated" in 159) appears in a moderator context — *"the MSRE core is
moderated by graphite"*. It's outside the seed vocabulary and triages as a **class +
relation**: propose a new `msr:Moderator` class, an individual `msrd:graphite`, and a new
object property `msr:moderatedBy` (`MoltenSaltReactor → Moderator`). It grounds to INIS
`GRAPHITE` (UF "graphite moderator") and `MODERATORS`. On approval the ontology gains a
moderator branch and `msrd:MSRE msr:moderatedBy msrd:graphite` — reaching beyond salts and
properties into reactor structure. Same detect → triage → review → apply → back-populate
loop; only the *kind* of change differs.

## AI-analysis example (recap)

Detailed in [ONTOLOGY.md](ONTOLOGY.md#how-the-ai-analysis-uses-it): "density of this
LiF-BeF2 melt at 900 K?" → agent SPARQLs the graph for the measurement (Linear form,
in-range, locator), pulls `c0,c1` from SQLite, evaluates `2.413 − 4.88e-4·900 =
**1.974 g·cm⁻³**`. Graph = method, table = numbers. After the evolution example above,
the *same* agent can now also answer solubility questions — the analysis surface grows
automatically as the ontology evolves.

## Tech stack summary

- **GraphDB** (Docker, local) — RDF/SPARQL triple store.
- **SQLite** — federated numeric value store.
- **spaCy** — NER + relation extraction; `EntityRuler` synced from the vocab + approved
  concepts.
- **Go** — structured loader, analysis agent, and the review-app backend.
- **SvelteKit** — review-app frontend (visual ontology diffs + evidence panels).
- **Python** — the spaCy extraction service *only*: NER, novelty mining, triage.
- **LLM** — triage classification (in the Python service) and the analysis agent (in Go).

## Open questions for review

Decided:
- **Text-derived values** → stored in SQLite with a `source` column, alongside the NIST
  coefficients (one uniform federation boundary). ✓
- **Instance auto-accept** → new specific salts/compounds/reactors are inserted directly
  into `<urn:msr:data>` (flagged `msr:autoAccepted true`, provenance kept); only *schema*
  changes (new property / class / relation) go through the human review gate. ✓
- **Review app** → Go + SvelteKit rendering visual ontology diffs. ✓
- **Language boundary** → Python only for the spaCy extraction service; Go everywhere else. ✓

Open (build-time tuning, non-blocking):
- **Novelty salience threshold** — fixed document-frequency cutoff vs. relative/tf-idf.
- **Relation extraction depth** — dependency-pattern rules (cheaper, brittle) vs. an LLM
  extractor (richer, costlier) for salt↔property↔value edges.
