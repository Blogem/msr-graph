"""The seed salt-role IRIs are surfaced to Flash via the per-sentence prompt.

Regression test for the roles-came-out-zero finding: the cached KG-schema
prefix (built from chunk-6's byte-stable ``read_known_entities()``) never
lists the ``msr:SaltRole`` individuals, so before this fix the model could
not emit a valid role IRI and every ``role`` proposal failed the closed-set
``unknown-role`` check. ``build_user_prompt`` now injects the role IRIs into
the per-sentence prompt (leaving the cached prefix untouched), and
``extract_relations`` threads them through.
"""

from __future__ import annotations

from msr_extraction.relations import (
    LinkedMention,
    SelectedSentence,
    build_user_prompt,
    extract_relations,
)

ROLES = {
    "https://w3id.org/msr-kg/ontology#FuelSalt",
    "https://w3id.org/msr-kg/ontology#CoolantSalt",
    "https://w3id.org/msr-kg/ontology#FlushSalt",
}


def _sentence() -> SelectedSentence:
    return SelectedSentence(
        report="ORNL-TM-2316",
        seg_index=0,
        char_start=0,
        char_end=10,
        text="FLiBe is the MSRE coolant salt.",
        linked_mentions=[
            LinkedMention(
                surface_form="MSRE",
                target_iri="https://w3id.org/msr-kg/vocab#msre-reactor",
                target_kind="concept",
            )
        ],
    )


def test_prompt_lists_all_seed_role_iris_when_provided() -> None:
    prompt = build_user_prompt(_sentence(), ROLES)
    for iri in ROLES:
        assert iri in prompt
    # Advertised as the allowed values for a role relation's "role".
    assert "salt-role" in prompt.lower()


def test_prompt_role_block_is_deterministic_and_sorted() -> None:
    # Same inputs -> byte-identical prompt (sorted role listing), regardless
    # of set iteration order.
    assert build_user_prompt(_sentence(), ROLES) == build_user_prompt(_sentence(), ROLES)
    prompt = build_user_prompt(_sentence(), ROLES)
    positions = [prompt.index(iri) for iri in sorted(ROLES)]
    assert positions == sorted(positions)  # listed in sorted IRI order


def test_prompt_omits_role_block_when_no_roles_given() -> None:
    # Backward-compatible default: callers that pass no roles get the
    # original prompt with no role-listing block.
    prompt = build_user_prompt(_sentence())
    assert "FuelSalt" not in prompt
    assert "Valid salt-role IRIs" not in prompt


class _StubCompleter:
    """Records the user prompt it was called with; returns an empty relation set."""

    def __init__(self) -> None:
        self.user_prompt: str | None = None

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.user_prompt = user_prompt
        return '{"relations": []}'


def test_extract_relations_threads_role_iris_into_the_prompt() -> None:
    stub = _StubCompleter()
    relations, ok = extract_relations(_sentence(), "cached-prefix", stub, ROLES)
    assert ok is True and relations == []
    assert stub.user_prompt is not None
    for iri in ROLES:
        assert iri in stub.user_prompt
