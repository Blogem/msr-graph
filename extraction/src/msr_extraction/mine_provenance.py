"""Shared mine-pipeline provenance helpers.

Provenance vocabulary and per-run Activity writer for the ontology-mining
pipeline (mine-ontology-candidates design.md, "The mine run records
provenance activities and per-run lineage"). This module mirrors
``provenance.py`` (the extraction pipeline's equivalent) exactly, with
only the pipeline identity changed: :data:`ACTIVITY_IRI`,
:data:`MINE_VERSION`, :data:`AGENT_IRI`, and the ``mine`` run-namespace
segment used by :func:`run_activity_iri`.

Every fact the miner asserts (auto-accepted individuals, proposal-bundle
triples) references the deterministic :data:`ACTIVITY_IRI` via
``prov:wasGeneratedBy`` in whichever graph it lands in, so that edge
stays a set-semantics no-op across re-runs. Each CLI invocation
additionally mints a **per-run** ``prov:Activity`` *node* — the run
identifier ``urn:msr:run:mine/<ts>`` used as an IRI, not a graph name —
and writes it, fully attributed (agent, start/end time, version), into
the single shared audit graph ``urn:msr:provenance``. The same
invocation also writes one ``<fact> prov:wasGeneratedBy
<urn:msr:run:mine/<ts>>`` generation edge per fact the run asserts into
``urn:msr:provenance`` via :func:`generation_edges_insert_data` — the
generalization of the per-writer pattern in ``mentions.py``, since the
miner's facts span multiple writers (auto-accept, proposals) that all
need the same per-run lineage edge. Because the per-run node and its
edges are timestamped, they are intentionally outside the
``urn:msr:data`` idempotency guarantee — a repeat wall-clock run appends
a new per-run activity and generation edges to ``urn:msr:provenance``
rather than mutating existing data.

Each invocation also types the stable :data:`ACTIVITY_IRI` itself, once,
in ``urn:msr:data`` -- ``a prov:Activity ; prov:wasAssociatedWith
<agent...> ; owl:versionInfo "<version>"`` with no timestamps -- via
:func:`stable_activity_insert_data`/:func:`write_stable_activity`, so that
typing re-asserts as a set-semantics no-op across re-runs.
"""

from __future__ import annotations

from datetime import datetime, timezone

from msr_extraction.sparql import SparqlClient

#: Deterministic per-pipeline Activity IRI (CURIE) referenced by every
#: fact the miner writes via ``prov:wasGeneratedBy``. Stable across runs
#: so the generation edge in ``urn:msr:data`` re-asserts as a no-op; only
#: the timestamped record in the run graph changes.
ACTIVITY_IRI = "msrd:activity-mine"

#: Mining pipeline version. Recorded as the run Activity's
#: ``owl:versionInfo``.
MINE_VERSION = "0.1.0"

#: Full IRI identifying the mining pipeline as a ``prov:Agent``, written
#: in ``<...>`` bracket form (a bare "agent:" scheme, not a prefixed
#: CURIE) because the ``@version`` segment would otherwise require
#: Turtle/SPARQL CURIE escaping of ``@``. Derived from
#: :data:`MINE_VERSION` so the version is single-sourced and cannot drift
#: between the two constants on a future bump.
AGENT_IRI = f"<agent:mine@{MINE_VERSION}>"

_PREFIXES = """\
PREFIX msr: <https://w3id.org/msr-kg/ontology#>
PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>"""

_PROVENANCE_PREFIXES = """\
PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX prov: <http://www.w3.org/ns/prov#>"""


def run_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp identifying one pipeline invocation.

    Callers (``cli.py``) generate this exactly once per invocation and
    thread it to :func:`write_activity` (and to the fact writers'
    ``run_ts`` parameter), so every generation edge and the per-run
    activity node from a single run share one ``urn:msr:run:mine/<ts>``
    IRI in ``urn:msr:provenance``.
    """
    return datetime.now(timezone.utc).isoformat()


def run_activity_iri(run_ts: str) -> str:
    """Return the bracketed per-run ``prov:Activity`` node IRI for ``run_ts``.

    ``<urn:msr:run:mine/{run_ts}>`` — the run identifier used as a
    *node*, not a graph name. Shared by :func:`activity_insert_data` and
    :func:`generation_edges_insert_data` so every fact from one
    invocation references the same activity node.
    """
    return f"<urn:msr:run:mine/{run_ts}>"


def activity_insert_data(run_ts: str) -> str:
    """Return the INSERT DATA update writing one run's per-run Activity node.

    Writes a single ``prov:Activity`` — subject :func:`run_activity_iri`
    (``<urn:msr:run:mine/{run_ts}>``), the per-run node, *not* the stable
    :data:`ACTIVITY_IRI` — into ``GRAPH <urn:msr:provenance>``, attributed
    to :data:`AGENT_IRI` via ``prov:wasAssociatedWith``, stamped with
    ``run_ts`` as both ``prov:startedAtTime`` and ``prov:endedAtTime`` (a
    single wall-clock stamp per run is acceptable at POC scale), and
    carrying :data:`MINE_VERSION` as ``owl:versionInfo``.

    ``run_ts`` is taken as a parameter rather than computed here (no
    ``datetime.now()`` in this function) so the builder is pure and
    unit-testable; see :func:`run_timestamp` for the one-per-invocation
    timestamp source.
    """
    subject = run_activity_iri(run_ts)
    return (
        f"{_PREFIXES}\n"
        "INSERT DATA {\n"
        "  GRAPH <urn:msr:provenance> {\n"
        f"    {subject} a prov:Activity ;\n"
        f"        prov:wasAssociatedWith {AGENT_IRI} ;\n"
        f'        prov:startedAtTime "{run_ts}"^^xsd:dateTime ;\n'
        f'        prov:endedAtTime   "{run_ts}"^^xsd:dateTime ;\n'
        f'        owl:versionInfo "{MINE_VERSION}" .\n'
        "  }\n"
        "}"
    )


def write_activity(run_ts: str, client: SparqlClient) -> None:
    """Send the run's per-run Activity node to the graph via ``client``.

    Builds the update with :func:`activity_insert_data` and sends it with
    ``client.update``, appending to the single shared audit graph
    ``urn:msr:provenance`` via additive ``INSERT DATA`` — never a
    graph-replace ``PUT``.

    Callers write this per-run node *before* any generation-edge writer
    (:func:`write_generation_edges`) so a crash mid-run never leaves a
    generation edge in ``urn:msr:provenance`` pointing at a run IRI that
    was never typed ``a prov:Activity``.
    """
    client.update(activity_insert_data(run_ts))


def stable_activity_insert_data() -> str:
    """Return the INSERT DATA update typing the stable per-pipeline Activity.

    Writes, into ``GRAPH <urn:msr:data>``, exactly one ``prov:Activity``
    triple set — subject :data:`ACTIVITY_IRI` (``msrd:activity-mine``,
    the stable per-pipeline IRI every mined fact already references via
    ``prov:wasGeneratedBy``), attributed to :data:`AGENT_IRI` via
    ``prov:wasAssociatedWith`` and carrying :data:`MINE_VERSION` as
    ``owl:versionInfo``. Deliberately carries **no timestamp literals**
    (no ``prov:startedAtTime``/``prov:endedAtTime``/``xsd:dateTime``) so
    this typing re-asserts as a set-semantics no-op across re-runs,
    keeping ``urn:msr:data`` byte-stable (mirrors the extraction
    pipeline's ``stable_activity_insert_data``).
    """
    return (
        f"{_PREFIXES}\n"
        "INSERT DATA {\n"
        "  GRAPH <urn:msr:data> {\n"
        f"    {ACTIVITY_IRI} a prov:Activity ;\n"
        f"        prov:wasAssociatedWith {AGENT_IRI} ;\n"
        f'        owl:versionInfo "{MINE_VERSION}" .\n'
        "  }\n"
        "}"
    )


def write_stable_activity(client: SparqlClient) -> None:
    """Send the stable per-pipeline Activity typing to ``urn:msr:data``.

    Builds the update with :func:`stable_activity_insert_data` and sends
    it with ``client.update``. Timestamp-free and deterministic, so
    re-running is a set-semantics no-op in ``urn:msr:data`` (scenario
    "The stable mine activity is typed idempotently in the data graph").
    Callers (``cli.py``) invoke this once per invocation, independent of
    and unordered with respect to :func:`write_activity` (they target
    different graphs).
    """
    client.update(stable_activity_insert_data())


def generation_edges_insert_data(fact_iris: list[str], run_ts: str) -> str:
    """Return the INSERT DATA update writing per-run generation edges.

    For each entry in ``fact_iris`` (sorted for determinism), emits
    ``{fact} prov:wasGeneratedBy <urn:msr:run:mine/{run_ts}> .`` into
    ``GRAPH <urn:msr:provenance>``. Each entry is already in SPARQL term
    form — either a ``msrd:...`` CURIE or a bracketed ``<...>`` IRI —
    exactly as it would appear as a subject in the data/proposal graph
    the fact was written to, so the generation edge's subject matches
    that fact's real term spelling. Callers should only invoke this (and
    send its result) when ``fact_iris`` is non-empty; this generalizes
    the single-writer pattern in ``mentions.py``'s
    ``provenance_insert_data`` to any mix of writers (auto-accept,
    proposal bundling) that need per-run lineage edges into the same
    shared ``urn:msr:provenance`` graph.
    """
    run_iri = run_activity_iri(run_ts)
    lines = [
        f"    {fact_iri} prov:wasGeneratedBy {run_iri} ."
        for fact_iri in sorted(fact_iris)
    ]
    body = "\n".join(lines)
    return (
        f"{_PROVENANCE_PREFIXES}\n"
        "INSERT DATA {\n"
        "  GRAPH <urn:msr:provenance> {\n"
        f"{body}\n"
        "  }\n"
        "}"
    )


def write_generation_edges(
    fact_iris: list[str], run_ts: str, client: SparqlClient
) -> None:
    """Build the per-run generation-edges update and send it, if non-empty.

    No-op (no write) when ``fact_iris`` is empty; otherwise builds the
    update with :func:`generation_edges_insert_data` and sends it via
    ``client.update``.
    """
    if not fact_iris:
        return
    client.update(generation_edges_insert_data(fact_iris, run_ts))
