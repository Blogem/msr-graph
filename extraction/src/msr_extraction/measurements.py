"""Text-derived measurement triple emission and dual-store writer (chunk 7, D5-D8).

Writes one text-derived ``msr:PropertyMeasurement`` to **both** stores the
chunk-4 agent reads, sharing one deterministic locator (design.md D5, spec
``text-measurement-writing``):

- ``urn:msr:data`` — the ``msr:PropertyMeasurement`` triples, carrying
  ``msr:ofSalt``/``msr:forProperty``/``msr:hasUnit``/``msr:equationForm``,
  a both-or-neither ordered ``msr:validTempMin``/``Max``, the shared
  ``msr:dataLocator``, the citation ``msr:citedIn`` the source ``Document``,
  ``msr:extractionConfidence``/``msr:extractionRationale``, and stable
  generation provenance (``prov:wasGeneratedBy msrd:activity-extraction`` /
  ``prov:wasDerivedFrom`` the source document) -- via additive SPARQL
  ``INSERT DATA``, never a graph-replace ``PUT``.
- SQLite -- a ``measurement_value`` row (``source='document'``) keyed by the
  same locator, via :func:`msr_extraction.measurement_store.upsert_rows`.

The subject IRI (:func:`measurement_iri`) is a deterministic function of the
locator -- no blank nodes -- so re-running the writer over the same
measurement is a set-semantics no-op in ``urn:msr:data`` and an
upsert-in-place no-op in SQLite. Coefficients live only in SQLite; the graph
carries just the ``msr:EquationForm`` local name (design.md D5). Each written
measurement additionally gets a per-run generation edge into
``urn:msr:provenance`` (provenance-run-lineage design.md D1-D3):
``<measurement> prov:wasGeneratedBy <urn:msr:run:extraction/<ts>>``, one per
measurement per invocation, so per-run lineage accumulates without touching
the idempotent ``urn:msr:data`` block.
"""

from __future__ import annotations

import math

from msr_extraction.equations import EquationParse
from msr_extraction.measurement_store import MeasurementRow, upsert_rows
from msr_extraction.provenance import ACTIVITY_IRI, run_activity_iri
from msr_extraction.sparql import SparqlClient

MSR = "https://w3id.org/msr-kg/ontology#"
MSRD = "https://w3id.org/msr-kg/data#"

_PREFIXES = """\
PREFIX msr: <https://w3id.org/msr-kg/ontology#>
PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX unit: <http://qudt.org/vocab/unit/>"""

_PROVENANCE_PREFIXES = """\
PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX prov: <http://www.w3.org/ns/prov#>"""


def _escape_literal(s: str) -> str:
    """Escape a string for use inside a double-quoted Turtle/SPARQL literal."""
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
    )


def _term(iri: str) -> str:
    """Return a Turtle term for ``iri``: a CURIE for known namespaces, else ``<iri>``.

    ``iri`` may arrive as a full IRI (from the graph reader) or already as a
    ``msr:``/``msrd:`` CURIE (from a caller that already shortened it) --
    both are handled so callers never have to normalize first. Mirrors
    ``edges.py``'s ``_term`` exactly (this module's emission conventions are
    shared with ``edges.py``).
    """
    if iri.startswith("msr:") or iri.startswith("msrd:"):
        return iri
    if iri.startswith(MSR):
        return f"msr:{iri[len(MSR):]}"
    if iri.startswith(MSRD):
        return f"msrd:{iri[len(MSRD):]}"
    return f"<{iri}>"


def _local(iri: str) -> str:
    """Return the local name of ``iri``: after ``#`` for a full IRI, after ``:`` for a CURIE."""
    if "#" in iri:
        return iri.rsplit("#", 1)[1]
    if ":" in iri:
        return iri.rsplit(":", 1)[1]
    return iri


def slugify(s: str) -> str:
    """Slugify ``s`` using the exact Go rule (loader parity).

    Replaces each of ``' '``, ``'/'``, ``'#'``, ``'|'``, ``'='``, ``'@'``
    with ``'-'``, collapses repeated ``--`` to ``-``, and strips leading and
    trailing ``-``. Identical to ``edges.py``'s ``slugify``.
    """
    out = s
    for ch in (" ", "/", "#", "|", "=", "@"):
        out = out.replace(ch, "-")
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


def _format_number(v: float) -> str:
    """Render ``v`` as a bare Turtle decimal literal (Go loader ``formatFloat`` parity).

    Shortest round-tripping decimal, never scientific notation, always
    carrying an explicit ``.0`` for whole numbers so the literal parses as
    ``xsd:decimal`` rather than ``xsd:integer`` -- otherwise re-running the
    writer against unchanged input would add a second, distinct
    ``validTempMin``/``Max`` triple instead of being a set-semantics no-op.
    """
    s = repr(float(v))
    if "e" in s or "E" in s:
        s = format(float(v), "f")
    if "." not in s:
        s += ".0"
    return s


def _format_confidence(v: float) -> str:
    """Render a confidence value as a safe, plain ``xsd:decimal`` literal.

    Defense-in-depth alongside relations.py's validation-boundary guard: a
    non-finite value (``NaN``/``Infinity``/``-Infinity``) must never be
    interpolated into emitted Turtle/SPARQL as the bare token ``nan``/
    ``inf`` (invalid, and not even quoted), so any non-finite input is
    clamped to ``0.0`` here rather than passed through. Reuses
    :func:`_format_number`'s plain-decimal, never-scientific-notation
    rendering for the finite case.
    """
    if not math.isfinite(v):
        v = 0.0
    return _format_number(v)


def salt_slug(salt_iri: str) -> str:
    """Local name of the salt IRI with a leading ``'salt-'`` stripped.

    E.g. ``'https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0'`` ->
    ``'BeF2-LiF-34.0-66.0'``.
    """
    local = _local(salt_iri)
    if local.startswith("salt-"):
        return local[len("salt-") :]
    return local


def build_locator(report: str, property_name: str, salt_iri: str) -> str:
    """Return the shared deterministic locator for a text-derived measurement.

    ``'doc/{report}/{property_name}#{salt_slug(salt_iri)}'``, e.g.
    ``'doc/ORNL-TM-2316/viscosity#BeF2-LiF-34.0-66.0'``. The ``doc/``
    namespace keeps text-derived values from colliding with NIST rows
    (``nist-srd27/...``) for the same salt and property (design.md,
    "Resolved Questions: slug spelling settled at implementation").
    """
    return f"doc/{report}/{property_name}#{salt_slug(salt_iri)}"


def measurement_iri(locator: str) -> str:
    """Return the deterministic ``msrd:`` CURIE for a measurement (Go loader parity).

    ``'msrd:m-' + slugify(locator)`` -- mirrors the Go ``buildMeasurementIRI``.
    """
    return f"msrd:m-{slugify(locator)}"


def measurement_triples(
    *,
    locator: str,
    salt_iri: str,
    property_iri: str,
    unit_curie: str,
    equation_form: str,
    t_min: float | None,
    t_max: float | None,
    report: str,
    confidence: float,
    rationale: str,
) -> str:
    """Return the Turtle triple block for one measurement (no ``INSERT`` wrapper).

    Produces (with proper literal escaping)::

        msrd:m-{slug} a msr:PropertyMeasurement ;
            msr:ofSalt {salt} ;
            msr:forProperty {property} ;
            msr:hasUnit {unit_curie} ;
            msr:equationForm msr:{equation_form} ;
            msr:validTempMin {t_min} ;   # only if BOTH t_min and t_max are not None
            msr:validTempMax {t_max} ;   # both-or-neither
            msr:dataLocator "{locator}" ;
            msr:citedIn msrd:{report} ;
            msr:extractionConfidence "{confidence}"^^xsd:decimal ;
            msr:extractionRationale "{rationale}"^^xsd:string ;
            prov:wasGeneratedBy msrd:activity-extraction ;
            prov:wasDerivedFrom msrd:{report} .

    The subject IRI is deterministic (:func:`measurement_iri`); no blank
    nodes are used. ``msr:validTempMin``/``Max`` are emitted only when both
    ``t_min`` and ``t_max`` are not ``None`` (a lone bound is dropped --
    SHACL ``ValidTemperatureRangeShape``); ``t_min``/``t_max`` arrive already
    ordered from :class:`msr_extraction.equations.EquationParse`.
    """
    subject = measurement_iri(locator)
    salt = _term(salt_iri)
    prop = _term(property_iri)
    rationale_escaped = _escape_literal(rationale)
    locator_escaped = _escape_literal(locator)

    lines = [
        f"{subject} a msr:PropertyMeasurement ;",
        f"    msr:ofSalt {salt} ;",
        f"    msr:forProperty {prop} ;",
        f"    msr:hasUnit {unit_curie} ;",
        f"    msr:equationForm msr:{equation_form} ;",
    ]
    if t_min is not None and t_max is not None:
        lines.append(f"    msr:validTempMin {_format_number(t_min)} ;")
        lines.append(f"    msr:validTempMax {_format_number(t_max)} ;")
    lines.append(f'    msr:dataLocator "{locator_escaped}" ;')
    lines.append(f"    msr:citedIn msrd:{report} ;")
    lines.append(
        f'    msr:extractionConfidence "{_format_confidence(confidence)}"^^xsd:decimal ;'
    )
    lines.append(f'    msr:extractionRationale "{rationale_escaped}"^^xsd:string ;')
    lines.append(f"    prov:wasGeneratedBy {ACTIVITY_IRI} ;")
    lines.append(f"    prov:wasDerivedFrom msrd:{report} .")
    return "\n".join(lines)


def insert_data(triples_block: str) -> str:
    """Wrap a triples block in a full SPARQL ``INSERT DATA`` update.

    Includes the required prefix declarations (``msr:``, ``msrd:``,
    ``prov:``, ``xsd:``, ``unit:``) and targets ``GRAPH <urn:msr:data>``,
    matching the additive, graph-scoped write contract used by
    ``mentions.py``/``edges.py``.
    """
    indented = "\n".join(f"    {line}" for line in triples_block.splitlines())
    return (
        f"{_PREFIXES}\n"
        "INSERT DATA {\n"
        "  GRAPH <urn:msr:data> {\n"
        f"{indented}\n"
        "  }\n"
        "}"
    )


def measurement_provenance_insert_data(measurement_iris: list[str], run_ts: str) -> str:
    """Return the INSERT DATA update writing per-run generation edges.

    For each measurement IRI (already sorted/ordered by the caller for
    determinism), emits ``<measurement-iri> prov:wasGeneratedBy
    <urn:msr:run:extraction/{run_ts}>`` into ``GRAPH <urn:msr:provenance>``.
    The subject reuses the exact ``msrd:m-...`` CURIE form produced by
    :func:`measurement_iri` -- the same subject the stable ``urn:msr:data``
    block uses.
    """
    run_iri = run_activity_iri(run_ts)
    lines = [
        f"    {iri} prov:wasGeneratedBy {run_iri} ." for iri in measurement_iris
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


def to_row(
    *,
    locator: str,
    salt_iri: str,
    property_name: str,
    equation: EquationParse,
    uncertainty: str | None,
    doc_id: str,
) -> MeasurementRow:
    """Build the ``measurement_value`` row for a parsed equation.

    ``equation.coeffs`` maps positionally onto ``c0..c4`` -- unused trailing
    slots are ``None``. ``salt`` is the canonical slug
    (:func:`salt_slug`), ``source`` is always ``'document'`` (text-derived).
    """
    coeffs = equation.coeffs

    def _coeff(i: int) -> float | None:
        return coeffs[i] if i < len(coeffs) else None

    return MeasurementRow(
        locator=locator,
        salt=salt_slug(salt_iri),
        property=property_name,
        equation_form=equation.form,
        c0=_coeff(0),
        c1=_coeff(1),
        c2=_coeff(2),
        c3=_coeff(3),
        c4=_coeff(4),
        t_min=equation.t_min,
        t_max=equation.t_max,
        uncertainty=uncertainty,
        doc_id=doc_id,
        source="document",
    )


def write_measurement(
    *,
    salt_iri: str,
    property_iri: str,
    property_name: str,
    unit_curie: str,
    equation: EquationParse,
    uncertainty: str | None,
    confidence: float,
    rationale: str,
    report: str,
    client: SparqlClient,
    conn,
    run_ts: str,
) -> str:
    """Write one text-derived measurement to both stores; return its IRI.

    Builds the shared locator (:func:`build_locator`) and measurement IRI
    (:func:`measurement_iri`), then: (1) sends the ``urn:msr:data``
    ``INSERT DATA`` (:func:`measurement_triples` wrapped by
    :func:`insert_data`) via ``client.update``; (2) upserts the
    ``measurement_value`` row (:func:`to_row`) via
    :func:`msr_extraction.measurement_store.upsert_rows`; (3) sends the
    per-run ``urn:msr:provenance`` generation edge
    (:func:`measurement_provenance_insert_data`) via ``client.update``. The
    run-level stable/per-run activity *nodes* are written by the CLI
    orchestration before any write -- this function only emits the per-fact
    generation edge, exactly like ``mentions.write_mentions``.
    """
    locator = build_locator(report, property_name, salt_iri)
    miri = measurement_iri(locator)

    triples = measurement_triples(
        locator=locator,
        salt_iri=salt_iri,
        property_iri=property_iri,
        unit_curie=unit_curie,
        equation_form=equation.form,
        t_min=equation.t_min,
        t_max=equation.t_max,
        report=report,
        confidence=confidence,
        rationale=rationale,
    )
    client.update(insert_data(triples))

    row = to_row(
        locator=locator,
        salt_iri=salt_iri,
        property_name=property_name,
        equation=equation,
        uncertainty=uncertainty,
        doc_id=report,
    )
    upsert_rows(conn, [row])

    client.update(measurement_provenance_insert_data([miri], run_ts))

    return miri
