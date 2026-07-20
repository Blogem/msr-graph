"""Shared extraction-run provenance helpers.

Provenance vocabulary and per-run Activity writer for the extraction
pipeline (provenance-run-lineage design.md D1, D2, D4). Every
``msr:Mention``/``msr:Document`` written by this pipeline (see
``mentions.py``/``documents.py``) references the deterministic
:data:`ACTIVITY_IRI` via ``prov:wasGeneratedBy`` in ``urn:msr:data`` so that
edge stays a set-semantics no-op across re-runs. Each CLI invocation
additionally mints a **per-run** ``prov:Activity`` *node* — the run
identifier ``urn:msr:run:extraction/<ts>`` used as an IRI, not a graph
name — and writes it, fully attributed (agent, start/end time, ontology
version), into the single shared audit graph ``urn:msr:provenance``. The
same invocation also writes one ``<fact> prov:wasGeneratedBy
<urn:msr:run:extraction/<ts>>`` generation edge per written mention/document
into ``urn:msr:provenance`` (see ``mentions.py``/``documents.py``). Because
the per-run node and its edges are timestamped, they are intentionally
outside the ``urn:msr:data`` idempotency guarantee (design.md D4) — a
repeat wall-clock run appends a new per-run activity and generation edges
to ``urn:msr:provenance`` rather than mutating existing data.
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
    thread it to :func:`write_activity` (and to the triple writers'
    ``run_ts`` parameter), so every mention/document generation edge and
    the per-run activity node from a single run share one
    ``urn:msr:run:extraction/<ts>`` IRI in ``urn:msr:provenance``.
    """
    return datetime.now(timezone.utc).isoformat()


def run_activity_iri(run_ts: str) -> str:
    """Return the bracketed per-run ``prov:Activity`` node IRI for ``run_ts``.

    ``<urn:msr:run:extraction/{run_ts}>`` — the run identifier used as a
    *node*, not a graph name (design.md D1/D2). Shared by
    :func:`activity_insert_data` and the per-run generation-edge builders
    in ``mentions.py``/``documents.py`` so every fact from one invocation
    references the same activity node.
    """
    return f"<urn:msr:run:extraction/{run_ts}>"


def activity_insert_data(run_ts: str) -> str:
    """Return the INSERT DATA update writing one run's per-run Activity node.

    Writes a single ``prov:Activity`` — subject :func:`run_activity_iri`
    (``<urn:msr:run:extraction/{run_ts}>``), the per-run node, *not* the
    stable :data:`ACTIVITY_IRI` — into ``GRAPH <urn:msr:provenance>``,
    attributed to :data:`AGENT_IRI` via ``prov:wasAssociatedWith``, stamped
    with ``run_ts`` as both ``prov:startedAtTime`` and ``prov:endedAtTime``
    (a single wall-clock stamp per run is acceptable at POC scale, design
    D1), and carrying :data:`EXTRACTION_VERSION` as ``owl:versionInfo``.

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
        f'        owl:versionInfo "{EXTRACTION_VERSION}" .\n'
        "  }\n"
        "}"
    )


def write_activity(run_ts: str, client: SparqlClient) -> None:
    """Send the run's per-run Activity node to the graph via ``client``.

    Builds the update with :func:`activity_insert_data` and sends it with
    ``client.update``, appending to the single shared audit graph
    ``urn:msr:provenance`` via additive ``INSERT DATA`` — never a
    graph-replace ``PUT`` (design.md D2, D5).
    """
    client.update(activity_insert_data(run_ts))
