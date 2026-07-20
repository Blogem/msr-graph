"""Flash relation extraction: salt<->property<->value measurements and
salt<->role / salt<->reactor edges (chunk 7, design.md D2/D3/D9; the
``relation-extraction`` spec).

Consumes chunk-5's ``segments.jsonl`` and chunk-6's ``mentions.jsonl``,
selects only sentences carrying >= 1 chunk-6 ``status:"linked"`` mention,
and calls an injected Flash client (the same :class:`~msr_extraction.
disambiguation.Completer` protocol chunk 6 uses) on top of the cached
KG-schema prompt (``kg_prompt.KGSchemaPromptCache``) to propose zero or
more structured relations per sentence. Every proposed relation is then
validated app-side against the run's closed sets (loaded salts, seed
physical properties, seed salt roles) plus a reactor grounding gate, and
recorded -- written, rejected, or skipped -- in a per-document trace
artifact ``relations.jsonl``.

This module mirrors ``disambiguation.py``'s posture throughout: DeepSeek's
JSON output mode guarantees syntactically valid JSON but never
field-level structure, so every parsed object is validated app-side, and
no function in this module ever raises on malformed input -- a bad field
just becomes a rejected/skipped record. The LLM only *proposes*; the app
*validates* (design.md D2/D3).

Flash relation JSON schema
---------------------------

The model must reply with a single JSON object::

    {"relations": [ {relation}, ... ]}

where each ``{relation}`` is one of:

- **measurement**::

    {"kind": "measurement", "salt": "<IRI>", "property": "<IRI>",
     "unit": "cP", "form_hint": "Arrhenius", "coefficients": [0.084, 4340],
     "value": null, "temperature": null, "t_min": null, "t_max": null,
     "uncertainty": "", "confidence": 0.92, "rationale": "..."}

- **role**::

    {"kind": "role", "salt": "<IRI>", "role": "<IRI>",
     "confidence": 0.8, "rationale": "..."}

- **reactor**::

    {"kind": "reactor", "salt": "<IRI>", "reactor": "<IRI>",
     "confidence": 0.9, "rationale": "..."}

``salt``/``property``/``role``/``reactor`` are full IRIs the model picks
from the known entities serialized into the cached KG-schema prompt
prefix (``build_user_prompt`` additionally identifies the *sentence's own*
linked mentions on top of that). ``coefficients``, ``value``,
``temperature``, ``t_min``, ``t_max`` follow :func:`msr_extraction.
equations.parse_correlation`'s normalized shape.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from msr_extraction.equations import EquationParse, parse_correlation
from msr_extraction.units import UnitMapper

if TYPE_CHECKING:
    from msr_extraction.config import Config
    from msr_extraction.disambiguation import Completer

# Reject/skip reason strings (RelationRecord.reason for a non-"" record).
# Pinned exactly -- testers assert against these literal strings.
REASON_BELOW_THRESHOLD = "below-threshold"
REASON_SALT_NOT_COMPOSED = "salt-not-composed"
REASON_UNKNOWN_PROPERTY = "unknown-property"
REASON_UNKNOWN_SALT = "unknown-salt"
REASON_UNKNOWN_ROLE = "unknown-role"
REASON_EQUATION_PARSE = "equation-parse"
REASON_REACTOR_NOT_GROUNDED = "reactor-not-grounded"
REASON_MALFORMED_RELATION = "malformed-relation"


@dataclass(frozen=True)
class LinkedMention:
    """One chunk-6 ``status:"linked"`` mention in a selected sentence."""

    surface_form: str
    target_iri: str
    target_kind: str  # "concept" | "class" | "salt"


@dataclass(frozen=True)
class SelectedSentence:
    """One segment carrying >= 1 linked mention -- a Flash-eligible sentence."""

    report: str
    seg_index: int
    char_start: int
    char_end: int
    text: str
    linked_mentions: list[LinkedMention]


@dataclass(frozen=True)
class KnownSets:
    """The run's closed validation sets, read from the core dataset."""

    molten_salts: set[str]
    physical_properties: set[str]
    salt_roles: set[str]
    reactor_concepts: set[str]


@dataclass(frozen=True)
class ValidatedMeasurement:
    """A validated, admissible property-measurement relation."""

    salt_iri: str
    property_iri: str
    property_name: str  # local name, e.g. "viscosity"
    unit_curie: str
    equation: EquationParse
    uncertainty: str | None
    confidence: float
    rationale: str
    report: str
    seg_index: int
    char_start: int
    char_end: int


@dataclass(frozen=True)
class ValidatedRole:
    """A validated, admissible salt<->role relation."""

    salt_iri: str
    role_iri: str
    confidence: float
    rationale: str
    report: str
    seg_index: int
    char_start: int
    char_end: int


@dataclass(frozen=True)
class ValidatedReactor:
    """A validated, admissible salt<->reactor relation (grounded + minted)."""

    salt_iri: str
    reactor_concept_iri: str
    reactor_label: str
    confidence: float
    rationale: str
    report: str
    seg_index: int
    char_start: int
    char_end: int


@dataclass(frozen=True)
class RelationRecord:
    """One line in the ``relations.jsonl`` trace -- every proposed relation."""

    report: str
    seg_index: int
    char_start: int
    char_end: int
    relation_kind: str  # "measurement" | "role" | "reactor" | "unknown"
    salt_iri: str | None
    property_iri: str | None
    role_iri: str | None
    reactor_iri: str | None
    unit_iri: str | None
    confidence: float | None
    rationale: str | None
    disposition: Literal["written", "rejected", "skipped"]
    reason: str  # "" for written; else the reject/skip reason


@dataclass(frozen=True)
class ReportExtraction:
    """The full result of :func:`extract_report` for one report."""

    measurements: list[ValidatedMeasurement]
    roles: list[ValidatedRole]
    reactors: list[ValidatedReactor]
    records: list[RelationRecord]
    sentences_seen: int
    malformed_calls: int


def _read_jsonl(path) -> list[dict]:
    """Read a JSONL file into a list of dicts, in file order.

    Blank lines are skipped. Shared by :func:`select_sentences`'s
    ``segments.jsonl``/``mentions.jsonl`` reads.
    """
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def select_sentences(report: str, config: Config) -> list[SelectedSentence]:
    """Select the report's Flash-eligible sentences (design.md D2).

    Reads ``config.segments_path(report)`` and ``config.mentions_path(report)``
    and returns one :class:`SelectedSentence` per segment that carries at
    least one ``status:"linked"`` mention (``mention.seg_index ==
    segment.index``) -- a segment with no linked mention is excluded
    entirely, so it never triggers a Flash call. Results are ordered by
    ``seg_index`` for determinism.
    """
    segments = _read_jsonl(config.segments_path(report))

    linked_by_seg: dict[int, list[LinkedMention]] = {}
    for mention in _read_jsonl(config.mentions_path(report)):
        if mention.get("status") != "linked":
            continue
        seg_index = mention["seg_index"]
        linked_by_seg.setdefault(seg_index, []).append(
            LinkedMention(
                surface_form=mention["surface_form"],
                target_iri=mention["target_iri"],
                target_kind=mention["target_kind"],
            )
        )

    selected: list[SelectedSentence] = []
    for seg in segments:
        linked_mentions = linked_by_seg.get(seg["index"])
        if not linked_mentions:
            continue
        selected.append(
            SelectedSentence(
                report=seg["report"],
                seg_index=seg["index"],
                char_start=seg["char_start"],
                char_end=seg["char_end"],
                text=seg["text"],
                linked_mentions=linked_mentions,
            )
        )

    selected.sort(key=lambda s: s.seg_index)
    return selected


def build_user_prompt(sentence: SelectedSentence) -> str:
    """Build the per-sentence user prompt appended to the cached KG-schema prefix.

    Identifies the sentence's already-linked entities (surface form,
    target IRI, kind) on top of the cached prefix's full known-entity
    serialization, and instructs the model to propose zero or more
    relations using IRIs from the known entities above -- never a new
    one. Includes the literal word "json" and a shape example, mirroring
    ``disambiguation._build_user_prompt`` (a DeepSeek JSON-output-mode
    requirement).
    """
    mentions_block = "\n".join(
        f'  - "{m.surface_form}" -> {m.target_iri} ({m.target_kind})'
        for m in sentence.linked_mentions
    )
    return (
        "Extract property-measurement, salt-role, and salt-reactor "
        "relations from the following sentence, using only IRIs from the "
        "known entities and this sentence's already-linked mentions above "
        "-- never invent a new IRI.\n\n"
        f'Sentence: "{sentence.text}"\n\n'
        "Linked mentions in this sentence:\n"
        f"{mentions_block}\n\n"
        "Respond with a single json object of the shape:\n"
        '  {"relations": [\n'
        '    {"kind": "measurement", "salt": "<IRI>", "property": "<IRI>", '
        '"unit": "cP", "form_hint": "Arrhenius", '
        '"coefficients": [0.084, 4340], "value": null, "temperature": null, '
        '"t_min": null, "t_max": null, "uncertainty": "", '
        '"confidence": 0.92, "rationale": "..."},\n'
        '    {"kind": "role", "salt": "<IRI>", "role": "<IRI>", '
        '"confidence": 0.8, "rationale": "..."},\n'
        '    {"kind": "reactor", "salt": "<IRI>", "reactor": "<IRI>", '
        '"confidence": 0.9, "rationale": "..."}\n'
        "  ]}\n\n"
        "If the sentence asserts no relation, return {\"relations\": []}. "
        "Return only the json object, no other text."
    )


def extract_relations(
    sentence: SelectedSentence, prompt_prefix: str, client: Completer
) -> tuple[list[dict], bool]:
    """Call Flash for one sentence and return its proposed relations, or ([], False).

    Calls ``client.complete(prompt_prefix, build_user_prompt(sentence))``,
    parses the reply as JSON, and pulls ``obj["relations"]``. Never
    raises: a client exception, malformed JSON, a non-dict payload, or a
    missing/non-list ``"relations"`` all yield ``([], False)``.
    """
    user_prompt = build_user_prompt(sentence)

    try:
        raw = client.complete(prompt_prefix, user_prompt)
    except Exception:
        return [], False

    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return [], False

    if not isinstance(parsed, dict):
        return [], False

    relations = parsed.get("relations")
    if not isinstance(relations, list):
        return [], False

    return relations, True


def _to_float(value: object) -> float | None:
    """Best-effort numeric coercion; ``None`` on anything not cleanly numeric.

    Guards :func:`msr_extraction.equations.parse_correlation` (whose own
    ``float(...)`` calls would raise on a non-numeric LLM-supplied string)
    so this module never raises on a malformed proposed relation.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _to_float_list(value: object) -> list[float] | None:
    """Best-effort coercion of a proposed ``coefficients`` list; ``None`` if
    ``value`` isn't a list or any element fails :func:`_to_float`."""
    if not isinstance(value, list):
        return None
    out: list[float] = []
    for item in value:
        f = _to_float(item)
        if f is None:
            return None
        out.append(f)
    return out


def _local_name(iri: str) -> str:
    """The local name of ``iri`` (after the last ``#``, else unchanged)."""
    if "#" in iri:
        return iri.rsplit("#", 1)[1]
    return iri


def validate_relation(
    raw: dict,
    sentence: SelectedSentence,
    known: KnownSets,
    unit_mapper: UnitMapper,
    threshold: float,
) -> tuple[object | None, RelationRecord]:
    """Validate one Flash-proposed relation against the closed sets + gates.

    Never raises: any anomaly (missing/malformed field, unknown IRI,
    unmappable unit, an equation that fails to parse, a reactor that
    isn't grounded) yields ``(None, record)`` with the record's
    ``disposition``/``reason`` set appropriately -- see the module
    docstring's reason-string constants. Returns
    ``(ValidatedMeasurement|ValidatedRole|ValidatedReactor, record)`` with
    ``disposition="written"`` (``reason=""``) only when every check
    passes.
    """

    def _record(
        relation_kind: str,
        disposition: Literal["written", "rejected", "skipped"],
        reason: str,
        *,
        salt_iri: str | None = None,
        property_iri: str | None = None,
        role_iri: str | None = None,
        reactor_iri: str | None = None,
        unit_iri: str | None = None,
        confidence: float | None = 0.0,
        rationale: str | None = "",
    ) -> RelationRecord:
        return RelationRecord(
            report=sentence.report,
            seg_index=sentence.seg_index,
            char_start=sentence.char_start,
            char_end=sentence.char_end,
            relation_kind=relation_kind,
            salt_iri=salt_iri,
            property_iri=property_iri,
            role_iri=role_iri,
            reactor_iri=reactor_iri,
            unit_iri=unit_iri,
            confidence=confidence,
            rationale=rationale,
            disposition=disposition,
            reason=reason,
        )

    if not isinstance(raw, dict):
        return None, _record("unknown", "rejected", REASON_MALFORMED_RELATION)

    raw_confidence = raw.get("confidence")
    if isinstance(raw_confidence, bool) or not isinstance(
        raw_confidence, (int, float)
    ):
        confidence = 0.0
    else:
        confidence = float(raw_confidence)

    raw_rationale = raw.get("rationale")
    rationale = raw_rationale if isinstance(raw_rationale, str) else ""

    kind = raw.get("kind")

    # 1. Threshold first -- unconditional, before any kind-specific check.
    if confidence < threshold:
        return None, _record(
            str(kind) if isinstance(kind, str) else "unknown",
            "skipped",
            REASON_BELOW_THRESHOLD,
            confidence=confidence,
            rationale=rationale,
        )

    # 2. kind == "measurement"
    if kind == "measurement":
        salt_raw = raw.get("salt")
        property_raw = raw.get("property")
        unit_raw = raw.get("unit")
        if (
            not isinstance(salt_raw, str)
            or not isinstance(property_raw, str)
            or not isinstance(unit_raw, str)
        ):
            return None, _record(
                "unknown",
                "rejected",
                REASON_MALFORMED_RELATION,
                confidence=confidence,
                rationale=rationale,
            )

        if salt_raw not in known.molten_salts:
            # Bare-concept skip (design.md D6/5.5): any measurement salt not
            # in the composed-individual set is skipped, never rejected --
            # nothing distinguishes a bare formula from any other unknown
            # salt referent here.
            return None, _record(
                "measurement",
                "skipped",
                REASON_SALT_NOT_COMPOSED,
                salt_iri=salt_raw,
                property_iri=property_raw,
                confidence=confidence,
                rationale=rationale,
            )

        if property_raw not in known.physical_properties:
            return None, _record(
                "measurement",
                "rejected",
                REASON_UNKNOWN_PROPERTY,
                salt_iri=salt_raw,
                property_iri=property_raw,
                confidence=confidence,
                rationale=rationale,
            )

        property_name = _local_name(property_raw)

        unit_result = unit_mapper.resolve(unit_raw, property_name)
        if not unit_result.ok:
            return None, _record(
                "measurement",
                "rejected",
                f"unit-{unit_result.reason}",
                salt_iri=salt_raw,
                property_iri=property_raw,
                confidence=confidence,
                rationale=rationale,
            )

        equation = parse_correlation(
            form_hint=raw.get("form_hint")
            if isinstance(raw.get("form_hint"), str)
            else None,
            coefficients=_to_float_list(raw.get("coefficients")),
            value=_to_float(raw.get("value")),
            temperature=_to_float(raw.get("temperature")),
            t_min=_to_float(raw.get("t_min")),
            t_max=_to_float(raw.get("t_max")),
        )
        if equation is None:
            return None, _record(
                "measurement",
                "rejected",
                REASON_EQUATION_PARSE,
                salt_iri=salt_raw,
                property_iri=property_raw,
                unit_iri=unit_result.unit_curie,
                confidence=confidence,
                rationale=rationale,
            )

        raw_uncertainty = raw.get("uncertainty")
        uncertainty = (
            raw_uncertainty
            if isinstance(raw_uncertainty, str) and raw_uncertainty
            else None
        )

        measurement = ValidatedMeasurement(
            salt_iri=salt_raw,
            property_iri=property_raw,
            property_name=property_name,
            unit_curie=unit_result.unit_curie,
            equation=equation,
            uncertainty=uncertainty,
            confidence=confidence,
            rationale=rationale,
            report=sentence.report,
            seg_index=sentence.seg_index,
            char_start=sentence.char_start,
            char_end=sentence.char_end,
        )
        return measurement, _record(
            "measurement",
            "written",
            "",
            salt_iri=salt_raw,
            property_iri=property_raw,
            unit_iri=unit_result.unit_curie,
            confidence=confidence,
            rationale=rationale,
        )

    # 3. kind == "role"
    if kind == "role":
        salt_raw = raw.get("salt")
        role_raw = raw.get("role")
        if not isinstance(salt_raw, str) or not isinstance(role_raw, str):
            return None, _record(
                "unknown",
                "rejected",
                REASON_MALFORMED_RELATION,
                confidence=confidence,
                rationale=rationale,
            )

        if salt_raw not in known.molten_salts:
            return None, _record(
                "role",
                "rejected",
                REASON_UNKNOWN_SALT,
                salt_iri=salt_raw,
                role_iri=role_raw,
                confidence=confidence,
                rationale=rationale,
            )

        if role_raw not in known.salt_roles:
            return None, _record(
                "role",
                "rejected",
                REASON_UNKNOWN_ROLE,
                salt_iri=salt_raw,
                role_iri=role_raw,
                confidence=confidence,
                rationale=rationale,
            )

        role = ValidatedRole(
            salt_iri=salt_raw,
            role_iri=role_raw,
            confidence=confidence,
            rationale=rationale,
            report=sentence.report,
            seg_index=sentence.seg_index,
            char_start=sentence.char_start,
            char_end=sentence.char_end,
        )
        return role, _record(
            "role",
            "written",
            "",
            salt_iri=salt_raw,
            role_iri=role_raw,
            confidence=confidence,
            rationale=rationale,
        )

    # 4. kind == "reactor"
    if kind == "reactor":
        salt_raw = raw.get("salt")
        reactor_raw = raw.get("reactor")
        if not isinstance(salt_raw, str) or not isinstance(reactor_raw, str):
            return None, _record(
                "unknown",
                "rejected",
                REASON_MALFORMED_RELATION,
                confidence=confidence,
                rationale=rationale,
            )

        if salt_raw not in known.molten_salts:
            return None, _record(
                "reactor",
                "rejected",
                REASON_UNKNOWN_SALT,
                salt_iri=salt_raw,
                reactor_iri=reactor_raw,
                confidence=confidence,
                rationale=rationale,
            )

        # Grounding gate (design.md D3/D9): the reactor reference must both
        # be in the reactor-concept closed set AND be a chunk-6 linked
        # mention in this same sentence -- the mention supplies the
        # surface-form label for the minted individual.
        grounding_mention = next(
            (
                m
                for m in sentence.linked_mentions
                if m.target_iri == reactor_raw
            ),
            None,
        )
        if reactor_raw not in known.reactor_concepts or grounding_mention is None:
            return None, _record(
                "reactor",
                "rejected",
                REASON_REACTOR_NOT_GROUNDED,
                salt_iri=salt_raw,
                reactor_iri=reactor_raw,
                confidence=confidence,
                rationale=rationale,
            )

        reactor = ValidatedReactor(
            salt_iri=salt_raw,
            reactor_concept_iri=reactor_raw,
            reactor_label=grounding_mention.surface_form,
            confidence=confidence,
            rationale=rationale,
            report=sentence.report,
            seg_index=sentence.seg_index,
            char_start=sentence.char_start,
            char_end=sentence.char_end,
        )
        return reactor, _record(
            "reactor",
            "written",
            "",
            salt_iri=salt_raw,
            reactor_iri=reactor_raw,
            confidence=confidence,
            rationale=rationale,
        )

    # 5. Unknown/missing kind.
    return None, _record(
        "unknown",
        "rejected",
        REASON_MALFORMED_RELATION,
        confidence=confidence,
        rationale=rationale,
    )


def write_relations_jsonl(
    report: str, records: list[RelationRecord], config: Config
) -> None:
    """Write ``config.relations_path(report)``: one JSON object per record.

    Deterministic given deterministic input ordering (design.md D8-style
    "regenerated wholesale per run"). UTF-8, ``ensure_ascii=False``, one
    object per line, keys in the artifact's documented order -- mirrors
    ``linker.write_mentions_jsonl``.
    """
    path = config.relations_path(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            obj = {
                "report": record.report,
                "seg_index": record.seg_index,
                "char_start": record.char_start,
                "char_end": record.char_end,
                "relation_kind": record.relation_kind,
                "salt_iri": record.salt_iri,
                "property_iri": record.property_iri,
                "role_iri": record.role_iri,
                "reactor_iri": record.reactor_iri,
                "unit_iri": record.unit_iri,
                "confidence": record.confidence,
                "rationale": record.rationale,
                "disposition": record.disposition,
                "reason": record.reason,
            }
            fh.write(json.dumps(obj, ensure_ascii=False))
            fh.write("\n")


def extract_report(
    report: str,
    config: Config,
    prompt_prefix: str,
    client: Completer,
    known: KnownSets,
    unit_mapper: UnitMapper,
) -> ReportExtraction:
    """Extract, validate, and trace every relation in one report.

    Ties the module together: :func:`select_sentences` ->
    :func:`extract_relations` per sentence -> :func:`validate_relation`
    per proposed relation -> collects payloads by kind and every record
    (any disposition) -> writes the ``relations.jsonl`` trace via
    :func:`write_relations_jsonl` -> returns the full
    :class:`ReportExtraction`. Ordering is deterministic: sentences by
    ``seg_index`` (already guaranteed by :func:`select_sentences`), and
    relations within a sentence in the order Flash returned them.
    ``malformed_calls`` counts sentences whose Flash reply failed to
    parse into a usable relations list (:func:`extract_relations`
    returning ``ok=False``) -- such a sentence contributes no records at
    all (nothing to trace), consistent with "malformed output never
    produces a silent write."
    """
    sentences = select_sentences(report, config)

    measurements: list[ValidatedMeasurement] = []
    roles: list[ValidatedRole] = []
    reactors: list[ValidatedReactor] = []
    records: list[RelationRecord] = []
    malformed_calls = 0

    for sentence in sentences:
        raw_relations, ok = extract_relations(sentence, prompt_prefix, client)
        if not ok:
            malformed_calls += 1
            continue

        for raw in raw_relations:
            payload, record = validate_relation(
                raw, sentence, known, unit_mapper, config.confidence_threshold
            )
            records.append(record)
            if isinstance(payload, ValidatedMeasurement):
                measurements.append(payload)
            elif isinstance(payload, ValidatedRole):
                roles.append(payload)
            elif isinstance(payload, ValidatedReactor):
                reactors.append(payload)

    write_relations_jsonl(report, records, config)

    return ReportExtraction(
        measurements=measurements,
        roles=roles,
        reactors=reactors,
        records=records,
        sentences_seen=len(sentences),
        malformed_calls=malformed_calls,
    )
