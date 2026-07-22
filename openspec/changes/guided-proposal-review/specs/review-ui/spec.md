## ADDED Requirements

### Requirement: Placement and unit use typed, kind-aware pickers
The detail view SHALL present placement and unit as **typed pickers**, not free text: a parent-class picker sourced from `GET /api/ontology/classes` and a unit picker sourced from `GET /api/units` (the QUDT allowlist). Each picker SHALL be **pre-filled with the model's suggested value and its confidence** where a suggestion exists. Fields SHALL be **kind-aware** — a field irrelevant to the proposal's derived kind SHALL be hidden (no unit picker for a class; no parent/subClassOf picker for a property). Where the proposal permits a value outside the offered list (e.g. proposing a genuinely new parent), the picker SHALL allow an explicit custom entry rather than silently accepting arbitrary text.

#### Scenario: Unit picker is populated from the allowlist and pre-filled with the suggestion
- **WHEN** the reviewer opens a property proposal carrying a suggested unit
- **THEN** the unit picker offers the allowlisted QUDT units and is pre-filled with the suggested unit and its confidence

#### Scenario: Irrelevant fields are hidden by kind
- **WHEN** the reviewer opens a class proposal
- **THEN** no unit picker is shown; when they open a property proposal, no subClassOf/parent picker is shown

### Requirement: Suggested values are confirmable and distinct from asserted ones
A suggested placement/unit SHALL render as tentative (carrying its confidence) and visually distinct from a confirmed/asserted value. The reviewer SHALL be able to **confirm** a suggestion (promoting it to the asserted axiom, e.g. `msr:suggestedUnit` → `msr:canonicalUnit`) or **override** it; confirming SHALL persist via the existing `PUT /api/proposals/{id}/graph` whole-graph write.

#### Scenario: Confirming a suggested unit asserts it
- **WHEN** the reviewer confirms a suggested unit
- **THEN** the client persists the graph with the value moved from suggested to asserted via `PUT /api/proposals/{id}/graph`, and the field reads as confirmed

### Requirement: Approval is blocked while a proposal needs a decision
The approve control SHALL be **disabled** while the proposal's decision state is `needs-decision` or it carries unconfirmed suggestions, and SHALL name the specific unresolved item(s) (missing/low-confidence/off-allowlist placement or unit) so the reviewer knows what to resolve. Approve SHALL become enabled once every such item is confirmed or overridden.

#### Scenario: Approve is disabled for a needs-decision proposal
- **WHEN** the reviewer opens a proposal in `needs-decision` state
- **THEN** the approve control is disabled and the UI names what must be decided

#### Scenario: Approve enables after decisions are resolved
- **WHEN** the reviewer confirms/overrides every outstanding suggestion so the proposal is no longer `needs-decision`
- **THEN** the approve control becomes enabled

### Requirement: Detail shows an approval impact preview
The detail view SHALL show, before approval, an **impact preview** from `GET /api/proposals/{id}/preview`: how many proposed triples would route to each core graph (vocab/ontology/data) and the resulting ontology version. The preview SHALL be shown adjacent to the approve control so the reviewer sees the consequence of the action next to the action.

#### Scenario: Impact preview states the routing and version delta
- **WHEN** the reviewer opens a proposal
- **THEN** the detail view shows, near the approve control, the per-graph triple counts and the resulting ontology version that approval would produce

### Requirement: Promotion proposals show their witness instances
When a proposal is a promotion (it references witness instances), the detail view SHALL present a **witness panel** listing those instances and their grounding evidence, so the reviewer can see why the type earned class-hood rather than trusting a one-shot judgment.

#### Scenario: A promoted class shows its witnesses
- **WHEN** the reviewer opens a promotion proposal that references witness instances
- **THEN** the detail view lists the witness instances with their evidence

### Requirement: Queue is sorted by likelihood
The proposal queue SHALL be ordered so more-likely, ready-to-confirm proposals appear first, using the proposal's confidence/decision-state and evidence signals; `needs-decision`/low-confidence proposals SHALL sink lower. This ordering SHALL apply within the active status filter.

#### Scenario: Confident proposals rise to the top
- **WHEN** the queue contains a high-confidence `confirm` proposal and a low-confidence `needs-decision` proposal in the same status
- **THEN** the `confirm` proposal is ordered above the `needs-decision` one

## MODIFIED Requirements

### Requirement: Proposal detail rendered as an ontology-neighborhood diff
Selecting a proposal SHALL fetch `GET /api/proposals/{id}` and render its proposed triples
overlaid on the returned one-hop affected ontology neighborhood, highlighting the added nodes and
edges so the change reads as a visual diff. The diff SHALL include a **legend** and SHALL
visually distinguish three states: **existing** (already in the KG), **added-by-proposal** (the
miner's proposed triples), and **added-by-your-edit** (a triple the reviewer introduced this
session). The detail header SHALL state the proposal's **derived kind** (from the detail
payload, e.g. "adds 1 datatype property") so the reviewer knows whether they are approving a
class, a property, or a relation — not merely the display `kind` pill.

#### Scenario: solubility proposal shows the new property as added
- **WHEN** the reviewer opens the `solubility` proposal
- **THEN** the diff highlights the new `solubility` property node against its neighborhood, and the header states it adds a property

#### Scenario: A reviewer edit is distinguished from the proposed triples
- **WHEN** the reviewer adds a placement triple via the pickers
- **THEN** the diff shows that triple as added-by-your-edit, distinct from the miner's added-by-proposal triples, per the legend

#### Scenario: Unknown proposal id surfaces not-found
- **WHEN** the detail view requests a proposal id the API reports `404`
- **THEN** the UI shows a not-found state rather than an empty or broken diff

### Requirement: Approve and reject controls
The detail view SHALL provide **prominent approve and reject controls placed at the top of the
detail** (not buried below the evidence and edit fields) calling `POST /api/proposals/{id}/approve`
and `POST /api/proposals/{id}/reject`. The approve request SHALL carry a JSON body identifying the
decision (`{reviewer, timestamp}`), since the API rejects an empty approve body `400`; the reject
request needs no body. Approve SHALL be disabled while the proposal is `needs-decision` or carries
unconfirmed suggestions (see "Approval is blocked while a proposal needs a decision"). On approve
success the proposal SHALL be shown as approved; on reject it SHALL be shown as rejected.

#### Scenario: Approve promotes the proposal
- **WHEN** the reviewer approves an eligible proposal and the API returns success
- **THEN** the client sends `POST /api/proposals/{id}/approve` with a `{reviewer, timestamp}` body
  and the proposal is shown as approved and removed from the pending queue

#### Scenario: Reject marks the proposal
- **WHEN** the reviewer rejects a proposal
- **THEN** the proposal is shown as rejected

#### Scenario: Controls are prominent and at the top
- **WHEN** the reviewer opens a proposal detail
- **THEN** the approve and reject controls are presented prominently at the top of the detail, not only at the bottom

### Requirement: Editable placement and unit fields drive the edit endpoint
The detail view SHALL allow the reviewer to edit the proposal's placement/unit **via the typed
pickers** (see "Placement and unit use typed, kind-aware pickers") and persist the edit via
`PUT /api/proposals/{id}/graph`. The edit endpoint **replaces the whole proposal graph**, so the
client SHALL send the full edited graph serialized in the request body's `triples` field
(`{"triples": "<serialized triples>"}`), never a partial patch. A successful edit SHALL update the
rendered proposal.

#### Scenario: Reviewer sets a proposal's unit
- **WHEN** the reviewer picks the `solubility` proposal's unit from the unit picker and saves
- **THEN** the client sends `PUT /api/proposals/{id}/graph` with the full edited graph as the
  `triples` string and the detail view reflects the change

#### Scenario: Empty edit body is not sent
- **WHEN** the reviewer's edit would produce no triples
- **THEN** the client does not send an empty `triples` body (which the API rejects `400`), and the
  proposal graph is left unchanged
