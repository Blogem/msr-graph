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
    # The layer-4 fuzzy fallback's minimum-token-length floor (chunk 6, task
    # 3.2/4.1). `fuzzy_link` has exactly one call site, and that call site
    # only ever runs on already formula-shaped candidate spans (never general
    # prose) -- so a floor of 3 (the intended chemistry-token minimum, per
    # design.md D5) doesn't broaden precision risk the way lowering a
    # general-prose fuzzy floor would.
    fuzzy_min_token_length: int = 3
    # Novelty miner's document-frequency FLOOR (refine-mine-salience D3): a
    # coarse cost bound, NOT a novelty rank — the POC showed document
    # frequency does not separate genuine targets from common/known phrases
    # (`solubility` at df 271 is rarer than `molten salt` at df 423), so this
    # value only drops rare OCR one-offs before the shaped candidate set
    # reaches triage. 50 is conservative — well below the demo targets
    # `solubility` (280/637 docs) and `graphite` (388/637 docs), so both clear
    # it, while still filtering out low-frequency OCR noise terms.
    salience_threshold: int = 50
    # Novelty miner's hard runaway ceiling (refine-mine-salience D3): after
    # spaCy shaping + hardened exclusion + the `salience_threshold` floor, if
    # more candidates remain than this, keep only the top-N by document
    # frequency (deterministic tie-break) and log the count cut. This is
    # purely a cost bound on LLM triage fan-out — explicitly not a novelty
    # ranking (see `salience_threshold` above) — so it is set generously
    # rather than tuned to surface targets. Override with
    # MSR_MINE_MAX_CANDIDATES.
    mine_max_candidates: int = 5000
    # The pinned statistical spaCy model loaded for noun-chunk candidate
    # enumeration (refine-mine-salience D5): deterministic at inference (no
    # sampling), pinned as a wheel dependency so no runtime download occurs.
    # Override with MSR_SPACY_MODEL (e.g. to swap models in a test double).
    spacy_model: str = "en_core_web_sm"
    # Chunk 7 (extract-property-relations) — the SQLite measurement_value
    # store's path (D-mirrors the Go loader/server `defaultDBPath =
    # "data/msr.db"` and `MSR_DB_PATH` env), so text-derived measurements can
    # be written to the same store as the NIST loader's rows.
    db_path: Path = Path("data/msr.db")
    # Precision knob for accepting an LLM-proposed relation as a written
    # msr:PropertyMeasurement (chunk 7). 0.5 is a deliberately precision-biased
    # default: a proposed relation must clear at least even odds before it is
    # written to the graph, favoring fewer false positives over recall at POC
    # scale.
    confidence_threshold: float = 0.5
    # Mirrors the loader's `MSR_ONTOLOGY_DIR=/app/ontology` (chunk 7) — the
    # directory containing the QUDT unit allowlist used to validate
    # LLM-proposed units before they are written.
    ontology_dir: Path = Path("ontology")
    # Mention-writer batch size (scale-mention-linking, D1): a report's
    # mentions are written as multiple additive INSERT DATA POSTs of at most
    # this many mentions each, keeping any single POST body well under
    # GraphDB's Tomcat maxPostSize (a single unbatched POST of a large
    # OCR-heavy report — e.g. NSRDS-NBS-61-p4's ~3.8k mentions — otherwise
    # exceeds it and is rejected with an HTTP 500).
    mention_write_batch_size: int = 500
    # Layer-5 disambiguation concurrency (scale-mention-linking, D2): the
    # bounded worker-pool size used to resolve a run's distinct unresolved
    # surfaces in parallel. The DeepSeek/openai client is blocking I/O, so
    # threads overlap the network round-trips that otherwise dominate the
    # link wall-clock. 24 is a safe, effective default for this workload:
    # comfortably below DeepSeek's concurrency ceiling and any practical
    # rate limit, while enough to overlap the per-call latency that
    # otherwise dominates. Override with MSR_DISAMBIG_CONCURRENCY. Reused by
    # chunk 7's extract as the per-sentence relation-extraction fan-out size.
    disambig_concurrency: int = 24
    # When true, ignore any persisted disambiguation cache on load and
    # re-resolve every layer-5 surface via the model, rewriting the store
    # (persist-disambiguation-cache D4). Env MSR_DISAMBIG_REFRESH.
    disambig_cache_refresh: bool = False
    # Chunk 11 (ingest-iaea-safety D3, task 3.1) — the safety genre's
    # noun-chunk candidate window for the novelty miner. Safety concepts are
    # longer prepositional phrases ("confinement of radioactive material",
    # "removal of residual heat") than the chemistry default of 3 surviving
    # content tokens allows, so this genre gets its own (relaxed) window.
    # Override with MSR_SAFETY_MAX_CHUNK_TOKENS.
    safety_max_chunk_tokens: int = 6

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
            salience_threshold=int(
                env.get("MSR_SALIENCE_THRESHOLD", cls.salience_threshold)
            ),
            mine_max_candidates=int(
                env.get("MSR_MINE_MAX_CANDIDATES", cls.mine_max_candidates)
            ),
            spacy_model=env.get("MSR_SPACY_MODEL", cls.spacy_model),
            db_path=Path(env.get("MSR_DB_PATH", str(cls.db_path))),
            confidence_threshold=float(
                env.get(
                    "MSR_EXTRACT_CONFIDENCE_THRESHOLD", cls.confidence_threshold
                )
            ),
            ontology_dir=Path(env.get("MSR_ONTOLOGY_DIR", str(cls.ontology_dir))),
            mention_write_batch_size=int(
                env.get("MSR_MENTION_WRITE_BATCH_SIZE", cls.mention_write_batch_size)
            ),
            disambig_concurrency=int(
                env.get("MSR_DISAMBIG_CONCURRENCY", cls.disambig_concurrency)
            ),
            disambig_cache_refresh=(
                env.get("MSR_DISAMBIG_REFRESH", "").strip().lower()
                in ("1", "true", "yes")
            ),
            safety_max_chunk_tokens=int(
                env.get("MSR_SAFETY_MAX_CHUNK_TOKENS", cls.safety_max_chunk_tokens)
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
    def disambig_cache_path(self) -> Path:
        """Path to the persisted layer-5 disambiguation cache (corpus-scoped).

        Under ``corpus_dir`` (the ./data bind mount) so it survives across
        `make link` container runs, and gitignored so it is never committed
        (persist-disambiguation-cache D1).
        """
        return self.corpus_dir / "disambiguation-cache.json"

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

    def relations_path(self, report: str) -> Path:
        """Path to the chunk-7 relation-extraction artifact for a given report."""
        return self.report_dir(report) / "relations.jsonl"

    @property
    def qudt_units_path(self) -> Path:
        """Path to the QUDT unit allowlist consulted by relation extraction."""
        return self.ontology_dir / "qudt-units.json"

    @property
    def safety_dir(self) -> Path:
        """The gitignored safety-source cache dir (chunk 11 D1).

        Rooted alongside ``corpus_dir`` off the shared data root (mirroring
        how :attr:`archive_dir` is rooted off ``corpus_dir``), so overriding
        ``MSR_CORPUS_DIR`` moves both caches together.
        """
        return self.corpus_dir.parent / "safety"

    def safety_text_path(self, source_id: str) -> Path:
        """Path to the pypdf-extracted raw text for a safety source (D1/1.3)."""
        return self.safety_dir / f"{source_id}.txt"

    def safety_report_dir(self, source_id: str) -> Path:
        """Directory holding the processed artifacts for a safety source."""
        return self.safety_dir / source_id

    def safety_normalized_path(self, source_id: str) -> Path:
        """Path to the chunk-5 normalized text for a safety source."""
        return self.safety_report_dir(source_id) / "normalized.txt"

    def safety_segments_path(self, source_id: str) -> Path:
        """Path to the chunk-5 segmented-text artifact for a safety source."""
        return self.safety_report_dir(source_id) / "segments.jsonl"

    def safety_mentions_path(self, source_id: str) -> Path:
        """Path to the chunk-6 mention/miss artifact for a safety source."""
        return self.safety_report_dir(source_id) / "mentions.jsonl"

    def safety_relations_path(self, source_id: str) -> Path:
        """Path to the chunk-7 relation-extraction artifact for a safety source."""
        return self.safety_report_dir(source_id) / "relations.jsonl"
