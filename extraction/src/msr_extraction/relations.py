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
import math
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal

from msr_extraction.edges import slugify as _reactor_slugify
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
REASON_DUPLICATE_LOCATOR = "duplicate-locator"
# Chunk 11 (ingest-iaea-safety D4, task 4.1-4.3) -- closed-set rejections
# for the two safety digital-thread linking relations. A safety-branch
# individual (SafetyFunction/Requirement) is grown, not seeded, so it only
# validates once the safety branch has been mined + approved into core
# (design.md D4 "two phases against one closed-set contract"); until then
# any edge naming one is rejected with these reasons, exactly like an
# unknown salt/property/role above.
REASON_UNKNOWN_SAFETY_FUNCTION = "unknown-safety-function"
REASON_UNKNOWN_REQUIREMENT = "unknown-requirement"


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
    # Chunk 11 (ingest-iaea-safety D4) -- the grown (not seeded) SafetyFunction
    # / Requirement individual IRIs, populated by the second-phase caller once
    # the safety branch has been mined + approved into core (graph_reader.py's
    # ``read_safety_functions``/``read_requirements``). Defaulted to an empty
    # frozenset so every existing chemistry-only caller/test is unaffected.
    safety_functions: frozenset[str] = frozenset()
    requirements: frozenset[str] = frozenset()


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
class ValidatedServedByProperty:
    """A validated, admissible ``msr:servedByProperty`` relation.

    ``SafetyFunction -> PhysicalProperty`` (design.md D4, chunk 11 task
    4.1): asserted only when the sentence states the safety function
    depends on / is served by the property -- a co-mention with no stated
    dependency never reaches here (the model is instructed, in
    :func:`build_user_prompt`, to propose nothing for that case, so there
    is no payload to validate). ``standard_name`` is the optional named
    IAEA standard (task 4.4, ``rdfs:seeAlso``) the source ties to this
    safety function, or ``None`` when the text names none.
    """

    safety_function_iri: str
    property_iri: str
    confidence: float
    rationale: str
    report: str
    seg_index: int
    char_start: int
    char_end: int
    standard_name: str | None = None


@dataclass(frozen=True)
class ValidatedAddressesFunction:
    """A validated, admissible ``msr:addressesFunction`` relation.

    ``Requirement -> SafetyFunction`` (design.md D4, chunk 11 task 4.2).
    Because a ``SafetyFunction`` is grown, not seeded, this only validates
    once the safety branch has been approved into core (D4's two-phase
    ordering). ``standard_name`` is task 4.4's optional named IAEA standard
    for this ``Requirement``. ``threshold_value``/``threshold_comparator``/
    ``threshold_unit`` are task 4.5's optional soft threshold (design.md
    D5) -- ``None`` unless the source states a numeric threshold, and never
    a SHACL constraint.
    """

    requirement_iri: str
    safety_function_iri: str
    confidence: float
    rationale: str
    report: str
    seg_index: int
    char_start: int
    char_end: int
    standard_name: str | None = None
    threshold_value: float | None = None
    threshold_comparator: str | None = None
    threshold_unit: str | None = None


@dataclass(frozen=True)
class RelationRecord:
    """One line in the ``relations.jsonl`` trace -- every proposed relation."""

    report: str
    seg_index: int
    char_start: int
    char_end: int
    relation_kind: str  # "measurement" | "role" | "reactor" | "servedByProperty" | "addressesFunction" | "unknown"
    salt_iri: str | None
    property_iri: str | None
    role_iri: str | None
    reactor_iri: str | None
    unit_iri: str | None
    confidence: float | None
    rationale: str | None
    disposition: Literal["written", "rejected", "skipped"]
    reason: str  # "" for written; else the reject/skip reason
    # Chunk 11 (ingest-iaea-safety D4) -- the safety linking relations'
    # subject/target IRIs. Defaulted to None so every existing chemistry
    # record construction (measurement/role/reactor) is unaffected.
    safety_function_iri: str | None = None
    requirement_iri: str | None = None


@dataclass(frozen=True)
class ReportExtraction:
    """The full result of :func:`extract_report` for one report."""

    measurements: list[ValidatedMeasurement]
    roles: list[ValidatedRole]
    reactors: list[ValidatedReactor]
    records: list[RelationRecord]
    sentences_seen: int
    malformed_calls: int
    # Chunk 11 (ingest-iaea-safety D4) -- the safety genre's linking
    # relations. Empty by default (``field(default_factory=list)``) so the
    # chemistry-genre construction in extract_report is unaffected.
    served_by_property: list[ValidatedServedByProperty] = field(default_factory=list)
    addresses_function: list[ValidatedAddressesFunction] = field(default_factory=list)


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


def select_sentences(
    report: str, config: Config, *, genre: Literal["chemistry", "safety"] = "chemistry"
) -> list[SelectedSentence]:
    """Select the report's Flash-eligible sentences (design.md D2).

    Reads ``config.segments_path(report)`` and ``config.mentions_path(report)``
    and returns one :class:`SelectedSentence` per segment that carries at
    least one ``status:"linked"`` mention (``mention.seg_index ==
    segment.index``) -- a segment with no linked mention is excluded
    entirely, so it never triggers a Flash call. Results are ordered by
    ``seg_index`` for determinism.

    ``genre`` (chunk 11, ingest-iaea-safety D8) selects which of the two
    parallel artifact layouts to read: the default ``"chemistry"`` reads
    ``config.segments_path``/``config.mentions_path`` (the chunk-5/6
    corpus layout); ``"safety"`` reads ``config.safety_segments_path``/
    ``config.safety_mentions_path`` instead, so the safety genre is "just
    another corpus" downstream (design.md D1) without touching a single
    line of this function's selection logic.
    """
    if genre == "safety":
        segments = _read_jsonl(config.safety_segments_path(report))
        mentions = _read_jsonl(config.safety_mentions_path(report))
    else:
        segments = _read_jsonl(config.segments_path(report))
        mentions = _read_jsonl(config.mentions_path(report))

    linked_by_seg: dict[int, list[LinkedMention]] = {}
    for mention in mentions:
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


def build_user_prompt(
    sentence: SelectedSentence,
    role_iris: Iterable[str] = (),
    *,
    safety_function_iris: Iterable[str] = (),
    requirement_iris: Iterable[str] = (),
) -> str:
    """Build the per-sentence user prompt appended to the cached KG-schema prefix.

    Identifies the sentence's already-linked entities (surface form,
    target IRI, kind) on top of the cached prefix's full known-entity
    serialization, and instructs the model to propose zero or more
    relations using IRIs from the known entities above -- never a new
    one. Includes the literal word "json" and a shape example, mirroring
    ``disambiguation._build_user_prompt`` (a DeepSeek JSON-output-mode
    requirement).

    ``role_iris`` are the seed ``msr:SaltRole`` individual IRIs. They are
    listed explicitly here (the per-sentence prompt) rather than in the
    cached KG-schema prefix, because that prefix is built from chunk-6's
    byte-stable ``read_known_entities()`` (concepts/classes/salts only, no
    role individuals) and is shared with NER seeding. Without this block the
    model never sees the valid role IRIs and every ``role`` proposal fails
    the closed-set ``unknown-role`` check; listing them here lets the model
    emit an exact seed role IRI while leaving the cached prefix untouched.
    Empty by default so callers that don't extract roles are unaffected.

    ``safety_function_iris``/``requirement_iris`` (chunk 11, ingest-iaea-safety
    D4, task 4.1/4.2) are the grown ``msr:SafetyFunction``/``msr:Requirement``
    individual IRIs -- listed here for the identical reason ``role_iris`` is:
    they are not seed vocabulary/ontology classes/salts, so
    ``read_known_entities()`` never surfaces them, and the safety linking
    edges' closed-set validation (:func:`validate_relation`) only resolves
    once the caller populates :class:`KnownSets` from a post-approval read
    (design.md D4's two-phase ordering). Both empty by default so every
    chemistry-genre caller is unaffected and sees the original prompt
    byte-for-byte.

    The precision guard for ``servedByProperty``/``addressesFunction`` --
    "co-mention is not a dependency" -- is enforced here, in the
    instructions below, not by any app-side heuristic: a stubbed/real Flash
    that merely sees a safety function and a property named in the same
    sentence, with no stated reliance between them, is told to emit nothing
    for that pair, so :func:`validate_relation` never even receives a
    payload to reject for that case.
    """
    mentions_block = "\n".join(
        f'  - "{m.surface_form}" -> {m.target_iri} ({m.target_kind})'
        for m in sentence.linked_mentions
    )
    roles_sorted = sorted(role_iris)
    roles_block = (
        (
            'Valid salt-role IRIs (a "role" relation\'s "role" value MUST be '
            "exactly one of these -- they are seed individuals, NOT in the "
            "mention list above):\n"
            + "\n".join(f"  - {iri}" for iri in roles_sorted)
            + "\n\n"
        )
        if roles_sorted
        else ""
    )

    safety_functions_sorted = sorted(safety_function_iris)
    requirements_sorted = sorted(requirement_iris)
    safety_block = ""
    if safety_functions_sorted or requirements_sorted:
        safety_lines = []
        if safety_functions_sorted:
            safety_lines.append(
                'Valid msr:SafetyFunction IRIs (a "servedByProperty" relation\'s '
                '"safety_function" value, or an "addressesFunction" relation\'s '
                '"safety_function" value, MUST be exactly one of these):\n'
                + "\n".join(f"  - {iri}" for iri in safety_functions_sorted)
            )
        if requirements_sorted:
            safety_lines.append(
                'Valid msr:Requirement IRIs (an "addressesFunction" relation\'s '
                '"requirement" value MUST be exactly one of these):\n'
                + "\n".join(f"  - {iri}" for iri in requirements_sorted)
            )
        safety_block = "\n".join(safety_lines) + "\n\n"

    return (
        "Extract property-measurement, salt-role, salt-reactor, "
        "safety-function-served-by-property, and "
        "requirement-addresses-function relations from the following "
        "sentence, using only IRIs from the known entities and this "
        "sentence's already-linked mentions above -- never invent a new "
        "IRI.\n\n"
        "Only propose a \"servedByProperty\" relation when the sentence "
        "explicitly states that the safety function depends on, is served "
        "by, or requires the property -- a sentence that merely names both "
        "a safety function and a property in the same breath, with no "
        "stated dependency between them, asserts NO relation for that pair "
        "(co-mention is not a dependency). The same rule applies to "
        "\"addressesFunction\": only propose it when the sentence states "
        "that the requirement addresses/serves the safety function.\n\n"
        f"{roles_block}"
        f"{safety_block}"
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
        '"confidence": 0.9, "rationale": "..."},\n'
        '    {"kind": "servedByProperty", "safety_function": "<IRI>", '
        '"property": "<IRI>", "confidence": 0.9, "rationale": "...", '
        '"standard": null},\n'
        '    {"kind": "addressesFunction", "requirement": "<IRI>", '
        '"safety_function": "<IRI>", "confidence": 0.85, '
        '"rationale": "...", "standard": null, "threshold_value": null, '
        '"threshold_comparator": null, "threshold_unit": null}\n'
        "  ]}\n\n"
        "\"standard\" is the named IAEA standard identifier (e.g. "
        "\"IAEA SSR-2/1\") backing a servedByProperty/addressesFunction "
        "relation's subject, only when the sentence names one, else null. "
        "\"threshold_value\"/\"threshold_comparator\" "
        "(one of \"lt\"/\"lte\"/\"gt\"/\"gte\")/\"threshold_unit\" are only "
        "set on an addressesFunction relation when the sentence states a "
        "numeric threshold for the requirement, else null.\n\n"
        "If the sentence asserts no relation, return {\"relations\": []}. "
        "Return only the json object, no other text."
    )


def extract_relations(
    sentence: SelectedSentence,
    prompt_prefix: str,
    client: Completer,
    role_iris: Iterable[str] = (),
    *,
    safety_function_iris: Iterable[str] = (),
    requirement_iris: Iterable[str] = (),
) -> tuple[list[dict], bool]:
    """Call Flash for one sentence and return its proposed relations, or ([], False).

    Calls ``client.complete(prompt_prefix, build_user_prompt(sentence,
    role_iris, safety_function_iris=..., requirement_iris=...))``, parses
    the reply as JSON, and pulls ``obj["relations"]``. ``role_iris`` (the
    seed ``msr:SaltRole`` IRIs) are surfaced to the model via the user
    prompt so it can propose valid role relations; ``safety_function_iris``/
    ``requirement_iris`` (chunk 11) do the same for the two safety linking
    relations. Never raises: a client exception, malformed JSON, a non-dict
    payload, or a missing/non-list ``"relations"`` all yield ``([], False)``.
    """
    user_prompt = build_user_prompt(
        sentence,
        role_iris,
        safety_function_iris=safety_function_iris,
        requirement_iris=requirement_iris,
    )

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
    so this module never raises on a malformed proposed relation. Also
    rejects non-finite results (``NaN``/``Infinity``/``-Infinity``) --
    ``json.loads`` parses those bare tokens into ``float('nan')``/
    ``float('inf')`` without raising, and a non-finite coefficient/value/
    temperature must not silently reach :func:`msr_extraction.equations.
    parse_correlation` or an emitted Turtle literal.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
    elif isinstance(value, str):
        try:
            f = float(value)
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(f):
        return None
    return f


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


# Chunk 11 (ingest-iaea-safety D5) -- the closed comparator vocabulary a
# stated Requirement threshold's "threshold_comparator" must be exactly one
# of. Pinned exactly, mirroring the reason-string constants above.
_VALID_THRESHOLD_COMPARATORS = frozenset({"lt", "lte", "gt", "gte"})


def _to_standard_name(value: object) -> str | None:
    """Best-effort coercion of a proposed ``"standard"`` field.

    ``None`` unless ``value`` is a non-empty string -- task 4.4's
    ``rdfs:seeAlso`` alignment is opportunistic (only when the source text
    actually names a standard), so anything else (missing field, ``null``,
    an empty string, a non-string) means "no standard named."
    """
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _to_threshold(raw: dict) -> tuple[float | None, str | None, str | None]:
    """Best-effort coercion of a proposed Requirement threshold (design.md D5).

    Returns ``(threshold_value, threshold_comparator, threshold_unit)``.
    Task 4.5's threshold is extracted only when the source states one, so
    this only returns a non-``None`` triple when BOTH a numeric
    ``"threshold_value"`` AND a ``"threshold_comparator"`` from
    :data:`_VALID_THRESHOLD_COMPARATORS` are present -- a value with no (or
    an invalid) comparator is ambiguous (``lt`` vs ``gt`` 500 °C reads
    oppositely) and is dropped entirely rather than guessed.
    ``threshold_unit`` is optional even then (``None`` if absent/blank).
    """
    threshold_value = _to_float(raw.get("threshold_value"))
    raw_comparator = raw.get("threshold_comparator")
    threshold_comparator = (
        raw_comparator
        if isinstance(raw_comparator, str)
        and raw_comparator in _VALID_THRESHOLD_COMPARATORS
        else None
    )
    if threshold_value is None or threshold_comparator is None:
        return None, None, None

    raw_unit = raw.get("threshold_unit")
    threshold_unit = (
        raw_unit if isinstance(raw_unit, str) and raw_unit.strip() else None
    )
    return threshold_value, threshold_comparator, threshold_unit


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
        safety_function_iri: str | None = None,
        requirement_iri: str | None = None,
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
            safety_function_iri=safety_function_iri,
            requirement_iri=requirement_iri,
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
        # A non-finite (NaN/Infinity) or out-of-range confidence must never
        # bypass the threshold gate below -- json.loads parses the bare
        # tokens "NaN"/"Infinity"/"-Infinity" into non-finite floats without
        # raising, and NaN < threshold is always False while inf is never
        # < threshold, so either would otherwise slip a relation through as
        # "written" regardless of the configured threshold.
        if not math.isfinite(confidence) or confidence < 0.0 or confidence > 1.0:
            confidence = 0.0

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

    # 5. kind == "servedByProperty" (chunk 11, ingest-iaea-safety D4, task 4.1)
    if kind == "servedByProperty":
        safety_function_raw = raw.get("safety_function")
        property_raw = raw.get("property")
        if not isinstance(safety_function_raw, str) or not isinstance(
            property_raw, str
        ):
            return None, _record(
                "unknown",
                "rejected",
                REASON_MALFORMED_RELATION,
                confidence=confidence,
                rationale=rationale,
            )

        # Closed-set validation (design.md D4): both the SafetyFunction
        # subject and the PhysicalProperty target must already be in core.
        # A SafetyFunction is grown, not seeded, so this rejects until the
        # safety branch has been mined + approved (the caller's KnownSets
        # stays empty until then) -- the two-phase ordering the spec pins.
        if safety_function_raw not in known.safety_functions:
            return None, _record(
                "servedByProperty",
                "rejected",
                REASON_UNKNOWN_SAFETY_FUNCTION,
                safety_function_iri=safety_function_raw,
                property_iri=property_raw,
                confidence=confidence,
                rationale=rationale,
            )

        if property_raw not in known.physical_properties:
            return None, _record(
                "servedByProperty",
                "rejected",
                REASON_UNKNOWN_PROPERTY,
                safety_function_iri=safety_function_raw,
                property_iri=property_raw,
                confidence=confidence,
                rationale=rationale,
            )

        served_by_property = ValidatedServedByProperty(
            safety_function_iri=safety_function_raw,
            property_iri=property_raw,
            confidence=confidence,
            rationale=rationale,
            report=sentence.report,
            seg_index=sentence.seg_index,
            char_start=sentence.char_start,
            char_end=sentence.char_end,
            standard_name=_to_standard_name(raw.get("standard")),
        )
        return served_by_property, _record(
            "servedByProperty",
            "written",
            "",
            safety_function_iri=safety_function_raw,
            property_iri=property_raw,
            confidence=confidence,
            rationale=rationale,
        )

    # 6. kind == "addressesFunction" (chunk 11, ingest-iaea-safety D4, task 4.2)
    if kind == "addressesFunction":
        requirement_raw = raw.get("requirement")
        safety_function_raw = raw.get("safety_function")
        if not isinstance(requirement_raw, str) or not isinstance(
            safety_function_raw, str
        ):
            return None, _record(
                "unknown",
                "rejected",
                REASON_MALFORMED_RELATION,
                confidence=confidence,
                rationale=rationale,
            )

        # Both referents are grown, not seeded (design.md D4): this only
        # validates once the safety branch's Requirement/SafetyFunction
        # individuals have been mined + approved into core.
        if requirement_raw not in known.requirements:
            return None, _record(
                "addressesFunction",
                "rejected",
                REASON_UNKNOWN_REQUIREMENT,
                requirement_iri=requirement_raw,
                safety_function_iri=safety_function_raw,
                confidence=confidence,
                rationale=rationale,
            )

        if safety_function_raw not in known.safety_functions:
            return None, _record(
                "addressesFunction",
                "rejected",
                REASON_UNKNOWN_SAFETY_FUNCTION,
                requirement_iri=requirement_raw,
                safety_function_iri=safety_function_raw,
                confidence=confidence,
                rationale=rationale,
            )

        threshold_value, threshold_comparator, threshold_unit = (
            _to_threshold(raw)
        )

        addresses_function = ValidatedAddressesFunction(
            requirement_iri=requirement_raw,
            safety_function_iri=safety_function_raw,
            confidence=confidence,
            rationale=rationale,
            report=sentence.report,
            seg_index=sentence.seg_index,
            char_start=sentence.char_start,
            char_end=sentence.char_end,
            standard_name=_to_standard_name(raw.get("standard")),
            threshold_value=threshold_value,
            threshold_comparator=threshold_comparator,
            threshold_unit=threshold_unit,
        )
        return addresses_function, _record(
            "addressesFunction",
            "written",
            "",
            requirement_iri=requirement_raw,
            safety_function_iri=safety_function_raw,
            confidence=confidence,
            rationale=rationale,
        )

    # 7. Unknown/missing kind.
    return None, _record(
        "unknown",
        "rejected",
        REASON_MALFORMED_RELATION,
        confidence=confidence,
        rationale=rationale,
    )


def write_relations_jsonl(
    report: str,
    records: list[RelationRecord],
    config: Config,
    *,
    genre: Literal["chemistry", "safety"] = "chemistry",
) -> None:
    """Write ``config.relations_path(report)``: one JSON object per record.

    Deterministic given deterministic input ordering (design.md D8-style
    "regenerated wholesale per run"). UTF-8, ``ensure_ascii=False``, one
    object per line, keys in the artifact's documented order -- mirrors
    ``linker.write_mentions_jsonl``.

    ``genre`` (chunk 11, ingest-iaea-safety D8) selects the trace path:
    ``"safety"`` writes ``config.safety_relations_path(report)`` instead of
    the chemistry-genre default ``config.relations_path(report)``.
    """
    path = (
        config.safety_relations_path(report)
        if genre == "safety"
        else config.relations_path(report)
    )
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
                "safety_function_iri": record.safety_function_iri,
                "requirement_iri": record.requirement_iri,
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
    concurrency: int = 1,
    *,
    genre: Literal["chemistry", "safety"] = "chemistry",
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

    ``concurrency`` bounds a thread pool that fans out only the per-sentence
    Flash calls (:func:`extract_relations`, a blocking network call) --
    mirroring ``cli._cmd_link``'s layer-5 disambiguation fan-out. Every
    other step (validation, dedup, trace writing) stays on the main thread
    and iterates the per-sentence results in the original ``seg_index``
    order, so output is byte-identical to the sequential path regardless of
    ``concurrency``. ``concurrency <= 1`` (the default) skips the executor
    entirely, keeping existing callers/tests deterministic and unchanged.

    ``genre`` (chunk 11, ingest-iaea-safety D8) is keyword-only and
    defaults to ``"chemistry"`` -- every existing caller/test is therefore
    unaffected byte-for-byte. ``genre="safety"`` reads segments/mentions
    via :func:`select_sentences`'s ``config.safety_segments_path``/
    ``config.safety_mentions_path``, surfaces ``known.safety_functions``/
    ``known.requirements`` to the model via :func:`extract_relations`
    (so it can propose valid ``servedByProperty``/``addressesFunction``
    edges once the safety branch is in core), and writes the trace to
    ``config.safety_relations_path(report)``.
    """
    sentences = select_sentences(report, config, genre=genre)

    measurements: list[ValidatedMeasurement] = []
    roles: list[ValidatedRole] = []
    reactors: list[ValidatedReactor] = []
    served_by_property: list[ValidatedServedByProperty] = []
    addresses_function: list[ValidatedAddressesFunction] = []
    records: list[RelationRecord] = []
    # Parallel to measurements/roles/reactors/served_by_property/
    # addresses_function: the index into ``records`` of the "written"
    # RelationRecord each payload came from, so a payload dropped as an
    # in-run duplicate (below) can flip its own record to "skipped"/
    # "duplicate-locator" without disturbing any other record.
    measurement_record_idx: list[int] = []
    role_record_idx: list[int] = []
    reactor_record_idx: list[int] = []
    served_by_property_record_idx: list[int] = []
    addresses_function_record_idx: list[int] = []
    malformed_calls = 0

    role_iris = tuple(sorted(known.salt_roles))
    safety_function_iris = tuple(sorted(known.safety_functions))
    requirement_iris = tuple(sorted(known.requirements))

    def _call(sentence: SelectedSentence) -> tuple[list[dict], bool]:
        try:
            return extract_relations(
                sentence,
                prompt_prefix,
                client,
                role_iris,
                safety_function_iris=safety_function_iris,
                requirement_iris=requirement_iris,
            )
        except Exception:
            # extract_relations never raises by contract, but a worker
            # future must never crash the run either way.
            return [], False

    if concurrency > 1 and sentences:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            # executor.map preserves input order, so zipping it back onto
            # ``sentences`` reproduces the exact sequential ordering below.
            call_results = list(executor.map(_call, sentences))
    else:
        call_results = [_call(sentence) for sentence in sentences]

    for sentence, (raw_relations, ok) in zip(sentences, call_results):
        if not ok:
            malformed_calls += 1
            continue

        for raw in raw_relations:
            payload, record = validate_relation(
                raw, sentence, known, unit_mapper, config.confidence_threshold
            )
            records.append(record)
            record_idx = len(records) - 1
            if isinstance(payload, ValidatedMeasurement):
                measurements.append(payload)
                measurement_record_idx.append(record_idx)
            elif isinstance(payload, ValidatedRole):
                roles.append(payload)
                role_record_idx.append(record_idx)
            elif isinstance(payload, ValidatedReactor):
                reactors.append(payload)
                reactor_record_idx.append(record_idx)
            elif isinstance(payload, ValidatedServedByProperty):
                served_by_property.append(payload)
                served_by_property_record_idx.append(record_idx)
            elif isinstance(payload, ValidatedAddressesFunction):
                addresses_function.append(payload)
                addresses_function_record_idx.append(record_idx)

    measurements, dropped = _dedupe_by_key(
        measurements,
        measurement_record_idx,
        key_fn=lambda m: (m.report, m.property_name, m.salt_iri),
    )
    for idx in dropped:
        records[idx] = replace(
            records[idx], disposition="skipped", reason=REASON_DUPLICATE_LOCATOR
        )

    roles, dropped = _dedupe_by_key(
        roles,
        role_record_idx,
        key_fn=lambda r: (r.report, r.salt_iri, r.role_iri),
    )
    for idx in dropped:
        records[idx] = replace(
            records[idx], disposition="skipped", reason=REASON_DUPLICATE_LOCATOR
        )

    reactors, dropped = _dedupe_by_key(
        reactors,
        reactor_record_idx,
        key_fn=lambda r: (
            r.report,
            r.salt_iri,
            _reactor_slugify(r.reactor_label).lower(),
        ),
    )
    for idx in dropped:
        records[idx] = replace(
            records[idx], disposition="skipped", reason=REASON_DUPLICATE_LOCATOR
        )

    served_by_property, dropped = _dedupe_by_key(
        served_by_property,
        served_by_property_record_idx,
        key_fn=lambda r: (r.report, r.safety_function_iri, r.property_iri),
    )
    for idx in dropped:
        records[idx] = replace(
            records[idx], disposition="skipped", reason=REASON_DUPLICATE_LOCATOR
        )

    addresses_function, dropped = _dedupe_by_key(
        addresses_function,
        addresses_function_record_idx,
        key_fn=lambda r: (r.report, r.requirement_iri, r.safety_function_iri),
    )
    for idx in dropped:
        records[idx] = replace(
            records[idx], disposition="skipped", reason=REASON_DUPLICATE_LOCATOR
        )

    write_relations_jsonl(report, records, config, genre=genre)

    return ReportExtraction(
        measurements=measurements,
        roles=roles,
        reactors=reactors,
        records=records,
        sentences_seen=len(sentences),
        malformed_calls=malformed_calls,
        served_by_property=served_by_property,
        addresses_function=addresses_function,
    )


def _dedupe_by_key(payloads, record_indices, *, key_fn):
    """Keep only the highest-confidence payload per :func:`key_fn` key.

    Used by :func:`extract_report` to dedupe validated measurements/roles/
    reactors that resolve to the same deterministic target subject within
    one report (two different sentences can validate to the same
    ``(report, property_name, salt_iri)``/``(report, salt_iri, role_iri)``/
    ``(report, salt_iri, reactor_slug)`` locator). Ties are broken
    deterministically by earliest ``seg_index``, then ``char_start``.

    Returns ``(kept_payloads, dropped_record_indices)`` -- ``kept_payloads``
    preserves the original relative order of the surviving items;
    ``dropped_record_indices`` is the (arbitrary-order) list of
    ``record_indices`` entries for every payload that lost its key's
    contest, for the caller to flip the corresponding ``RelationRecord``.
    """
    groups: dict[object, list[int]] = {}
    for i, payload in enumerate(payloads):
        groups.setdefault(key_fn(payload), []).append(i)

    keep_positions: set[int] = set()
    dropped_record_indices: list[int] = []
    for positions in groups.values():
        best = min(
            positions,
            key=lambda i: (
                -payloads[i].confidence,
                payloads[i].seg_index,
                payloads[i].char_start,
            ),
        )
        keep_positions.add(best)
        for i in positions:
            if i != best:
                dropped_record_indices.append(record_indices[i])

    kept_payloads = [payloads[i] for i in range(len(payloads)) if i in keep_positions]
    return kept_payloads, dropped_record_indices
