"""Instance auto-accept: direct-to-data write and the rides-with renderer.

Implements the "Instances under an existing class are auto-accepted to core
data" and "Instances depending on proposed schema ride the proposal bundle"
requirements (mine-ontology-candidates design.md D8, spec
``instance-auto-accept``). An ``instance``-kind candidate whose type resolves
entirely within the current core schema is written directly to
``urn:msr:data`` as an :class:`Individual`, flagged ``msr:autoAccepted true``
and provenance-complete: it carries **both** ``prov:wasGeneratedBy
msrd:activity-mine`` and ``prov:wasDerivedFrom`` its source ``msr:Document``,
satisfying the landed SHACL ``CatalogIndividualProvenanceShape`` (which
targets ``msr:MoltenSalt``/``msr:Constituent``/``msr:ChemicalCompound`` and
requires min-count-1 of both PROV edges) so the write is not atomically
rejected.

An individual that can only be typed by *proposed* schema (a pending class,
e.g. ``msr:Moderator``) must not auto-accept — it rides its proposal's
``urn:msr:proposal/{id}`` graph instead, reaching ``urn:msr:data`` only on
chunk-9 approval. :func:`resolves_in_core` is the decision function the CLI
uses to route between the two paths; :func:`individual_triples` is the exact
same graph-agnostic renderer for both (the rides-with case hands its output
to ``proposals.write_proposal(..., extra_proposal_triples=...)`` rather than
wrapping it in this module's ``INSERT DATA``).

Deliberately stdlib-only plus intra-package imports at module level (no
third-party imports) so this module has zero import-time third-party
dependencies, mirroring ``mine_provenance.py``/``mining_types.py`` (``sparql.py``
itself defers its one third-party import, ``httpx``, inside
``SparqlClient.update``).
"""

from __future__ import annotations

from dataclasses import dataclass

from msr_extraction import mine_provenance
from msr_extraction.mining_types import TriagedCandidate
from msr_extraction.sparql import SparqlClient

#: Core catalog classes (CURIEs) an ``instance``-kind candidate's asserted
#: type may resolve against without depending on any pending proposal
#: (spec "Instances under an existing class are auto-accepted to core
#: data"). Kept small and explicit rather than derived from a live schema
#: query, matching the reviewer-verifiable, never-dereferenced posture of
#: D6's placement claims.
CORE_TYPES: frozenset[str] = frozenset(
    {
        "msr:MoltenSalt",
        "msr:ChemicalCompound",
        "msr:Constituent",
        "msr:Substance",
    }
)

_PREFIXES = """\
PREFIX msr: <https://w3id.org/msr-kg/ontology#>
PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>"""


@dataclass(frozen=True)
class Individual:
    """An instance-kind candidate's individual, ready to be rendered.

    Graph-agnostic: whether it lands in ``urn:msr:data`` (auto-accept) or a
    proposal graph (rides-with) is decided by the caller via
    :func:`resolves_in_core`, not carried on this dataclass.
    """

    #: Deterministic ``msrd:{slug}`` CURIE (or bracketed full IRI) subject.
    iri: str
    #: The individual's asserted type, e.g. ``"msr:MoltenSalt"`` (core) or
    #: ``"msr:Moderator"`` (proposed) — a CURIE, or a full IRI.
    type_iri: str
    #: Full IRI of the source ``msr:Document`` (written bracketed).
    document_iri: str


def _term(value: str) -> str:
    """Return ``value`` as a SPARQL/Turtle term: bracketed if a full IRI.

    A CURIE (``msr:MoltenSalt``, ``msrd:foo``) is already a valid term and
    is returned unchanged; a bare full IRI (``https://...``) is wrapped in
    ``<...>`` so it dereferences as an IRIref rather than an undefined
    prefixed name.
    """
    if value.startswith("<") or "://" in value:
        return value if value.startswith("<") else f"<{value}>"
    return value


def individual_triples(ind: Individual) -> str:
    """Return the Turtle triple block for one auto-accepted/rides-with individual.

    Produces (with the type term and document IRI escaped/bracketed as
    needed)::

        {ind.iri} a {ind.type_iri} ;
            msr:autoAccepted true ;
            prov:wasGeneratedBy msrd:activity-mine ;
            prov:wasDerivedFrom <{ind.document_iri}> .

    No ``msr:citedIn`` is asserted (deferred to chunk-7 citation
    extraction; the derivation root is ``prov:wasDerivedFrom``).
    ``msr:autoAccepted true`` is a bare Turtle boolean literal (already
    ``xsd:boolean``-typed by the grammar). The subject IRI is deterministic
    and there are no blank nodes, so re-emitting this block is a
    set-semantics no-op. This renderer is graph-agnostic — no ``INSERT``/
    ``GRAPH`` wrapper — so the same output can be sent to ``urn:msr:data``
    via :func:`data_insert_data` or spliced into a proposal graph as
    ``proposals.write_proposal(..., extra_proposal_triples=...)``.
    """
    subject = _term(ind.iri)
    type_term = _term(ind.type_iri)
    return (
        f"{subject} a {type_term} ;\n"
        "    msr:autoAccepted true ;\n"
        f"    prov:wasGeneratedBy {mine_provenance.ACTIVITY_IRI} ;\n"
        f"    prov:wasDerivedFrom <{ind.document_iri}> ."
    )


def resolves_in_core(
    triaged: TriagedCandidate,
    known_iris: set[str],
    *,
    core_types: set[str] | None = None,
) -> bool:
    """Return whether ``triaged``'s asserted type resolves entirely within core schema.

    The instance's asserted type is ``triaged.placement.broader_class`` (the
    "typed by X" claim D3's placement records for the candidate). This is
    True — and thus auto-accept, per the "Instances under an existing class
    are auto-accepted to core data" requirement — iff that type is either:

    - a member of ``core_types`` (defaults to :data:`CORE_TYPES`, the small
      set of core catalog classes, as CURIEs), or
    - a full IRI already present in ``known_iris``.

    False — and thus rides-with-proposal, per "Instances depending on
    proposed schema ride the proposal bundle" — when the type is unset or
    is a pending proposed class (e.g. ``msr:Moderator``) present in neither
    set. This is the single decision point the CLI uses to route an
    instance candidate's individual to :func:`write_auto_accepted` (True)
    or into a proposal graph via ``proposals.write_proposal`` (False).
    """
    if core_types is None:
        core_types = CORE_TYPES
    type_ref = triaged.placement.broader_class
    if not type_ref:
        return False
    if type_ref in core_types:
        return True
    return type_ref in known_iris


def data_insert_data(individuals: list[Individual]) -> str:
    """Return the INSERT DATA update writing all auto-accepted individuals.

    Orders ``individuals`` by ``iri`` for determinism, concatenates their
    :func:`individual_triples` blocks, and wraps them in
    ``INSERT DATA { GRAPH <urn:msr:data> { ... } }`` with the ``msr:``,
    ``msrd:``, ``prov:``, ``xsd:`` prefix declarations (mirroring
    ``mentions.py``'s ``insert_data``).
    """
    ordered = sorted(individuals, key=lambda ind: ind.iri)
    body = "\n\n".join(individual_triples(ind) for ind in ordered)
    indented = "\n".join(f"    {line}" for line in body.splitlines())
    return (
        f"{_PREFIXES}\n"
        "INSERT DATA {\n"
        "  GRAPH <urn:msr:data> {\n"
        f"{indented}\n"
        "  }\n"
        "}"
    )


def write_auto_accepted(
    individuals: list[Individual], client: SparqlClient, run_ts: str
) -> None:
    """Write auto-accepted individuals to ``urn:msr:data`` plus their lineage.

    No-op (no writes at all) when ``individuals`` is empty. Otherwise sends
    :func:`data_insert_data` via ``client.update`` — the idempotent,
    deterministic-IRI ``urn:msr:data`` block — then writes one per-run
    ``prov:wasGeneratedBy <urn:msr:run:mine/{run_ts}>`` generation edge per
    individual into ``urn:msr:provenance`` via
    :func:`mine_provenance.write_generation_edges`. The stable
    ``msrd:activity-mine`` and per-run activity *nodes* are written once by
    the CLI umbrella (:func:`mine_provenance.write_stable_activity`/
    :func:`mine_provenance.write_activity`), not here — this function only
    writes the individuals and their generation edges.
    """
    if not individuals:
        return
    client.update(data_insert_data(individuals))
    mine_provenance.write_generation_edges(
        [ind.iri for ind in individuals], run_ts, client
    )
