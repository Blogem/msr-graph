"""Proposal-bundle emission, QUDT-allowlist guard, and staging writer.

Builds the two-graph `msr:ChangeProposal` bundle for a triaged candidate
(design.md D5-D7, specs `proposal-staging` + `change-proposal-schema`): a
``msr:ChangeProposal`` resource plus its ``msr:Evidence`` nodes, written to
the shared ``urn:msr:staging`` graph, and the proposed TBox/instance
triples, written to a dedicated ``urn:msr:proposal/{kind}-{term-slug}``
graph. IRIs are deterministic (``msrd:proposal-{kind}-{slug}`` via
``mining_types.term_slug``; evidence nodes mirror ``mentions.py``'s
``msrd:mention-{report}-{start}-{end}`` scheme) and no blank nodes are
used, so a re-run over the same corpus is a set-semantics no-op.

The QUDT-allowlist guard (design.md D6) is one of two hard checks: any
concrete ``unit:``/``qk:`` IRI a proposal would assert must be present in
the vendored ``ontology/qudt-units.json`` allowlist, else the whole
proposal is rejected (dropped, nothing written) by :func:`build_proposal_bundle`
returning ``None``. A placement that leaves its unit/quantity-kind unset
(the ``solubility`` demo case) never trips the guard.

The second hard check is the ``mining_types.safe_type_ref`` guard: every
``Placement.broader_class``/``.domain``/``.range_`` value is an unverified
LLM string spliced directly into CURIE/IRI *term* position (not literal
position, so ``_escape_literal`` cannot protect it) -- ``_class_block``/
``_relation_block`` run each such value through ``safe_type_ref`` and, if
it is present but unsafe (punctuation, a raw SPARQL-breakout payload, a
full IRI that would double-prefix into an invalid CURIE, ...), the whole
proposal is rejected the same way the QUDT guard rejects one, via
:func:`build_proposal_bundle` returning ``None``.

All builders in this module are pure string assembly (no I/O), so they are
unit-testable against a fake client; :func:`write_proposal` is the only
function that performs I/O, and it always writes additively via
``INSERT DATA`` -- never a graph-replace ``PUT`` -- mirroring
``mentions.py``'s writer style.

Deliberately stdlib-only at module level (``json``/``pathlib``/
``dataclasses``) plus the project's own zero-import-time-dependency
modules (``mining_types``, ``mine_provenance``, ``sparql``), so this
module has no third-party import-time dependency.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from msr_extraction.mining_types import (
    KIND_CLASS,
    KIND_PROPERTY,
    KIND_RELATION,
    Evidence,
    Placement,
    TriagedCandidate,
    local_name,
    safe_type_ref,
    term_slug,
)
from msr_extraction.sparql import SparqlClient

_PREFIXES = """\
PREFIX msr: <https://w3id.org/msr-kg/ontology#>
PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX voc: <https://w3id.org/msr-kg/vocab#>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>"""


def _escape_literal(s: str) -> str:
    """Escape a string for use inside a double-quoted Turtle/SPARQL literal.

    Mirrors ``mentions.py``'s ``_escape_literal`` exactly, so evidence
    sentences and terms containing quotes/backslashes/newlines never break
    the generated SPARQL update.
    """
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
    )


def _indent(block: str) -> str:
    """Indent every line of ``block`` by four spaces (mirrors ``mentions.py``)."""
    return "\n".join(f"    {line}" for line in block.splitlines())


def _evidence_iri(report: str, start: int, end: int) -> str:
    """Return the deterministic ``msrd:`` CURIE for one evidence node.

    ``msrd:evidence-{report}-{start}-{end}`` -- the same
    report/offset-keyed scheme as ``mentions.mention_iri``, so evidence
    nodes are deterministic and idempotent across re-runs.
    """
    return f"msrd:evidence-{report}-{start}-{end}"


@dataclass(frozen=True)
class QudtAllowlist:
    """The vendored QUDT unit/quantity-kind allowlist (``ontology/qudt-units.json``)."""

    units: frozenset[str]
    quantity_kinds: frozenset[str]


def load_qudt_allowlist(path: Path) -> QudtAllowlist:
    """Load and parse the vendored QUDT allowlist JSON at ``path``.

    Returns the ``allowedUnits``/``allowedQuantityKinds`` arrays (full
    IRIs) as frozensets. Reused, single source of truth also consulted by
    the SHACL unit shape (design.md D9) -- both derive from this same file
    so they cannot drift.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return QudtAllowlist(
        units=frozenset(data.get("allowedUnits", ())),
        quantity_kinds=frozenset(data.get("allowedQuantityKinds", ())),
    )


@dataclass(frozen=True)
class ProposalBundle:
    """A built proposal, ready to be written via :func:`write_proposal`."""

    #: ``msrd:proposal-{kind}-{slug}`` CURIE -- the ``msr:ChangeProposal`` resource.
    proposal_iri: str
    #: ``urn:msr:proposal/{kind}-{slug}`` -- this proposal's dedicated graph.
    proposal_graph: str
    #: Turtle triple block (``msr:ChangeProposal`` resource + ``msr:Evidence``
    #: nodes), destined for ``urn:msr:staging``.
    staging_triples: str
    #: Turtle triple block of the proposed TBox/instance axioms, destined
    #: for ``proposal_graph``. May be empty (e.g. a bare ``instance`` kind).
    proposal_graph_triples: str


def _proposal_iri(kind: str, slug: str) -> str:
    return f"msrd:proposal-{kind}-{slug}"


def _proposal_graph(kind: str, slug: str) -> str:
    return f"urn:msr:proposal/{kind}-{slug}"


def _evidence_block(evidence: Evidence) -> str:
    """Return the Turtle block for one ``msr:Evidence`` node."""
    iri = _evidence_iri(evidence.report, evidence.start_offset, evidence.end_offset)
    text = _escape_literal(evidence.sentence_text)
    return (
        f"{iri} a msr:Evidence ;\n"
        f'    msr:evidenceText "{text}"^^xsd:string ;\n'
        f"    msr:citedIn <{evidence.document_iri}> ;\n"
        f'    msr:startOffset "{evidence.start_offset}"^^xsd:integer ;\n'
        f'    msr:endOffset "{evidence.end_offset}"^^xsd:integer .'
    )


def _staging_resource_block(
    triaged: TriagedCandidate,
    proposal_iri: str,
    proposal_graph: str,
    evidence: list[Evidence],
) -> str:
    """Return the Turtle block for the ``msr:ChangeProposal`` resource plus its evidence.

    Deliberately omits ``prov:wasGeneratedBy`` -- a per-run generation edge
    would carry the run-specific :func:`mine_provenance.run_activity_iri`
    and so would change on every invocation, which would break the
    ``proposal-staging`` spec's "re-run leaves ``urn:msr:staging`` triple
    counts unchanged" idempotency guarantee. The per-run attribution edge
    the ``change-proposal-schema`` spec requires (``ChangeProposal``
    resource -> its mine run) is instead written by the CLI umbrella into
    the append-only ``urn:msr:provenance`` graph via
    ``mine_provenance.write_generation_edges``, mirroring how
    ``mentions.py``/``documents.py`` keep ``urn:msr:data`` idempotent while
    still recording per-run lineage.
    """
    predicates = [
        "a msr:ChangeProposal",
        f'msr:kind "{_escape_literal(triaged.kind)}"^^xsd:string',
        'msr:reviewStatus "pending"^^xsd:string',
        f'msr:term "{_escape_literal(triaged.candidate.term)}"^^xsd:string',
        f'msr:docFrequency "{triaged.candidate.doc_frequency}"^^xsd:integer',
        f'msr:hasProposalGraph "{proposal_graph}"^^xsd:anyURI',
    ]
    if evidence:
        evidence_iris = ", ".join(
            _evidence_iri(e.report, e.start_offset, e.end_offset) for e in evidence
        )
        predicates.append(f"msr:hasEvidence {evidence_iris}")
    joined = " ;\n    ".join(predicates)
    resource_block = f"{proposal_iri} {joined} ."
    blocks = [resource_block, *(_evidence_block(e) for e in evidence)]
    return "\n\n".join(blocks)


def _property_block(term: str, slug: str, placement: Placement) -> str:
    """Return the ``msr:PhysicalProperty`` + ``voc:`` SKOS concept blocks.

    Asserts ``msr:canonicalUnit``/``msr:quantityKind`` only when the
    placement carries that concrete value (the allowlist guard already
    ran in :func:`build_proposal_bundle`, so any value reaching here has
    passed it); an unset value (the ``solubility`` demo case) is left as
    a reviewer decision, per design.md D6. No ``skos:closeMatch`` --
    grounding is via ``rdfs:label`` only.
    """
    label = _escape_literal(term)
    predicates = ["a msr:PhysicalProperty", f'rdfs:label "{label}"^^xsd:string']
    if placement.canonical_unit:
        predicates.append(f"msr:canonicalUnit <{placement.canonical_unit}>")
    if placement.quantity_kind:
        predicates.append(f"msr:quantityKind <{placement.quantity_kind}>")
    joined = " ;\n    ".join(predicates)
    property_block = f"msr:{slug} {joined} ."
    concept_block = (
        f"voc:{slug} a skos:Concept ;\n"
        f'    skos:prefLabel "{label}"^^xsd:string .'
    )
    return f"{property_block}\n\n{concept_block}"


def _reject_external_iri(term: str | None) -> bool:
    """Return whether a :func:`~msr_extraction.mining_types.safe_type_ref` result
    must be rejected as out of scope for a *proposed* schema placement.

    ``safe_type_ref`` is a general-purpose safety primitive (also reused by
    ``mine_runner.py`` for the ``instance``-kind rides-with/auto-accept
    path, where a full IRI already present in the live known-entity set is
    a legitimate type reference). A ``class``/``relation``-kind proposal is
    different: it mints a *new* schema term (or references an existing one)
    that design.md D6/D7 always names within this project's own
    ``msr:``/``msrd:``/``voc:`` namespace -- never an arbitrary external
    IRI. So here, even a syntactically clean bracketed full IRI
    (``safe_type_ref``'s ``"<...>"`` output) is rejected: it is not unsafe
    to write, but it is out of scope for what a proposal is allowed to
    assert, and treating it the same as any other unsafe value (reject the
    whole proposal) is the simplest, fail-closed rule.
    """
    return term is not None and term.startswith("<")


def _companion_relation_name(broader_class_local: str) -> str:
    """Derive a companion ``...edBy`` object-property local name from a class's local name.

    POC naming convention (design.md D7's ``graphite``/``Moderator``
    example): an agent-noun class ending in ``-or``/``-er`` (e.g.
    ``Moderator``) names entities that verb something; the companion
    relation connecting an instance to that class is named by stripping
    the agent suffix and appending ``edBy`` (``Moderator`` ->
    ``moderatedBy``). This is deliberately narrow -- it is not a general
    English morphology solver, only the single demo naming pair this
    change is scoped to. ``broader_class_local`` must already be a
    sanitized local name (``mining_types.local_name`` of a
    :func:`~msr_extraction.mining_types.safe_type_ref` result), never the
    raw LLM string, so this derivation can never itself become an
    injection vector.
    """
    if not broader_class_local:
        return broader_class_local
    lowered = broader_class_local[0].lower() + broader_class_local[1:]
    stem = lowered[:-2] if lowered.endswith(("or", "er")) else lowered
    return f"{stem}edBy"


def _class_block(placement: Placement) -> str | None:
    """Return the broader-class + companion object-property blocks.

    Emits ``{class_term} a owl:Class`` plus a companion
    ``owl:ObjectProperty`` (:func:`_companion_relation_name`) with
    ``rdfs:range`` the same class -- domain is deliberately left open (no
    ``rdfs:domain``), per design.md D7, since the concrete
    reactor/domain-typed instance edge is chunk-7 relation-extraction
    work, not hand-asserted here. Returns ``""`` if the placement carries
    no ``broader_class`` claim, or ``None`` if it carries one that
    ``mining_types.safe_type_ref`` rejects as SPARQL-unsafe, or that
    resolves to an external full IRI (:func:`_reject_external_iri`) -- a
    proposed class must be a term in this project's own ``msr:``/``msrd:``/
    ``voc:`` namespace. Either way the caller, :func:`build_proposal_bundle`,
    must then reject the whole proposal -- this LLM-asserted value is
    spliced directly into CURIE/IRI term position, not literal position, so
    ``_escape_literal`` cannot protect it here.
    """
    broader = placement.broader_class
    if not broader:
        return ""
    class_term = safe_type_ref(broader)
    if class_term is None or _reject_external_iri(class_term):
        return None
    label = local_name(class_term)
    class_block = (
        f"{class_term} a owl:Class ;\n"
        f'    rdfs:label "{_escape_literal(label)}"^^xsd:string .'
    )
    relation_name = _companion_relation_name(label)
    relation_block = f"msr:{relation_name} a owl:ObjectProperty ;\n    rdfs:range {class_term} ."
    return f"{class_block}\n\n{relation_block}"


def _relation_block(slug: str, placement: Placement) -> str | None:
    """Return the ``owl:ObjectProperty`` block for a ``relation``-kind candidate.

    ``rdfs:domain``/``rdfs:range`` are asserted only when the placement
    carries that claim, and only after passing ``mining_types.safe_type_ref``
    plus the same external-IRI rejection (see :func:`_class_block`'s
    docstring for why both guards are needed here, in term rather than
    literal position). Returns ``None`` if a present ``domain``/``range_``
    value is SPARQL-unsafe or an external full IRI -- the caller must then
    reject the whole proposal.
    """
    predicates = ["a owl:ObjectProperty"]
    if placement.domain:
        domain_term = safe_type_ref(placement.domain)
        if domain_term is None or _reject_external_iri(domain_term):
            return None
        predicates.append(f"rdfs:domain {domain_term}")
    if placement.range_:
        range_term = safe_type_ref(placement.range_)
        if range_term is None or _reject_external_iri(range_term):
            return None
        predicates.append(f"rdfs:range {range_term}")
    joined = " ;\n    ".join(predicates)
    return f"msr:{slug} {joined} ."


def _proposal_graph_triples(triaged: TriagedCandidate, slug: str) -> str | None:
    """Dispatch to the per-``kind`` proposal-graph triple builder.

    ``property``/``class``/``relation`` build proposed TBox (+, for
    ``class``, a rides-along companion relation) axioms; any other kind
    (notably a bare ``instance``, normally handled directly by
    ``auto_accept.py`` rather than routed through this builder) yields no
    TBox axioms -- the staging resource is the whole bundle. Returns
    ``None`` if the ``class``/``relation`` builder rejected an unsafe
    placement value (see :func:`_class_block`/:func:`_relation_block`) --
    the caller, :func:`build_proposal_bundle`, must then reject the whole
    proposal.
    """
    kind = triaged.kind
    placement = triaged.placement
    if kind == KIND_PROPERTY:
        return _property_block(triaged.candidate.term, slug, placement)
    if kind == KIND_CLASS:
        return _class_block(placement)
    if kind == KIND_RELATION:
        return _relation_block(slug, placement)
    return ""


def build_proposal_bundle(
    triaged: TriagedCandidate, allowlist: QudtAllowlist, run_ts: str
) -> ProposalBundle | None:
    """Build the deterministic proposal bundle for one triaged candidate.

    Runs the QUDT-allowlist guard first (design.md D6): if
    ``triaged.placement.canonical_unit`` or ``.quantity_kind`` is a
    non-empty concrete IRI absent from ``allowlist``, the whole proposal
    is rejected -- returns ``None``, nothing built. An unset value never
    trips the guard.

    Then runs the ``mining_types.safe_type_ref`` guard: builds the
    per-kind proposal-graph TBox block (:func:`_proposal_graph_triples`)
    and, if that returns ``None`` -- a present ``broader_class``/``domain``/
    ``range_`` value that ``safe_type_ref`` rejected as SPARQL-unsafe --
    the whole proposal is rejected the same way, before anything else is
    built. On success, mints the deterministic
    ``msrd:proposal-{kind}-{slug}`` resource IRI and
    ``urn:msr:proposal/{kind}-{slug}`` graph name
    (``slug = mining_types.term_slug(triaged.candidate.term)``), then
    assembles the ``urn:msr:staging`` resource+evidence block. No blank
    nodes anywhere.

    ``run_ts`` is accepted but **reserved/unused** by the staging block
    (kept in the signature for call-site/API stability and in case a
    future bundle component needs it): the per-run
    ``prov:wasGeneratedBy`` attribution for this proposal's
    ``msr:ChangeProposal`` resource is written separately, by the CLI
    umbrella, into ``urn:msr:provenance`` (append-only) via
    ``mine_provenance.write_generation_edges`` -- not embedded in this
    (idempotent, re-run-stable) bundle.
    """
    placement = triaged.placement
    if placement.canonical_unit and placement.canonical_unit not in allowlist.units:
        return None
    if placement.quantity_kind and placement.quantity_kind not in allowlist.quantity_kinds:
        return None

    kind = triaged.kind
    slug = term_slug(triaged.candidate.term)

    proposal_graph_triples = _proposal_graph_triples(triaged, slug)
    if proposal_graph_triples is None:
        return None

    proposal_iri = _proposal_iri(kind, slug)
    proposal_graph = _proposal_graph(kind, slug)

    evidence = sorted(
        triaged.candidate.evidence,
        key=lambda e: (e.report, e.start_offset, e.end_offset),
    )
    staging_triples = _staging_resource_block(
        triaged, proposal_iri, proposal_graph, evidence
    )

    return ProposalBundle(
        proposal_iri=proposal_iri,
        proposal_graph=proposal_graph,
        staging_triples=staging_triples,
        proposal_graph_triples=proposal_graph_triples,
    )


def write_proposal(
    bundle: ProposalBundle, client: SparqlClient, *, extra_proposal_triples: str = ""
) -> None:
    """Send ``bundle`` to the graph via two additive ``INSERT DATA`` updates.

    (1) always writes ``bundle.staging_triples`` into
    ``GRAPH <urn:msr:staging>``. (2) writes ``bundle.proposal_graph_triples``
    plus ``extra_proposal_triples`` (e.g. a rides-along individual built by
    ``auto_accept.py``, per design.md D7/D8) into
    ``GRAPH <bundle.proposal_graph>`` -- skipped entirely if both are
    empty. Never a graph-replace ``PUT``; deterministic IRIs and no blank
    nodes make both updates idempotent across re-runs.
    """
    staging_update = (
        f"{_PREFIXES}\n"
        "INSERT DATA {\n"
        "  GRAPH <urn:msr:staging> {\n"
        f"{_indent(bundle.staging_triples)}\n"
        "  }\n"
        "}"
    )
    client.update(staging_update)

    parts = [p for p in (bundle.proposal_graph_triples, extra_proposal_triples) if p]
    if not parts:
        return
    body = "\n\n".join(parts)
    proposal_update = (
        f"{_PREFIXES}\n"
        "INSERT DATA {\n"
        f"  GRAPH <{bundle.proposal_graph}> {{\n"
        f"{_indent(body)}\n"
        "  }\n"
        "}"
    )
    client.update(proposal_update)
