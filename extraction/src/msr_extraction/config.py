"""Pipeline configuration.

A single, injectable source of truth for the paths, URLs, and repository name
the extraction pipeline needs. Reads from the environment by default but
accepts an explicit mapping so tests never touch real process environment.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    """Runtime configuration for the extraction pipeline.

    Construct via :meth:`from_env` in normal operation; the dataclass fields
    themselves carry the documented defaults so ``Config()`` (with no args)
    is already a usable, self-consistent configuration for local dev/tests.
    """

    graphdb_url: str = "http://localhost:7200"
    graphdb_repo: str = "msr"
    corpus_dir: Path = Path("data/corpus")
    msr_archive_url: str = "https://github.com/openmsr/msr-archive"
    # Raw checkout dir under corpus_dir (D1). Not environment-configurable —
    # it is an internal layout detail, not a deployment parameter.
    archive_subdir: str = "msr-archive"
    # Chunk 6 (ner-entity-linking) — the injected DeepSeek client (D5) and the
    # bounded rapidfuzz fallback's tuning knobs (D4).
    deepseek_base_url: str = ""
    # Optional bearer credential for the DeepSeek endpoint above. Left empty
    # by default so `make link` still works against keyless/compatible
    # endpoints (see FlashClient.complete's "unused" fallback) — never
    # logged.
    deepseek_api_key: str = ""
    llm_model_extract: str = "deepseek-v4-flash"
    fuzzy_threshold: float = 90.0
    fuzzy_min_token_length: int = 4
    # Dedicated minimum-token-length knob for the layer-4 fuzzy fallback when
    # applied to formula-shaped candidate spans (chunk 6, task 3.2/4.1):
    # `fuzzy_min_token_length`'s default of 4 would disqualify short but
    # legitimate 3-char chemistry tokens like "LiF"/"BeF" -- since the fuzzy
    # layer only ever runs on already formula-shaped candidate spans (never
    # general prose), a lower floor here doesn't broaden precision risk the
    # way lowering the general knob would.
    fuzzy_min_token_length_chemistry: int = 3

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        """Build a Config from environment variables.

        ``env`` defaults to ``os.environ`` but can be an explicit mapping so
        tests can inject values without mutating real process environment.
        Missing variables fall back to the field defaults declared above.
        """
        if env is None:
            env = os.environ
        return cls(
            graphdb_url=env.get("GRAPHDB_URL", cls.graphdb_url),
            graphdb_repo=env.get("GRAPHDB_REPO", cls.graphdb_repo),
            corpus_dir=Path(env.get("MSR_CORPUS_DIR", str(cls.corpus_dir))),
            msr_archive_url=env.get("MSR_ARCHIVE_URL", cls.msr_archive_url),
            deepseek_base_url=env.get("DEEPSEEK_BASE_URL", cls.deepseek_base_url),
            deepseek_api_key=env.get("DEEPSEEK_API_KEY", cls.deepseek_api_key),
            llm_model_extract=env.get("LLM_MODEL_EXTRACT", cls.llm_model_extract),
            fuzzy_threshold=float(
                env.get("MSR_FUZZY_THRESHOLD", cls.fuzzy_threshold)
            ),
            fuzzy_min_token_length=int(
                env.get("MSR_FUZZY_MIN_TOKEN_LENGTH", cls.fuzzy_min_token_length)
            ),
            fuzzy_min_token_length_chemistry=int(
                env.get(
                    "MSR_FUZZY_MIN_TOKEN_LENGTH_CHEMISTRY",
                    cls.fuzzy_min_token_length_chemistry,
                )
            ),
        )

    @property
    def archive_dir(self) -> Path:
        """The raw msr-archive checkout directory (D1)."""
        return self.corpus_dir / self.archive_subdir

    @property
    def readme_path(self) -> Path:
        """Path to the msr-archive manifest (its README.md)."""
        return self.archive_dir / "README.md"

    def report_dir(self, report: str) -> Path:
        """Directory holding the processed artifacts for a given report number."""
        return self.corpus_dir / report

    @property
    def sparql_update_endpoint(self) -> str:
        """The GraphDB SPARQL UPDATE endpoint for the configured repository."""
        return f"{self.graphdb_url}/repositories/{self.graphdb_repo}/statements"

    @property
    def sparql_query_endpoint(self) -> str:
        """The GraphDB SPARQL QUERY endpoint for the configured repository.

        Unlike :attr:`sparql_update_endpoint`, this does not carry the
        ``/statements`` suffix (D1) — it is the repository's read endpoint,
        used with explicit ``FROM``/dataset parameters for the core-dataset
        read guard.
        """
        return f"{self.graphdb_url}/repositories/{self.graphdb_repo}"

    def segments_path(self, report: str) -> Path:
        """Path to the chunk-5 segmented-text artifact for a given report."""
        return self.report_dir(report) / "segments.jsonl"

    def mentions_path(self, report: str) -> Path:
        """Path to the chunk-6 mention/miss artifact for a given report (D7)."""
        return self.report_dir(report) / "mentions.jsonl"

    def normalized_path(self, report: str) -> Path:
        """Path to the chunk-5 OCR-normalized text for a given report."""
        return self.report_dir(report) / "normalized.txt"
