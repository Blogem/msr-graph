"""Shared extraction-run provenance helpers.

Provenance vocabulary and per-run Activity writer for the extraction
pipeline (design.md D2, D6, D8). Every ``msr:Mention``/``msr:Document``
written by this pipeline (see ``mentions.py``/``documents.py``) references
the deterministic :data:`ACTIVITY_IRI` via ``prov:wasGeneratedBy`` so that
edge stays a set-semantics no-op across re-runs. Each CLI invocation
additionally writes exactly one timestamped ``prov:Activity`` *record*
(agent, start/end time, ontology version) describing that run into its
own named graph ``urn:msr:run:extraction/<ts>``; because that record is
timestamped it is intentionally outside the ``urn:msr:data`` idempotency
guarantee (design.md D8) — a repeat wall-clock run appends a new run
graph rather than mutating an existing one.
"""

from __future__ import annotations

from datetime import datetime, timezone

from msr_extraction.sparql import SparqlClient

#: Deterministic per-pipeline Activity IRI (CURIE) referenced by every
#: written Mention/Document via ``prov:wasGeneratedBy`` (design.md D2).
#: Stable across runs so the generation edge in ``urn:msr:data`` re-asserts
#: as a no-op; only the timestamped record in the run graph changes.
ACTIVITY_IRI = "msrd:activity-extraction"

#: Extraction pipeline version. Recorded as the run Activity's
#: ``owl:versionInfo`` (design.md D1/D6).
EXTRACTION_VERSION = "0.3.0"

#: Full IRI identifying the extraction pipeline as a ``prov:Agent``,
#: written in ``<...>`` bracket form (a bare "agent:" scheme, not a
#: prefixed CURIE) because the ``@version`` segment would otherwise
#: require Turtle/SPARQL CURIE escaping of ``@``. Derived from
#: :data:`EXTRACTION_VERSION` so the version is single-sourced and cannot
#: drift between the two constants on a future bump.
AGENT_IRI = f"<agent:extraction@{EXTRACTION_VERSION}>"

_PREFIXES = """\
PREFIX msr: <https://w3id.org/msr-kg/ontology#>
PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>"""


def run_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp identifying one pipeline invocation.

    Callers (``cli.py``) generate this exactly once per invocation and
    thread it to :func:`write_activity` (and, where relevant, to the
    triple writers), so every mention/document/activity record from a
    single run shares one ``urn:msr:run:extraction/<ts>`` graph.
    """
    return datetime.now(timezone.utc).isoformat()


def activity_insert_data(run_ts: str) -> str:
    """Return the INSERT DATA update writing one run's Activity record.

    Writes a single ``prov:Activity`` (:data:`ACTIVITY_IRI`) into
    ``GRAPH <urn:msr:run:extraction/{run_ts}>``, attributed to
    :data:`AGENT_IRI` via ``prov:wasAssociatedWith``, stamped with
    ``run_ts`` as both ``prov:startedAtTime`` and ``prov:endedAtTime``
    (a single wall-clock stamp per run is acceptable at POC scale, design
    D6), and carrying :data:`EXTRACTION_VERSION` as ``owl:versionInfo``.

    ``run_ts`` is taken as a parameter rather than computed here (no
    ``datetime.now()`` in this function) so the builder is pure and
    unit-testable; see :func:`run_timestamp` for the one-per-invocation
    timestamp source.
    """
    return (
        f"{_PREFIXES}\n"
        "INSERT DATA {\n"
        f"  GRAPH <urn:msr:run:extraction/{run_ts}> {{\n"
        f"    {ACTIVITY_IRI} a prov:Activity ;\n"
        f"        prov:wasAssociatedWith {AGENT_IRI} ;\n"
        f'        prov:startedAtTime "{run_ts}"^^xsd:dateTime ;\n'
        f'        prov:endedAtTime   "{run_ts}"^^xsd:dateTime ;\n'
        f'        owl:versionInfo "{EXTRACTION_VERSION}" .\n'
        "  }\n"
        "}"
    )


def write_activity(run_ts: str, client: SparqlClient) -> None:
    """Send the run's Activity record to the graph via ``client``.

    Builds the update with :func:`activity_insert_data` and sends it with
    ``client.update``, appending a new timestamped audit graph
    (``urn:msr:run:extraction/{run_ts}``) — never a graph-replace ``PUT``.
    """
    client.update(activity_insert_data(run_ts))
