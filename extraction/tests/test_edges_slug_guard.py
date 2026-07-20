"""Reactor-slug charset guard tests (chunk 7 review fix, hardening).

``ReactorEdge.reactor_slug`` ultimately becomes a bare token inside a
``msrd:reactor-{slug}`` CURIE that gets spliced straight into a Turtle/
SPARQL ``INSERT DATA`` update body (see ``edges.reactor_iri``,
``edges.reactor_edge_triples``, ``edges.insert_data``). Unlike every other
IRI-shaped field this module handles, ``reactor_slug`` is *not* one of the
run's closed-vocabulary IRIs -- design.md/D9 derives it from a chunk-6
linked mention's surface form (a reactor name Flash proposed, grounded by
mention only, not from a fixed allowlist), so a hostile or malformed
surface form could in principle carry characters (``<``, ``>``, ``"``,
``{``, ``}``, ``;``, ``\\``, whitespace) that either break the CURIE's
own syntax or inject extra triples/tokens into the surrounding
``INSERT DATA`` block.

Pins the fix that ``edges.reactor_iri`` sanitizes its input to the
``[a-z0-9-]`` charset (mirroring ``edges.slugify``'s existing
loader-parity posture, but stricter -- ``slugify`` only *replaces* a fixed
punctuation set, it doesn't reject every non-charset character) before
building the ``msrd:reactor-...`` CURIE, so a malicious slug can never
smuggle Turtle-breaking characters into the emitted triples.

Pass-1 note: as merged into this worktree at pass-1 time,
``edges.reactor_iri`` returns ``f"msrd:reactor-{slug}"`` verbatim with no
sanitization, so the malicious-input assertions below are expected to
FAIL until the sibling coder's fix (applied concurrently to ``edges.py``)
merges -- do not weaken them to pass early. The legitimate-input case
(``"msre"``) already passes against the merged code and documents the
guard must be a no-op for well-formed slugs.
"""

from __future__ import annotations

import re

from msr_extraction.edges import ReactorEdge, reactor_edge_triples, reactor_iri

SALT_IRI = "https://w3id.org/msr-kg/data#salt-BeF2-LiF-34.0-66.0"
REACTOR_GROUNDING = "https://w3id.org/msr-kg/vocab#molten-salt-reactors"
REPORT = "ORNL-TM-2316"
DOCUMENT_IRI = "https://w3id.org/msr-kg/data#ORNL-TM-2316"

# A slug carrying every character this guard must strip/reject: quote,
# curly braces, semicolon, angle brackets, backslash, and a space --
# enough to break out of a CURIE token and inject extra triples/clauses
# into an INSERT DATA body if left unsanitized.
EVIL_SLUG = 'msre"} ; DROP <http://evil/> \\ {x'


def test_reactor_iri_is_unchanged_for_a_legitimate_slug() -> None:
    assert reactor_iri("msre") == "msrd:reactor-msre"


def test_reactor_iri_sanitizes_a_malicious_slug_to_the_safe_charset() -> None:
    result = reactor_iri(EVIL_SLUG)

    assert re.fullmatch(r"msrd:reactor-[a-z0-9-]+", result), result


def test_reactor_iri_output_never_contains_turtle_breaking_characters() -> None:
    result = reactor_iri(EVIL_SLUG)

    for forbidden in ("<", ">", '"', "{", "}", ";", "\\", " "):
        assert forbidden not in result


def test_reactor_edge_triples_with_malicious_slug_leaks_no_forbidden_characters() -> None:
    """The minted-reactor token inside the emitted Turtle block must be
    the sanitized form -- none of the evil slug's structural characters
    may leak into the ``msrd:reactor-...`` token itself. (Legitimate ``<`` /
    ``>`` IRI wrappers and quoted string literals elsewhere in the block
    are expected and are not what this test is checking.)"""
    edge = ReactorEdge(
        report=REPORT,
        salt_iri=SALT_IRI,
        reactor_slug=EVIL_SLUG,
        reactor_label="MSRE",
        grounding_concept_iri=REACTOR_GROUNDING,
        document_iri=DOCUMENT_IRI,
        confidence=0.85,
        rationale="the text links BeF2-LiF's use to a maliciously-named reactor",
    )

    block = reactor_edge_triples(edge)
    sanitized = reactor_iri(EVIL_SLUG)

    assert sanitized in block
    # The evil slug's structural characters must not appear anywhere as
    # part of the minted-reactor token's own local name.
    reactor_local_name = sanitized.split(":", 1)[1]
    assert re.fullmatch(r"reactor-[a-z0-9-]+", reactor_local_name)


def test_reactor_edge_triples_still_has_no_blank_nodes_with_malicious_slug() -> None:
    edge = ReactorEdge(
        report=REPORT,
        salt_iri=SALT_IRI,
        reactor_slug=EVIL_SLUG,
        reactor_label="MSRE",
        grounding_concept_iri=REACTOR_GROUNDING,
        document_iri=DOCUMENT_IRI,
        confidence=0.85,
        rationale="the text links BeF2-LiF's use to a maliciously-named reactor",
    )

    block = reactor_edge_triples(edge)

    assert "[" not in block
    assert "_:" not in block
