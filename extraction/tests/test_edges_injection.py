"""``standard_iri`` SPARQL/Turtle injection guard tests (chunk 11 review
fix, hardening).

``ServedByEdge.standard_name``/``AddressesFunctionEdge.standard_name``
(``ValidatedServedByProperty.standard_name``/
``ValidatedAddressesFunction.standard_name`` upstream) is LLM-derived free
text naming an IAEA standard, with no charset restriction. Prior to this
fix, ``edges.standard_iri`` returned ``f"msrd:{slugify(name)}"`` and
``slugify`` only *replaces* a fixed punctuation set (space, ``/``, ``#``,
``|``, ``=``, ``@``) -- it does not neutralize SPARQL/Turtle metacharacters
such as ``< > " { } ;``, a backslash, or a raw newline. The result is
interpolated *unquoted* into an ``INSERT DATA`` CURIE
(``{subject} rdfs:seeAlso {standard} .``), so a crafted ``standard_name``
could break out of the CURIE and inject arbitrary SPARQL/Turtle into the
update body.

Mirrors ``test_edges_slug_guard.py``'s pattern for the structurally
identical ``reactor_slug``/``reactor_iri`` case: pins that
``edges.standard_iri`` now passes its slug through
``edges._safe_reactor_slug`` on top of ``edges.slugify``, restricting the
local name to ``[a-z0-9-]``, and returns ``None`` (rather than minting a
degenerate ``msrd:`` IRI) when the sanitized result is empty -- callers
must skip emitting the ``rdfs:seeAlso`` block in that case.
"""

from __future__ import annotations

import re

from msr_extraction.edges import (
    AddressesFunctionEdge,
    ServedByEdge,
    addresses_function_edge_triples,
    served_by_edge_triples,
    standard_iri,
)

REPORT = "GIF-Holcomb-MSR-safety"
DOCUMENT_IRI = "https://w3id.org/msr-kg/data#GIF-Holcomb-MSR-safety"
SAFETY_FUNCTION = "https://w3id.org/msr-kg/data#sf-heat-removal"
REQUIREMENT = "https://w3id.org/msr-kg/data#requirement-coolant-selection"
SPECIFIC_HEAT = "https://w3id.org/msr-kg/ontology#specificHeat"

# A standard name carrying every character this guard must strip: quote,
# curly braces, semicolon, angle brackets, backslash, a space, and a raw
# newline -- enough to close the surrounding INSERT DATA block and splice
# in an extra SPARQL update if left unsanitized.
EVIL_STANDARD_NAME = 'IAEA SSR-2/1"} ;\nDROP GRAPH <urn:msr:data> ;\nINSERT DATA { <http://evil/> a <http://evil/Pwned> \\ {x'

# A standard name that is entirely metacharacters/whitespace: sanitizes to
# an empty local name.
EMPTY_AFTER_SANITIZE = '{ } ; < > " \\'


def test_standard_iri_is_unchanged_in_shape_for_a_legitimate_name() -> None:
    result = standard_iri("IAEA SSR-2/1")
    assert result == "msrd:iaea-ssr-2-1"


def test_standard_iri_sanitizes_a_malicious_name_to_the_safe_charset() -> None:
    result = standard_iri(EVIL_STANDARD_NAME)
    assert result is not None
    local_name = result.split(":", 1)[1]
    assert re.fullmatch(r"[a-z0-9-]+", local_name), result


def test_standard_iri_output_never_contains_turtle_breaking_characters() -> None:
    result = standard_iri(EVIL_STANDARD_NAME)
    assert result is not None
    for forbidden in ("<", ">", '"', "{", "}", ";", "\\", " ", "\n"):
        assert forbidden not in result


def test_standard_iri_returns_none_when_sanitized_result_is_empty() -> None:
    assert standard_iri(EMPTY_AFTER_SANITIZE) is None


def test_served_by_edge_triples_with_malicious_standard_name_leaks_no_breakout() -> None:
    edge = ServedByEdge(
        safety_function_iri=SAFETY_FUNCTION,
        property_iri=SPECIFIC_HEAT,
        report=REPORT,
        document_iri=DOCUMENT_IRI,
        confidence=0.9,
        rationale="heat capacity is cited as needed for natural circulation cooling",
        standard_name=EVIL_STANDARD_NAME,
    )

    block = served_by_edge_triples(edge)

    # The minted standard IRI is the injection vector this fix closes: its
    # CURIE token must be the sanitized, safe-charset form, and the line
    # that mints it (the `rdfs:seeAlso` triple) must carry no breakout
    # character. (The evil name's raw text also appears inside the
    # separately-escaped `rdfs:label` string literal further down --
    # that's `_escape_literal`'s pre-existing, unrelated guarantee, not
    # what this test is pinning.)
    sanitized = standard_iri(EVIL_STANDARD_NAME)
    assert sanitized is not None
    assert sanitized in block
    see_also_line = next(line for line in block.splitlines() if "rdfs:seeAlso" in line)
    assert see_also_line == f"msrd:sf-heat-removal rdfs:seeAlso {sanitized} ."
    for forbidden in ("<", ">", '"', "{", "}", ";", "\\", "\n"):
        assert forbidden not in see_also_line


def test_served_by_edge_triples_skips_see_also_when_standard_name_sanitizes_empty() -> None:
    kwargs = dict(
        safety_function_iri=SAFETY_FUNCTION,
        property_iri=SPECIFIC_HEAT,
        report=REPORT,
        document_iri=DOCUMENT_IRI,
        confidence=0.9,
        rationale="heat capacity is cited as needed for natural circulation cooling",
    )
    edge_with_junk_standard = ServedByEdge(**kwargs, standard_name=EMPTY_AFTER_SANITIZE)
    edge_without_standard = ServedByEdge(**kwargs, standard_name=None)

    block = served_by_edge_triples(edge_with_junk_standard)

    assert "rdfs:seeAlso" not in block
    # A sanitize-to-empty standard name must produce the exact same block
    # as no standard name at all -- no degenerate msrd: IRI is minted.
    assert block == served_by_edge_triples(edge_without_standard)


def test_addresses_function_edge_triples_with_malicious_standard_name_leaks_no_breakout() -> None:
    edge = AddressesFunctionEdge(
        requirement_iri=REQUIREMENT,
        safety_function_iri=SAFETY_FUNCTION,
        report=REPORT,
        document_iri=DOCUMENT_IRI,
        confidence=0.85,
        rationale="the coolant-selection requirement is stated to serve heat removal",
        standard_name=EVIL_STANDARD_NAME,
    )

    block = addresses_function_edge_triples(edge)

    sanitized = standard_iri(EVIL_STANDARD_NAME)
    assert sanitized is not None
    assert sanitized in block
    see_also_line = next(line for line in block.splitlines() if "rdfs:seeAlso" in line)
    assert see_also_line == f"msrd:requirement-coolant-selection rdfs:seeAlso {sanitized} ."
    for forbidden in ("<", ">", '"', "{", "}", ";", "\\", "\n"):
        assert forbidden not in see_also_line


def test_addresses_function_edge_triples_skips_see_also_when_standard_name_sanitizes_empty() -> None:
    kwargs = dict(
        requirement_iri=REQUIREMENT,
        safety_function_iri=SAFETY_FUNCTION,
        report=REPORT,
        document_iri=DOCUMENT_IRI,
        confidence=0.85,
        rationale="the coolant-selection requirement is stated to serve heat removal",
    )
    edge_with_junk_standard = AddressesFunctionEdge(**kwargs, standard_name=EMPTY_AFTER_SANITIZE)
    edge_without_standard = AddressesFunctionEdge(**kwargs, standard_name=None)

    block = addresses_function_edge_triples(edge_with_junk_standard)

    assert "rdfs:seeAlso" not in block
    assert block == addresses_function_edge_triples(edge_without_standard)
