"""Disambiguation tests (task 10.5, design.md D5/D10).

Covers the DeepSeek V4 Flash disambiguation layer: valid-IRI accept,
unknown-IRI reject -> novel, explicit novel declaration, and malformed JSON
-> novel. Every test uses a stub :class:`~msr_extraction.disambiguation.Completer`
implementation and never contacts a live model.
"""

from __future__ import annotations

from msr_extraction.config import Config
from msr_extraction.disambiguation import Disambiguation, FlashClient, disambiguate

KNOWN_IRIS = {"msrd:salt-BeF2-LiF-34.0-66.0", "voc:flibe", "voc:viscosity"}

SURFACE = "FLiBe"
SENTENCE = "The FLiBe coolant salt exhibits low viscosity at operating temperature."
PROMPT_PREFIX = "cached KG-schema prompt prefix"


class StubCompleter:
    """A stub :class:`Completer` returning a fixed canned response."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        return self.response


def test_valid_iri_in_known_set_is_linked() -> None:
    stub = StubCompleter('{"link": "voc:flibe"}')

    result = disambiguate(SURFACE, SENTENCE, PROMPT_PREFIX, KNOWN_IRIS, stub)

    assert result == Disambiguation("linked", "voc:flibe")
    # The prompt prefix is forwarded as the system prompt unchanged.
    assert stub.calls[0][0] == PROMPT_PREFIX
    assert "json" in stub.calls[0][1].lower()


def test_unknown_iri_is_rejected_as_novel() -> None:
    stub = StubCompleter('{"link": "voc:not-a-real-concept"}')

    result = disambiguate(SURFACE, SENTENCE, PROMPT_PREFIX, KNOWN_IRIS, stub)

    assert result == Disambiguation("novel", None)


def test_explicit_novel_declaration() -> None:
    stub = StubCompleter('{"novel": true}')

    result = disambiguate(SURFACE, SENTENCE, PROMPT_PREFIX, KNOWN_IRIS, stub)

    assert result == Disambiguation("novel", None)


def test_malformed_json_is_treated_as_novel() -> None:
    stub = StubCompleter("this is not json at all")

    result = disambiguate(SURFACE, SENTENCE, PROMPT_PREFIX, KNOWN_IRIS, stub)

    assert result == Disambiguation("novel", None)


def test_non_object_json_is_treated_as_novel() -> None:
    stub = StubCompleter('["link", "voc:flibe"]')

    result = disambiguate(SURFACE, SENTENCE, PROMPT_PREFIX, KNOWN_IRIS, stub)

    assert result == Disambiguation("novel", None)


def test_missing_expected_keys_is_treated_as_novel() -> None:
    stub = StubCompleter('{"unexpected": "shape"}')

    result = disambiguate(SURFACE, SENTENCE, PROMPT_PREFIX, KNOWN_IRIS, stub)

    assert result == Disambiguation("novel", None)


def test_completer_raising_is_treated_as_novel() -> None:
    class RaisingCompleter:
        def complete(self, system_prompt: str, user_prompt: str) -> str:
            raise RuntimeError("network error")

    result = disambiguate(SURFACE, SENTENCE, PROMPT_PREFIX, KNOWN_IRIS, RaisingCompleter())

    assert result == Disambiguation("novel", None)


def test_from_config_returns_none_when_deepseek_base_url_empty() -> None:
    config = Config(deepseek_base_url="")

    assert FlashClient.from_config(config) is None


def test_from_config_returns_client_when_deepseek_base_url_set() -> None:
    config = Config(
        deepseek_base_url="https://api.deepseek.example",
        llm_model_extract="deepseek-v4-flash",
    )

    client = FlashClient.from_config(config)

    assert client is not None
    assert client.base_url == "https://api.deepseek.example"
    assert client.model == "deepseek-v4-flash"
    # No key configured -> None, so `complete` falls back to "unused" against
    # a keyless/compatible endpoint.
    assert client.api_key is None


def test_from_config_threads_configured_api_key_onto_client() -> None:
    config = Config(
        deepseek_base_url="https://api.deepseek.example",
        llm_model_extract="deepseek-v4-flash",
        deepseek_api_key="sk-test-secret",
    )

    client = FlashClient.from_config(config)

    assert client is not None
    assert client.api_key == "sk-test-secret"
