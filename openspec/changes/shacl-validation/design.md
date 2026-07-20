## Context

The `msr` GraphDB repository (11.4.2, inference disabled per D2) accepts any well-formed RDF; the ontology's `rdfs:domain`/`rdfs:range` declarations and the provenance model are documentation, not enforcement. This change adds the write-time validation layer described in `docs/PROVENANCE_AND_TRUST_DESIGN.md` §2. It is chunk 13 of Phase P3.5 and is sequenced **after** chunk 12 `provenance-model` (**now landed and archived**), which added the PROV-O vocabulary and made every writer emit `prov:wasDerivedFrom` + `prov:wasGeneratedBy` — so the predicates these shapes require are already asserted on real writes.

Current state:

- Repo provisioning: `scripts/ensure-repo.sh` POSTs `deploy/graphdb/msr-repo-config.ttl` to `POST /rest/repositories` (check-then-create, idempotent). The config sets `graphdb:ruleset "empty"` and has no SHACL parameters.
- Write path: `internal/graph.Client.Update` (SPARQL 1.1 UPDATE, writers name explicit `GRAPH` targets) and `Client.PutGraph` (Graph Store Protocol PUT, graph-replace for seed/data). Both surface non-2xx responses as generic errors.
- Allowlist source of truth: `ontology/qudt-units.json` (consumed by the Go loader and the Python extraction).
- Existing integration tests in `internal/graph` (`*_integration_test.go`) are opt-in and gated on a running GraphDB.

## Goals / Non-Goals

**Goals:**

- Enable GraphDB native SHACL on `msr` at repository-creation time, idempotently, preserving inference-off (D2).
- Author a shape catalogue enforcing the provenance invariants (§1) and data-quality invariants from the design doc.
- Install shapes into the reserved shapes graph as part of bootstrap; make re-loading idempotent.
- Make commit rejections legible: callers can tell a validation failure from other write errors and see the failing shape + focus node.
- Decide and document a bulk-load validation strategy, measured against 11.4.2.

**Non-Goals:**

- Defining the PROV-O vocabulary or retrofitting writers to emit provenance — that is chunk 12 `provenance-model` (landed).
- A human-in-the-loop review/promotion workflow — SHACL is the enforcement gate; the review UI is chunk 9 (demonstration).
- Any new domain/safety schema (chunk 11, IAEA).
- RDF-star / statement-level annotation — explicitly rejected at POC scale in the design doc.
- Data migration — POC data is disposable and replaced wholesale; the repository is recreated, not migrated.

## Decisions

### D1: Enable SHACL via the vendored repo-config TTL, not a runtime toggle

GraphDB's SHACL is a **repository capability fixed at creation time** (confirmed against the GraphDB SHACL docs: *"SHACL support in a given repository must be enabled when that repository is created … you cannot modify an already existing repository by enabling the validation afterwards"*). Enabling it belongs in `deploy/graphdb/msr-repo-config.ttl` so `ensure-repo.sh` creates a SHACL-enabled repo in one POST, keeping provisioning declarative and idempotent. Alternative — enabling SHACL through a REST call after creation — was rejected: GraphDB pins validation config at creation, so it is not even possible.

**Verified config surface (GraphDB 11.x, confirm the exact sail-type string on 11.4.2).** GraphDB's SHACL is a **wrapping sail**: the repository's `sr:sailImpl` becomes `sail:sailType "graphdb:ShaclSail"` and the *current* GraphDB sail config (with `graphdb:ruleset "empty"` — D2 preserved) moves verbatim under `sail:delegate [ … ]`. SHACL parameters use the prefix `sail-shacl: <http://rdf4j.org/config/sail/shacl#>`. Target shape:

```turtle
@prefix sail-shacl: <http://rdf4j.org/config/sail/shacl#>.
@prefix xsd: <http://www.w3.org/2001/XMLSchema#>.

    sr:sailImpl [
        rep:repositoryType "graphdb:SailRepository" ;
        sail:sailType "graphdb:ShaclSail" ;
        sail-shacl:validationEnabled true ;
        sail-shacl:shapesGraph <http://rdf4j.org/schema/rdf4j#SHACLShapeGraph> ;
        sail-shacl:parallelValidation true ;
        sail-shacl:serializableValidation true ;
        sail-shacl:logValidationViolations true ;   # feeds D5's legible report
        sail-shacl:undefinedTargetValidatesAllSubjects false ;
        sail-shacl:rdfsSubClassReasoning false ;     # inference off (D2); targets are concrete classes
        sail-shacl:transactionalValidationLimit "500000"^^xsd:long ;  # our batches ≪ this ⇒ transactional (D6)
        sail:delegate [
            sail:sailType "graphdb:Sail" ;
            graphdb:ruleset "empty" ;
            # … the existing graphdb: parameters, unchanged …
        ]
    ]
```

Consequence: a repo created by the _old_ (non-wrapped) config is not SHACL-enabled and must be recreated. Acceptable because POC data is disposable (the seed/NIST/extraction writes are replayable). `ensure-repo.sh`'s check-then-create means an existing pre-SHACL repo would be left untouched — so bring-up on an old volume must drop the `graphdb-data` volume first (migration plan), and `ensure-repo.sh` actively detects and warns on a non-SHACL existing repo (D7).

### D2: Shapes live in the RDF4J reserved shapes graph, loaded as a graph update

RDF4J/GraphDB read SHACL shapes from the reserved graph `http://rdf4j.org/schema/rdf4j#SHACLShapeGraph` (confirmed as the default in the GraphDB SHACL docs; also referenced by `sail-shacl:shapesGraph` in D1). Shapes are authored as a committed Turtle artifact (proposed: `deploy/graphdb/msr-shapes.ttl`) and loaded by importing that RDF into the reserved graph — a new idempotent step in `ensure-repo.sh` (run after the repo exists and is healthy). Loading is a Graph Store Protocol **PUT** to the graph-store endpoint targeting the shapes graph (replace semantics ⇒ idempotent re-load); a `DROP GRAPH`+`INSERT` SPARQL update is the fallback if PUT to the reserved graph misbehaves on 11.4.2. Re-loading replaces the graph contents — no repository recreation. This keeps shape evolution a reviewable diff. (Note: this bootstrap load is `curl` in `ensure-repo.sh`, so it is not subject to the Go `Client.PutGraph` known-graph guard.)

### D3: Generate the unit-allowlist `sh:in` list from `ontology/qudt-units.json`

The unit data-quality shape must agree with the loader's allowlist. Rather than hand-copy IRIs into the Turtle (drift risk), a small generation step reads `qudt-units.json` and emits the `sh:in (...)` node into the shapes artifact (or a companion fragment loaded alongside it). Alternative — hand-authored list — rejected: two sources of truth for the same allowlist is exactly the class of bug SHACL is here to prevent.

### D4: `linksTo` target-kind uses a SPARQL-based constraint (confirmed supported)

"References an existing target of the expected kind" needs existence + type checks that go beyond SHACL Core cardinality/`sh:in`. **Confirmed: GraphDB supports SHACL-SPARQL** — both `sh:SPARQLConstraint` (SPARQL-based constraint components) and `sh:SPARQLTarget` (SPARQL-based targets). So the target-kind/dangling-reference invariant is expressed with a `sh:sparql` constraint whose `SELECT` returns the focus node when the target is missing or the wrong kind. No alternative solution is needed.

Two engine facts shape the implementation:

- **Inference is off (D2)**, so a Core `sh:class` on the object matches only the *explicitly asserted* `rdf:type` — which is exactly what we want (we validate what was written, not what a reasoner would infer). Where a plain explicit-type check suffices, prefer Core `sh:class`/`sh:nodeKind` over `sh:sparql`.
- **Path/feature limits** (from the GraphDB SHACL docs): `sh:path` is limited to predicate, sequence, alternative, and inverse paths (no zero-or-more/one-or-more/zero-or-one); unsupported: pairwise comparisons, wildcard paths, `sh:xone`, qualified shapes, `sh:closed`. None of our shapes need these — the `validTempMin ≤ validTempMax` comparison is done inside the `sh:sparql` `SELECT` (a filter), not via an unsupported pairwise-comparison component.

### D5: Surface validation rejections as a typed error at the write boundary

`Client.Update`/`PutGraph` currently wrap any non-2xx as a generic error. A SHACL rejection returns a validation report (RDF4J emits an HTTP error carrying a `sh:ValidationReport`). Add detection at the write boundary that recognizes the validation-report response and returns a distinguishable error (e.g. a `ValidationError` type carrying the failing constraint(s) and focus node(s)), so `cmd/loader` and the extraction writers can log/report it legibly instead of a bare HTTP status. Keep the writer _interfaces_ stable — this is additive error typing.

### D6: Bulk-load uses per-transaction (incremental) validation

**Decided: validate per transaction (incremental).** At POC scale the batches are tiny — the curated corpus is ~12 documents and the NIST ingest is a handful of salts/measurements — far below GraphDB's `transactionalValidationLimit` (default `500000`, above which the engine switches to whole-repository validation). So every real write stays in the cheap transactional-validation path, and per-transaction rejection gives the cleanest "which record failed" signal, which D5's legible error depends on. No measurement spike is needed to choose the strategy; a sanity check that a full seed+NIST load stays comfortably under the limit is enough. Load-then-validate is the documented fallback only if a future, much larger ingest crosses the limit. The spec requires that invalid data never silently persists — satisfied because each transaction is atomic and rejected as a whole.

### D7: `ensure-repo.sh` detects and warns on a non-SHACL existing repo

Because provisioning is check-then-create, an existing pre-SHACL `msr` repo on an old `graphdb-data` volume would be silently left untouched — validation would appear "on" but never fire. So `ensure-repo.sh`, on finding the repo already present, additionally inspects its config (`GET /rest/repositories/msr` or the repository config download) for the `graphdb:ShaclSail` sail type / `sail-shacl:validationEnabled`; if absent it fails (or loudly warns) with guidance to drop the volume and recreate. This closes the "silent no-op on old volume" trap rather than leaving it to documentation.

## Risks / Trade-offs

- **[Exact 11.4.2 sail-type string]** → The config surface is now determined (D1): `graphdb:ShaclSail` wrapper + `sail:delegate`, `sail-shacl:` params, reserved shapes graph. The one residual is confirming the sail-type literal is `graphdb:ShaclSail` (GraphDB-native, matches UI-generated config) vs. `rdf4j:ShaclSail` on 11.4.2 exactly. Mitigation: the config-apply task verifies by round-tripping the config through GraphDB's own "create then download config" and diffing — no guessing.
- **[Chunk 12 landed — provenance present]** → Chunk 12 `provenance-model` is landed and archived, so every measurement/mention already carries `prov:wasDerivedFrom` + `prov:wasGeneratedBy`; the provenance-requiring shapes reject-if-absent without blocking valid writes. `msr:citedIn` is the one predicate no writer asserts (deferred to chunk 7), so the shapes deliberately do **not** require it — requiring it would reject every real measurement. Integration fixtures asserting acceptance of valid data must include the PROV edges the writers now emit.
- **[Recreating the repo drops existing data]** → A developer bringing up on an old `graphdb-data` volume would get a silently pre-SHACL repo (check-then-create no-ops). Mitigation: D7 makes `ensure-repo.sh` detect and warn/fail on a non-SHACL existing repo, plus the documented volume-drop step. Acceptable data loss — POC data is disposable/replayable.
- **[SHACL feature limits]** → GraphDB's engine omits some SHACL features (zero-or-more paths, `sh:xone`, qualified shapes, `sh:closed`, pairwise comparisons — see D4). Mitigation: none of our shapes need them; the one comparison (`validTempMin ≤ validTempMax`) is a filter inside a `sh:sparql` `SELECT`, which is supported. If a future shape needs an omitted feature, express it via `sh:sparql` or document the gap.
- **[Test flakiness / GraphDB dependency]** → Validation behavior can only be truly exercised against a real GraphDB. Mitigation: opt-in integration tests consistent with the existing `internal/graph` pattern; do not attempt to unit-test the engine.

## Migration Plan

1. Chunk 12 `provenance-model` is already landed (writers emit the required provenance) — no action needed; proceed directly.
2. Update `deploy/graphdb/msr-repo-config.ttl` to enable SHACL (verified 11.4.2 surface).
3. Add the shapes artifact and the idempotent shapes-load step to `ensure-repo.sh`.
4. On existing developer machines: `docker compose down -v` (or drop the `graphdb-data` volume) so `make up` recreates a SHACL-enabled `msr`, then replay seed/NIST loads. No production data exists.
5. Rollback: revert the config + shapes changes and recreate the repository from the prior config; data is replayable.

## Resolved Questions

Resolved from the GraphDB SHACL documentation (11.x line) rather than deferred to a spike:

- **Config surface / shapes-graph IRI** → Determined (D1, D2): `graphdb:ShaclSail` wrapper with the current sail under `sail:delegate`; `sail-shacl: <http://rdf4j.org/config/sail/shacl#>` params (`validationEnabled`, `shapesGraph`, `parallelValidation`, `serializableValidation`, `logValidationViolations`, `transactionalValidationLimit`, …); shapes loaded into `http://rdf4j.org/schema/rdf4j#SHACLShapeGraph`. SHACL must be set at repo creation — cannot be added later. Only residual: confirm the sail-type literal (`graphdb:ShaclSail` vs `rdf4j:ShaclSail`) on 11.4.2 via config round-trip (Risks).
- **`sh:sparql` support** → Yes (D4): GraphDB supports `sh:SPARQLConstraint` + `sh:SPARQLTarget`; the `linksTo` target-kind and `validTempMin ≤ validTempMax` checks use it. Path/feature limits noted in D4; none of our shapes hit them. No alternative solution required.
- **Bulk-load strategy** → Per-transaction (incremental) validation (D6): POC batches are far below `transactionalValidationLimit` (500000). Load-then-validate kept only as a documented fallback for a future large ingest.
- **Detect non-SHACL existing repo** → Yes (D7): `ensure-repo.sh` inspects an already-present repo's config and warns/fails if SHACL is not enabled, closing the silent-no-op-on-old-volume trap.
