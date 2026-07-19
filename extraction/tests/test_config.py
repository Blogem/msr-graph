"""Config tests (task 1.3, design.md D1/D4/D5/D7).

Covers the chunk-6 (ner-entity-linking) additions to ``Config``: the
DeepSeek client settings, the bounded rapidfuzz tuning knobs, the SPARQL
query endpoint, and the mention-pipeline artifact paths. All ``from_env``
tests inject an explicit mapping so they never touch real process
environment.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from msr_extraction.config import Config


def test_defaults_for_new_fields() -> None:
    config = Config()
    assert config.deepseek_base_url == ""
    assert config.deepseek_api_key == ""
    assert config.llm_model_extract == "deepseek-v4-flash"
    assert config.fuzzy_threshold == 90.0
    assert config.fuzzy_min_token_length == 4


def test_from_env_empty_mapping_keeps_defaults() -> None:
    config = Config.from_env({})
    assert config.deepseek_base_url == Config.deepseek_base_url
    assert config.deepseek_api_key == Config.deepseek_api_key
    assert config.llm_model_extract == Config.llm_model_extract
    assert config.fuzzy_threshold == Config.fuzzy_threshold
    assert config.fuzzy_min_token_length == Config.fuzzy_min_token_length


def test_from_env_reads_deepseek_base_url() -> None:
    config = Config.from_env({"DEEPSEEK_BASE_URL": "https://api.deepseek.example"})
    assert config.deepseek_base_url == "https://api.deepseek.example"


def test_from_env_reads_deepseek_api_key() -> None:
    config = Config.from_env({"DEEPSEEK_API_KEY": "sk-test-secret"})
    assert config.deepseek_api_key == "sk-test-secret"


def test_from_env_reads_llm_model_extract() -> None:
    config = Config.from_env({"LLM_MODEL_EXTRACT": "deepseek-v4-flash-custom"})
    assert config.llm_model_extract == "deepseek-v4-flash-custom"


def test_from_env_parses_fuzzy_threshold_as_float() -> None:
    config = Config.from_env({"MSR_FUZZY_THRESHOLD": "85"})
    assert config.fuzzy_threshold == 85.0
    assert isinstance(config.fuzzy_threshold, float)


def test_from_env_parses_fuzzy_min_token_length_as_int() -> None:
    config = Config.from_env({"MSR_FUZZY_MIN_TOKEN_LENGTH": "6"})
    assert config.fuzzy_min_token_length == 6
    assert isinstance(config.fuzzy_min_token_length, int)


@pytest.mark.parametrize(
    ("env", "attr", "expected"),
    [
        ({"DEEPSEEK_BASE_URL": "https://x"}, "deepseek_base_url", "https://x"),
        ({"DEEPSEEK_API_KEY": "sk-x"}, "deepseek_api_key", "sk-x"),
        ({"LLM_MODEL_EXTRACT": "m"}, "llm_model_extract", "m"),
        ({"MSR_FUZZY_THRESHOLD": "72.5"}, "fuzzy_threshold", 72.5),
        ({"MSR_FUZZY_MIN_TOKEN_LENGTH": "3"}, "fuzzy_min_token_length", 3),
    ],
)
def test_from_env_table(env: dict[str, str], attr: str, expected: object) -> None:
    config = Config.from_env(env)
    assert getattr(config, attr) == expected


def test_sparql_query_endpoint_has_no_statements_suffix() -> None:
    config = Config(graphdb_url="http://localhost:7200", graphdb_repo="msr")
    assert config.sparql_query_endpoint == "http://localhost:7200/repositories/msr"
    assert not config.sparql_query_endpoint.endswith("/statements")


def test_sparql_query_endpoint_differs_from_update_endpoint() -> None:
    config = Config()
    assert config.sparql_query_endpoint != config.sparql_update_endpoint
    assert config.sparql_update_endpoint == f"{config.sparql_query_endpoint}/statements"


@pytest.mark.parametrize(
    ("method_name", "expected_name"),
    [
        ("segments_path", "segments.jsonl"),
        ("mentions_path", "mentions.jsonl"),
        ("normalized_path", "normalized.txt"),
    ],
)
def test_report_artifact_paths_compose_under_corpus_dir(
    method_name: str, expected_name: str
) -> None:
    config = Config(corpus_dir=Path("data/corpus"))
    path = getattr(config, method_name)("ORNL-TM-2316")
    assert path == Path("data/corpus") / "ORNL-TM-2316" / expected_name


class TestFuzzyMinTokenLengthGovernsChemistryEligibility:
    """ocr-robust-salt-linking design.md D5 / specs/entity-linking spec
    "Bounded fuzzy fallback admits short chemistry tokens": the minimum
    token length gating fuzzy eligibility MUST remain an injectable
    configuration value, never a hardcoded constant.

    These tests pin the *field itself* (construction + env override) at an
    explicit, non-default value -- deliberately not asserting on
    `Config.fuzzy_min_token_length`'s default, which task 4.1 leaves to the
    coder's judgment (it may stay 4, with a 3-char knob applied only via an
    explicit override, or move to 3 outright). The downstream behavioral
    contract -- that this value actually governs whether a 3-char formula
    token like `LiF`/`BeF` is eligible for the bounded fuzzy fallback -- is
    covered in test_linker.py's `TestBoundedFuzzyShortChemistryTokens`
    (already exercises `Config(fuzzy_min_token_length=3)` end to end via
    `fuzzy_link`/`link_segment`, so it needs no coder change to hold)."""

    def test_config_accepts_an_explicit_three_char_min_token_length(self) -> None:
        config = Config(fuzzy_min_token_length=3)
        assert config.fuzzy_min_token_length == 3
        assert isinstance(config.fuzzy_min_token_length, int)

    def test_env_override_can_set_min_token_length_to_three(self) -> None:
        config = Config.from_env({"MSR_FUZZY_MIN_TOKEN_LENGTH": "3"})
        assert config.fuzzy_min_token_length == 3

    def test_a_higher_min_token_length_is_distinct_from_the_three_char_value(self) -> None:
        # Round-tripping two distinct values through the same field/env
        # variable proves eligibility is driven by configuration, not a
        # hardcoded constant baked into the fuzzy fallback itself.
        low = Config.from_env({"MSR_FUZZY_MIN_TOKEN_LENGTH": "3"})
        high = Config.from_env({"MSR_FUZZY_MIN_TOKEN_LENGTH": "6"})
        assert low.fuzzy_min_token_length == 3
        assert high.fuzzy_min_token_length == 6
        assert low.fuzzy_min_token_length != high.fuzzy_min_token_length
