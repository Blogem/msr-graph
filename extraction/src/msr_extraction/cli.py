"""Ingest pipeline CLI.

Subcommand dispatcher extending the chunk-1 ``--help`` scaffold with the
real pipeline stages (design.md D7): ``acquire``, ``manifest``,
``normalize``, ``documents``, and an ``ingest`` umbrella that runs them in
order (task 8.1). All sibling modules imported here are first-party and
have no third-party imports at module level, so this file (like the rest
of the package) stays importable with zero third-party dependencies
installed.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from msr_extraction import (
    acquisition,
    backfill_observations,
    curated,
    disambig_cache,
    documents,
    edges,
    linker,
    manifest,
    measurement_store,
    measurements,
    mentions,
    mine_runner,
    provenance,
    relations,
    safety_acquire,
    safety_manifest,
    segmenter,
    units,
)
from msr_extraction.config import Config
from msr_extraction.disambiguation import FlashClient, disambiguate
from msr_extraction.graph_reader import GraphReader
from msr_extraction.kg_prompt import KGSchemaPromptCache
from msr_extraction.safety_manifest import SafetySource
from msr_extraction.seeding import build_matcher
from msr_extraction.sparql import SparqlClient

logger = logging.getLogger(__name__)

#: Path to the safety-source fetch script (design.md D8, task 7.1), relative
#: to the process cwd -- mirrors every other `Config` path default
#: (`corpus_dir`, `ontology_dir`, ...) in assuming the CLI runs from the
#: repo root. Overridable via env for a container layout that differs.
_SAFETY_FETCH_SCRIPT_ENV = "MSR_SAFETY_FETCH_SCRIPT"
_SAFETY_FETCH_SCRIPT_DEFAULT = "scripts/fetch-safety-sources.sh"


def _load_manifest_records(config: Config) -> list[manifest.ManifestRecord]:
    readme_text = config.readme_path.read_text(encoding="utf-8")
    return manifest.parse_manifest(readme_text)


def _cmd_acquire(config: Config) -> int:
    logger.info("acquire: cloning %s into %s", config.msr_archive_url, config.archive_dir)
    acquisition.acquire(config)
    logger.info("acquire: done")
    return 0


def _cmd_manifest(config: Config) -> int:
    logger.info("manifest: parsing %s", config.readme_path)
    records = _load_manifest_records(config)
    logger.info("manifest: parsed %d record(s)", len(records))
    print(f"Parsed {len(records)} manifest record(s) from {config.readme_path}")
    return 0


def _cmd_normalize(config: Config) -> int:
    records = _load_manifest_records(config)
    logger.info("normalize: %d curated report(s) to process", len(curated.CURATED_REPORTS))
    for report in curated.CURATED_REPORTS:
        ocr_path = manifest.resolve_ocr_path(records, report)
        logger.info("normalize: report=%s ocr_path=%s", report, ocr_path)
        segmenter.run_normalize(report, config, ocr_path)
    logger.info("normalize: done")
    return 0


def _cmd_documents(config: Config) -> int:
    records = _load_manifest_records(config)
    curated_set = set(curated.CURATED_REPORTS)
    curated_records = [r for r in records if r.report_number in curated_set]
    logger.info("documents: writing %d document node(s)", len(curated_records))
    client = SparqlClient.from_config(config)
    run_ts = provenance.run_timestamp()
    provenance.write_stable_activity(client)
    provenance.write_activity(run_ts, client)
    documents.write_documents(curated_records, client, run_ts)
    logger.info("documents: done")
    return 0


def _cmd_ingest(config: Config) -> int:
    logger.info("ingest: stage 1/4 acquire")
    acquisition.acquire(config)

    logger.info("ingest: stage 2/4 manifest")
    records = _load_manifest_records(config)
    logger.info("ingest: parsed %d manifest record(s)", len(records))

    logger.info("ingest: stage 3/4 normalize")
    for report in curated.CURATED_REPORTS:
        ocr_path = manifest.resolve_ocr_path(records, report)
        segmenter.run_normalize(report, config, ocr_path)

    logger.info("ingest: stage 4/4 documents")
    curated_set = set(curated.CURATED_REPORTS)
    curated_records = [r for r in records if r.report_number in curated_set]
    client = SparqlClient.from_config(config)
    run_ts = provenance.run_timestamp()
    provenance.write_stable_activity(client)
    provenance.write_activity(run_ts, client)
    documents.write_documents(curated_records, client, run_ts)

    logger.info("ingest: complete")
    return 0


def _resolve_link_reports(
    all_reports: list[str], selected: list[str] | None, limit: int | None
) -> list[str]:
    """Return the ordered subset of `all_reports` the `link` command should process.

    `selected` (from repeatable `--report`) restricts the set to the named
    report ids, preserving `all_reports` order; every id must be present in
    `all_reports` or a `ValueError` naming the unknown id(s) is raised.
    `limit` (from `--limit`) then takes the first N of that (possibly
    filtered) selection; a limit < 1 raises `ValueError`. Passing neither
    `selected` nor `limit` returns `all_reports` unchanged.
    """
    if selected is not None:
        known = set(all_reports)
        unknown = [report for report in selected if report not in known]
        if unknown:
            raise ValueError(
                f"unknown --report id(s): {', '.join(unknown)}; "
                f"expected one of: {', '.join(all_reports)}"
            )
        selected_set = set(selected)
        reports = [report for report in all_reports if report in selected_set]
    else:
        reports = list(all_reports)

    if limit is not None:
        if limit < 1:
            raise ValueError(f"--limit must be >= 1, got {limit}")
        reports = reports[:limit]

    return reports


def _cmd_link(config: Config, reports: list[str] = curated.CURATED_REPORTS) -> int:
    """Seed the matcher from the graph, link the selected curated document(s),
    write mention triples + `mentions.jsonl`, and print a per-doc run summary
    (design.md D1/D7, tasks 6.2/9.1).

    `reports` defaults to the full `curated.CURATED_REPORTS` set; callers
    (e.g. the CLI dispatcher) may pass a `--report`/`--limit`-filtered subset
    to bound a run to fewer documents.

    Guards a missing `segments.jsonl` per report (logs a warning and skips
    it) so a partial corpus doesn't crash the whole run.

    Generates a single run timestamp for this invocation
    (provenance-run-lineage design.md D1/D3) and writes the stable
    per-pipeline `Activity` typing plus the per-run extraction `Activity`
    node into `urn:msr:provenance` *before* processing any report, so the
    run node exists before the per-report `write_mentions` calls emit
    generation edges referencing it -- closing the crash window where a
    generation edge could point at an untyped run IRI. Every mention
    written across the whole invocation carries a generation edge to the
    same `urn:msr:run:extraction/<ts>` activity node.
    """
    reader = GraphReader.from_config(config)
    prompt_prefix = KGSchemaPromptCache().get(reader)

    known = reader.read_known_entities()
    known_iris = reader.known_iris()
    matcher = build_matcher(known)

    client = FlashClient.from_config(config)
    disambiguator: linker.Disambiguator | None = None
    prewarm_report: "Callable[[str], None] | None" = None
    save_disambig_cache: "Callable[[], None] | None" = None
    if client is not None:
        # Per-run disambiguation cache keyed on surface form
        # (cache-disambiguation-by-surface): layer-5 candidates are
        # formula-shaped, so the surface determines identity and the same
        # unresolved formula recurring across segments/reports need only be
        # resolved once. A "novel" outcome is cached too. The known-IRI
        # validation inside `disambiguate` still gates every link, so a
        # cached outcome can never be a link to an unloaded IRI.
        _disambig_cache: dict[str, tuple[str, str | None]] = {}

        # Cross-run persistence (persist-disambiguation-cache D2/D3): seed the
        # cache from the on-disk store, but only when it was written against
        # the same known-IRI set (the hash guards staleness). Seeded surfaces
        # are skipped by the pre-warm collector, so an unchanged graph makes
        # zero model calls on re-run. Seeded `linked` entries are re-validated
        # against the live known-IRI set (belt-and-suspenders against a
        # hand-edited store).
        _iris_hash = disambig_cache.known_iris_hash(known_iris)
        if not config.disambig_cache_refresh:
            seeded = disambig_cache.load_cache(config.disambig_cache_path, _iris_hash)
            for surface, (status, target_iri) in seeded.items():
                if status == "linked" and target_iri not in known_iris:
                    continue
                _disambig_cache[surface] = (status, target_iri)
            if _disambig_cache:
                logger.info(
                    "link: seeded %d disambiguation outcome(s) from %s",
                    len(_disambig_cache),
                    config.disambig_cache_path,
                )

        def save_disambig_cache() -> None:
            disambig_cache.save_cache(
                config.disambig_cache_path, _iris_hash, _disambig_cache
            )
            logger.info(
                "link: wrote %d disambiguation outcome(s) to %s",
                len(_disambig_cache),
                config.disambig_cache_path,
            )

        def _resolve(surface: str, sentence: str) -> tuple[str, str | None]:
            result = disambiguate(surface, sentence, prompt_prefix, known_iris, client)
            return (result.status, result.target_iri)

        def disambiguator(surface: str, sentence: str) -> tuple[str, str | None]:
            cached = _disambig_cache.get(surface)
            if cached is not None:
                return cached
            outcome = _resolve(surface, sentence)
            _disambig_cache[surface] = outcome
            return outcome

        def prewarm_report(report: str) -> None:
            # Concurrent pre-warm (scale-mention-linking D2). A cheap collect
            # scan gathers this report's distinct not-yet-cached layer-5
            # surfaces (the collector returns "novel" so linking proceeds and
            # the throwaway records are discarded), then a bounded thread pool
            # resolves them in parallel into the shared cache — so the real
            # link pass below issues no model calls. Threads are correct here
            # because the DeepSeek client is blocking I/O; `disambiguate`
            # never raises, so worker futures never do. `pending` maps each
            # distinct surface to the first sentence context seen for it.
            pending: dict[str, str] = {}

            def collector(surface: str, sentence: str) -> tuple[str, str | None]:
                if surface not in _disambig_cache and surface not in pending:
                    pending[surface] = sentence
                return ("novel", None)

            linker.link_report(
                report,
                config,
                matcher,
                known,
                known_iris,
                prompt_prefix=prompt_prefix,
                disambiguator=collector,
            )
            if not pending:
                return
            with ThreadPoolExecutor(max_workers=config.disambig_concurrency) as pool:
                futures = {
                    pool.submit(_resolve, surface, sentence): surface
                    for surface, sentence in pending.items()
                }
                for future in as_completed(futures):
                    _disambig_cache[futures[future]] = future.result()
            logger.info(
                "link: report=%s pre-warmed %d distinct layer-5 surface(s) (concurrency=%d)",
                report,
                len(pending),
                config.disambig_concurrency,
            )

    else:
        logger.warning("link: DEEPSEEK_BASE_URL not configured; layer 5 spans fall to novel")

    sparql = SparqlClient.from_config(config)
    run_ts = provenance.run_timestamp()
    provenance.write_stable_activity(sparql)
    provenance.write_activity(run_ts, sparql)

    logger.info("link: %d curated report(s) to process", len(reports))
    for report in reports:
        segments_path = config.segments_path(report)
        if not segments_path.exists():
            logger.warning("link: report=%s missing %s, skipping", report, segments_path)
            continue

        if prewarm_report is not None:
            prewarm_report(report)

        records = linker.link_report(
            report,
            config,
            matcher,
            known,
            known_iris,
            prompt_prefix=prompt_prefix,
            disambiguator=disambiguator,
        )
        linker.write_mentions_jsonl(report, records, config)

        document_iri = mentions.MSRD + report
        linked_mentions = [
            mentions.Mention(
                report=record.report,
                start=record.char_start,
                end=record.char_end,
                surface_form=record.surface_form,
                target_iri=record.target_iri,
                document_iri=document_iri,
            )
            for record in records
            if record.status == "linked"
        ]
        mentions.write_mentions(
            linked_mentions, sparql, run_ts, batch_size=config.mention_write_batch_size
        )

        linked_count = len(linked_mentions)
        novel_count = len(records) - linked_count
        layer_counts = {
            layer: sum(1 for record in records if record.layer == layer)
            for layer in (2, 3, 4, 5)
        }
        summary = (
            f"link: report={report} spans={len(records)} linked={linked_count} "
            f"novel={novel_count} layer2={layer_counts[2]} layer3={layer_counts[3]} "
            f"layer4={layer_counts[4]} layer5={layer_counts[5]}"
        )
        logger.info(summary)
        print(summary)

    if save_disambig_cache is not None:
        save_disambig_cache()

    logger.info("link: complete")
    return 0


def _cmd_mine(config: Config) -> int:
    """Run the full ontology-mining pipeline and print a one-line run summary.

    Thin wrapper (design.md, OpenSpec task 1.1-CLI): all orchestration --
    enumerate/exclude/score candidates, triage each, build proposal
    bundles + rides-with individuals, write proposals and auto-accepted
    instances, and wire the per-run provenance activity nodes -- lives in
    :func:`msr_extraction.mine_runner.run_mine`, mirroring how ``_cmd_link``
    delegates its per-report work to ``linker.link_report``.
    """
    summary = mine_runner.run_mine(config)
    by_kind = summary["proposals_by_kind"]
    kind_summary = " ".join(f"{kind}={count}" for kind, count in sorted(by_kind.items()))
    line = (
        f"mine: candidates={summary['candidates']} "
        f"proposals=[{kind_summary}] "
        f"auto_accepted={summary['auto_accepted']} "
        f"rejected={summary['rejected']} "
        f"dropped={summary['dropped']}"
    )
    logger.info(line)
    print(line)
    return 0


def _cmd_extract(config: Config, reports: list[str] = curated.CURATED_REPORTS) -> int:
    """Extract salt<->property<->value measurements and salt<->role/reactor
    edges from linked sentences, write both measurement stores + role/reactor
    edges (+ minted reactors) with per-fact generation provenance, and print
    a per-doc run summary (design.md D2/D4/D5/D6/D7, tasks 7.1/5.6/2.2).

    `reports` defaults to the full `curated.CURATED_REPORTS` set; callers
    (e.g. the CLI dispatcher) may pass a `--report`/`--limit`-filtered subset
    to bound a run to fewer documents.

    Guards a missing `segments.jsonl` per report (logs a warning and skips
    it) so a partial corpus doesn't crash the whole run.

    Generates a single run timestamp for this invocation and writes the
    stable per-pipeline `Activity` typing plus the per-run extraction
    `Activity` node into `urn:msr:provenance` *before* processing any
    report, so the run node exists before any measurement/edge write emits
    a generation edge referencing it. Reuses the cached KG-schema prompt
    prefix (task 2.2) rather than re-deriving it.
    """
    reader = GraphReader.from_config(config)
    prompt_prefix = KGSchemaPromptCache().get(reader)

    known = relations.KnownSets(
        molten_salts=reader.read_molten_salts(),
        physical_properties=reader.read_physical_properties(),
        salt_roles=reader.read_salt_roles(),
        reactor_concepts=reader.read_reactor_concepts(),
    )
    unit_mapper = units.UnitMapper.from_config(config)

    client = FlashClient.from_config(config)
    if client is None:
        logger.warning(
            "extract: DEEPSEEK_BASE_URL not configured; no relations will be extracted"
        )
        return 0

    sparql = SparqlClient.from_config(config)
    conn = measurement_store.connect(config.db_path)

    run_ts = provenance.run_timestamp()
    provenance.write_stable_activity(sparql)
    provenance.write_activity(run_ts, sparql)

    logger.info("extract: %d curated report(s) to process", len(reports))
    logger.info("extract: fan-out concurrency=%d", config.disambig_concurrency)
    for report in reports:
        segments_path = config.segments_path(report)
        if not segments_path.exists():
            logger.warning("extract: report=%s missing %s, skipping", report, segments_path)
            continue

        result = relations.extract_report(
            report,
            config,
            prompt_prefix,
            client,
            known,
            unit_mapper,
            concurrency=config.disambig_concurrency,
        )

        for m in result.measurements:
            measurements.write_measurement(
                salt_iri=m.salt_iri,
                property_iri=m.property_iri,
                property_name=m.property_name,
                unit_curie=m.unit_curie,
                equation=m.equation,
                uncertainty=m.uncertainty,
                confidence=m.confidence,
                rationale=m.rationale,
                report=m.report,
                client=sparql,
                conn=conn,
                run_ts=run_ts,
            )

        role_edges = [
            edges.RoleEdge(
                salt_iri=r.salt_iri,
                role_iri=r.role_iri,
                report=r.report,
                document_iri=f"msrd:{r.report}",
                confidence=r.confidence,
                rationale=r.rationale,
            )
            for r in result.roles
        ]
        reactor_edges = [
            edges.ReactorEdge(
                salt_iri=r.salt_iri,
                reactor_slug=edges.slugify(r.reactor_label).lower(),
                reactor_label=r.reactor_label,
                grounding_concept_iri=r.reactor_concept_iri,
                report=r.report,
                document_iri=f"msrd:{r.report}",
                confidence=r.confidence,
                rationale=r.rationale,
            )
            for r in result.reactors
        ]
        edges.write_edges(role_edges, reactor_edges, sparql, run_ts)

        rejected = sum(1 for record in result.records if record.disposition == "rejected")
        skipped = sum(1 for record in result.records if record.disposition == "skipped")
        summary = (
            f"extract: report={report} sentences={result.sentences_seen} "
            f"relations={len(result.records)} measurements={len(result.measurements)} "
            f"roles={len(result.roles)} reactors={len(result.reactors)} "
            f"rejected={rejected} skipped={skipped} "
            f"malformed_calls={result.malformed_calls}"
        )
        logger.info(summary)
        print(summary)

    conn.close()
    logger.info("extract: complete")
    return 0


def _cmd_backfill_observations(config: Config) -> int:
    """Run the deterministic, inference-free observation backfill and print a summary.

    Thin wrapper (proposal-observation-provenance design.md D4/D6, task
    4.4) mirroring `_cmd_mine`'s shape: all orchestration -- reading staged
    proposals, re-scanning both cached corpora, writing per-document/
    per-corpus observations, tagging scanned documents, and removing the
    stale `msr:docFrequency` scalars -- lives in
    `backfill_observations.run_backfill`. No LLM/triage call is made and no
    corpus is re-acquired; re-running is idempotent (fixed backfill run
    token, see that module's docstring).
    """
    summary = backfill_observations.run_backfill(config)
    line = (
        f"backfill-observations: proposals_processed={summary.proposals_processed} "
        f"observations_written={summary.observations_written} "
        f"documents_tagged={summary.documents_tagged} "
        f"doc_frequency_scalars_removed={summary.doc_frequency_scalars_removed}"
    )
    logger.info(line)
    print(line)
    return 0


# --- `safety` subcommand group (design.md D8, OpenSpec task 7.1) -----------
#
# Wires the already-merged safety-genre modules (`safety_manifest`,
# `safety_acquire`, `documents.write_safety_documents`, the genre-aware
# `linker`/`novelty`/`triage`/`mine_runner`/`relations`/`edges`/
# `graph_reader`) into the same fetch -> extract -> documents -> link ->
# mine -> relations shape as the chemistry `ingest` umbrella, over the four
# fixed `safety_manifest.SAFETY_SOURCES` instead of `curated.CURATED_REPORTS`.


def _cmd_safety_fetch(
    config: Config, runner: Callable[..., object] = subprocess.run
) -> int:
    """Fetch the cached safety-source PDFs (design.md D1, task 1.1).

    Invokes `scripts/fetch-safety-sources.sh`, mirroring
    `acquisition.acquire`'s injectable-runner convention so tests can
    supply a fake and assert the constructed command without touching the
    network; the script itself is already idempotent (skips any file
    already present in `data/safety/`).
    """
    script = os.environ.get(_SAFETY_FETCH_SCRIPT_ENV, _SAFETY_FETCH_SCRIPT_DEFAULT)
    logger.info("safety fetch: running %s", script)
    runner(["bash", script], check=True)
    logger.info("safety fetch: done")
    return 0


def _cmd_safety_extract(
    config: Config, sources: tuple[SafetySource, ...] = safety_manifest.SAFETY_SOURCES
) -> int:
    """pypdf-extract, normalize, and segment every cached safety-source PDF
    (design.md D1, tasks 1.3/1.4): `safety_acquire.extract_pdf_text` then
    `safety_acquire.normalize_and_segment`, per source, honoring the
    manifest's declared section/page scope.
    """
    logger.info("safety extract: %d source(s) to process", len(sources))
    for source in sources:
        text_path = safety_acquire.extract_pdf_text(source, config)
        normalized_path, segments_path = safety_acquire.normalize_and_segment(
            source, config
        )
        summary = (
            f"safety extract: source={source.id} text={text_path} "
            f"normalized={normalized_path} segments={segments_path}"
        )
        logger.info(summary)
        print(summary)
    logger.info("safety extract: done")
    return 0


def _cmd_safety_documents(
    config: Config, sources: tuple[SafetySource, ...] = safety_manifest.SAFETY_SOURCES
) -> int:
    """Write the four attributed safety `Document` nodes (design.md D2, task 2.1/2.2)."""
    logger.info("safety documents: writing %d document node(s)", len(sources))
    client = SparqlClient.from_config(config)
    run_ts = provenance.run_timestamp()
    provenance.write_stable_activity(client)
    provenance.write_activity(run_ts, client)
    documents.write_safety_documents(list(sources), client, run_ts)
    logger.info("safety documents: done")
    return 0


def _run_safety_link(
    config: Config, sources: tuple[SafetySource, ...] = safety_manifest.SAFETY_SOURCES
) -> None:
    """Genre-aware link stage for the safety corpus (design.md D8, task 7.1).

    Minimal viable version of `_cmd_link` for the safety genre: reuses the
    identical layered resolution (`linker.link_segment`'s layers 2-5) via
    `linker.link_report(..., genre="safety")` (reading
    `config.safety_segments_path`) and `linker.write_mentions_jsonl(...,
    genre="safety")` (writing `config.safety_mentions_path`), so the safety
    corpus's `mentions.jsonl` lands in the identical format the relation
    extractor already consumes.

    Deliberately does NOT wire `_cmd_link`'s persistent cross-run
    disambiguation cache (`disambig_cache`) or its concurrent per-report
    pre-warm fan-out: those are throughput optimizations for the
    hundreds-of-documents chemistry corpus, and the safety corpus is four
    documents, so the added surface area isn't worth it here (a limitation
    noted, not a correctness gap -- every span still resolves through the
    same `disambiguate` call when a `FlashClient` is configured).
    """
    reader = GraphReader.from_config(config)
    prompt_prefix = KGSchemaPromptCache().get(reader)
    known = reader.read_known_entities()
    known_iris = reader.known_iris()
    matcher = build_matcher(known)

    client = FlashClient.from_config(config)
    disambiguator: linker.Disambiguator | None = None
    if client is not None:

        def disambiguator(surface: str, sentence: str) -> tuple[str, str | None]:
            result = disambiguate(surface, sentence, prompt_prefix, known_iris, client)
            return (result.status, result.target_iri)

    else:
        logger.warning(
            "safety link: DEEPSEEK_BASE_URL not configured; spans fall to novel"
        )

    sparql = SparqlClient.from_config(config)
    run_ts = provenance.run_timestamp()
    provenance.write_stable_activity(sparql)
    provenance.write_activity(run_ts, sparql)

    logger.info("safety link: %d source(s) to process", len(sources))
    for source in sources:
        segments_path = config.safety_segments_path(source.id)
        if not segments_path.exists():
            logger.warning(
                "safety link: source=%s missing %s, skipping", source.id, segments_path
            )
            continue

        records = linker.link_report(
            source.id,
            config,
            matcher,
            known,
            known_iris,
            prompt_prefix=prompt_prefix,
            disambiguator=disambiguator,
            genre="safety",
        )
        linker.write_mentions_jsonl(source.id, records, config, genre="safety")

        document_iri = mentions.MSRD + source.id
        linked_mentions = [
            mentions.Mention(
                report=record.report,
                start=record.char_start,
                end=record.char_end,
                surface_form=record.surface_form,
                target_iri=record.target_iri,
                document_iri=document_iri,
            )
            for record in records
            if record.status == "linked"
        ]
        mentions.write_mentions(
            linked_mentions, sparql, run_ts, batch_size=config.mention_write_batch_size
        )

        linked_count = len(linked_mentions)
        summary = (
            f"safety link: source={source.id} spans={len(records)} "
            f"linked={linked_count} novel={len(records) - linked_count}"
        )
        logger.info(summary)
        print(summary)

    logger.info("safety link: complete")


def _run_safety_relations(
    config: Config, sources: tuple[SafetySource, ...] = safety_manifest.SAFETY_SOURCES
) -> None:
    """The safety digital-thread linking relations, second phase (design.md D4).

    Populates `relations.KnownSets`'s `safety_functions`/`requirements` from
    `graph_reader.read_safety_functions`/`read_requirements` -- the *grown*
    (not seeded) closed sets the two linking relations validate their
    safety-individual subjects/targets against -- then runs
    `relations.extract_report(..., genre="safety")` per source and
    `edges.write_safety_edges` for whatever validates.

    Per design.md D4, this is legitimately a two-phase process: until the
    mined `SafetyFunction`/`Requirement` proposals (and the two linking
    object properties) are reviewed and approved into core via the chunk-9
    approval API, both closed sets read empty here, so every proposed
    `servedByProperty`/`addressesFunction` edge is rejected as
    unknown-target -- not written, but each is still recorded (with its
    rejection reason) in `relations.jsonl`. This is NOT a bug: re-run this
    phase (or `safety ingest` as a whole) after approval to pick up the
    now-resolvable safety individuals.
    """
    reader = GraphReader.from_config(config)
    known = relations.KnownSets(
        molten_salts=reader.read_molten_salts(),
        physical_properties=reader.read_physical_properties(),
        salt_roles=reader.read_salt_roles(),
        reactor_concepts=reader.read_reactor_concepts(),
        safety_functions=frozenset(reader.read_safety_functions()),
        requirements=frozenset(reader.read_requirements()),
    )
    if not known.safety_functions or not known.requirements:
        logger.warning(
            "safety relations: safety_functions=%d requirements=%d in core -- "
            "until the mined safety branch is reviewed and approved "
            "(design.md D4's two-phase ordering), servedByProperty/"
            "addressesFunction edges will legitimately validate to ZERO; "
            "this is the designed gate, not a bug",
            len(known.safety_functions),
            len(known.requirements),
        )

    unit_mapper = units.UnitMapper.from_config(config)
    client = FlashClient.from_config(config)
    if client is None:
        logger.warning(
            "safety relations: DEEPSEEK_BASE_URL not configured; no relations "
            "will be extracted"
        )
        return

    sparql = SparqlClient.from_config(config)
    run_ts = provenance.run_timestamp()
    provenance.write_stable_activity(sparql)
    provenance.write_activity(run_ts, sparql)
    prompt_prefix = KGSchemaPromptCache().get(reader)

    logger.info("safety relations: %d source(s) to process", len(sources))
    for source in sources:
        segments_path = config.safety_segments_path(source.id)
        if not segments_path.exists():
            logger.warning(
                "safety relations: source=%s missing %s, skipping",
                source.id,
                segments_path,
            )
            continue

        result = relations.extract_report(
            source.id,
            config,
            prompt_prefix,
            client,
            known,
            unit_mapper,
            concurrency=config.disambig_concurrency,
            genre="safety",
        )

        served_by_edges = [
            edges.ServedByEdge(
                safety_function_iri=r.safety_function_iri,
                property_iri=r.property_iri,
                report=r.report,
                document_iri=f"msrd:{r.report}",
                confidence=r.confidence,
                rationale=r.rationale,
                standard_name=r.standard_name,
            )
            for r in result.served_by_property
        ]
        addresses_function_edges = [
            edges.AddressesFunctionEdge(
                requirement_iri=r.requirement_iri,
                safety_function_iri=r.safety_function_iri,
                report=r.report,
                document_iri=f"msrd:{r.report}",
                confidence=r.confidence,
                rationale=r.rationale,
                standard_name=r.standard_name,
                threshold_value=r.threshold_value,
                threshold_comparator=r.threshold_comparator,
                threshold_unit=r.threshold_unit,
            )
            for r in result.addresses_function
        ]
        edges.write_safety_edges(served_by_edges, addresses_function_edges, sparql, run_ts)

        rejected = sum(1 for record in result.records if record.disposition == "rejected")
        skipped = sum(1 for record in result.records if record.disposition == "skipped")
        summary = (
            f"safety relations: source={source.id} sentences={result.sentences_seen} "
            f"servedByProperty={len(result.served_by_property)} "
            f"addressesFunction={len(result.addresses_function)} "
            f"rejected={rejected} skipped={skipped} "
            f"malformed_calls={result.malformed_calls}"
        )
        logger.info(summary)
        print(summary)

    logger.info("safety relations: complete")


def _cmd_safety_mine(config: Config) -> int:
    """Re-run mining for the safety genre alone (post-chunk-11 follow-up).

    Thin wrapper around `mine_runner.run_mine(config, genre="safety")`,
    mirroring `_cmd_mine`'s shape but scoped to the safety genre and
    standalone (unlike `_cmd_safety_ingest`'s `safety ingest` umbrella,
    this does not re-run `safety extract`/`safety documents`/
    `safety link` first) -- so a reviewer can re-mine against
    already-written safety `segments.jsonl`/`mentions.jsonl` (e.g. after
    tuning `MSR_SAFETY_SALIENCE_THRESHOLD`) without paying for a full
    `safety ingest` re-run. Prints the same run-summary line shape
    `_cmd_safety_ingest`'s mine stage logs.
    """
    summary = mine_runner.run_mine(config, genre="safety")
    by_kind = summary["proposals_by_kind"]
    kind_summary = " ".join(f"{kind}={count}" for kind, count in sorted(by_kind.items()))
    line = (
        f"safety mine: candidates={summary['candidates']} "
        f"proposals=[{kind_summary}] "
        f"auto_accepted={summary['auto_accepted']} "
        f"rejected={summary['rejected']} "
        f"dropped={summary['dropped']}"
    )
    logger.info(line)
    print(line)
    return 0


def _cmd_safety_ingest(config: Config) -> int:
    """The `safety ingest` umbrella (design.md D8): extract -> documents ->
    link -> mine -> the second-phase relations, in order, over the fixed
    `safety_manifest.SAFETY_SOURCES` set.

    Per design.md D4, mine+approve is a manual reviewer step (the chunk-9
    approval API) between the mine stage and the relations stage -- this
    umbrella still runs the relations stage immediately afterward in the
    same invocation (so a single `safety ingest` run exercises the whole
    pipeline shape end-to-end), but it will legitimately write zero
    `servedByProperty`/`addressesFunction` edges until a human has approved
    the mined safety branch. `_run_safety_relations` logs this clearly.
    Re-running `safety ingest` after approval picks up the now-resolvable
    safety individuals (idempotent: deterministic IRIs, `INSERT DATA`
    no-ops on repeat).
    """
    sources = safety_manifest.SAFETY_SOURCES

    logger.info("safety ingest: stage 1/5 extract")
    _cmd_safety_extract(config, sources=sources)

    logger.info("safety ingest: stage 2/5 documents")
    _cmd_safety_documents(config, sources=sources)

    logger.info("safety ingest: stage 3/5 link")
    _run_safety_link(config, sources=sources)

    logger.info("safety ingest: stage 4/5 mine")
    summary = mine_runner.run_mine(config, genre="safety")
    by_kind = summary["proposals_by_kind"]
    kind_summary = " ".join(f"{kind}={count}" for kind, count in sorted(by_kind.items()))
    mine_line = (
        f"safety ingest: mine candidates={summary['candidates']} "
        f"proposals=[{kind_summary}] "
        f"auto_accepted={summary['auto_accepted']} "
        f"rejected={summary['rejected']} "
        f"dropped={summary['dropped']}"
    )
    logger.info(mine_line)
    print(mine_line)

    logger.info(
        "safety ingest: stage 5/5 relations (second phase -- see design.md D4; "
        "requires the mined safety branch to already be reviewer-approved to "
        "produce any edges)"
    )
    _run_safety_relations(config, sources=sources)

    logger.info("safety ingest: complete")
    return 0


_SAFETY_HANDLERS = {
    "fetch": _cmd_safety_fetch,
    "extract": _cmd_safety_extract,
    "documents": _cmd_safety_documents,
    "mine": _cmd_safety_mine,
    "ingest": _cmd_safety_ingest,
}


_HANDLERS = {
    "acquire": _cmd_acquire,
    "manifest": _cmd_manifest,
    "normalize": _cmd_normalize,
    "documents": _cmd_documents,
    "ingest": _cmd_ingest,
    "link": _cmd_link,
    "mine": _cmd_mine,
    "extract": _cmd_extract,
    "backfill-observations": _cmd_backfill_observations,
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="msr-extraction",
        description="MSR knowledge-graph extraction pipeline.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("acquire", help="Clone the msr-archive corpus (idempotent).")
    subparsers.add_parser(
        "manifest", help="Parse the msr-archive README manifest and print a summary."
    )
    subparsers.add_parser(
        "normalize", help="Normalize and segment the curated document set."
    )
    subparsers.add_parser(
        "documents", help="Write curated Document provenance nodes to the graph."
    )
    subparsers.add_parser(
        "ingest", help="Run acquire, manifest, normalize, and documents in order."
    )
    link_parser = subparsers.add_parser(
        "link",
        help="Link recognized spans to known entities; write msr:Mention triples + mentions.jsonl.",
    )
    link_parser.add_argument(
        "--report",
        action="append",
        metavar="ID",
        help="Restrict linking to this curated report id (repeatable). Default: all curated reports.",
    )
    link_parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="Process only the first N of the (possibly --report-filtered) selection.",
    )
    subparsers.add_parser(
        "mine",
        help=(
            "Mine novel ontology candidates from curated text + chunk-6 misses; "
            "write proposals to staging + auto-accepted instances to data."
        ),
    )
    extract_parser = subparsers.add_parser(
        "extract",
        help=(
            "Extract salt<->property<->value measurements and salt<->role/reactor "
            "edges from linked sentences; write both stores + relations.jsonl."
        ),
    )
    extract_parser.add_argument(
        "--report",
        action="append",
        metavar="ID",
        help="Restrict extraction to this curated report id (repeatable). Default: all curated reports.",
    )
    extract_parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="Process only the first N of the (possibly --report-filtered) selection.",
    )

    subparsers.add_parser(
        "backfill-observations",
        help=(
            "Deterministic, inference-free backfill: re-scan both cached "
            "corpora and rebuild per-document/per-corpus observations for "
            "already-staged proposals, then remove the stale docFrequency "
            "scalars (proposal-observation-provenance D4)."
        ),
    )

    safety_parser = subparsers.add_parser(
        "safety",
        help=(
            "Safety-genre pipeline over the four IAEA/GIF/ORNL sources "
            "(design.md D8, ingest-iaea-safety chunk 11)."
        ),
    )
    safety_subparsers = safety_parser.add_subparsers(
        dest="safety_command", required=True
    )
    safety_subparsers.add_parser(
        "fetch",
        help="Fetch the cached safety-source PDFs (scripts/fetch-safety-sources.sh; idempotent).",
    )
    safety_subparsers.add_parser(
        "extract",
        help="pypdf-extract, normalize, and segment every cached safety-source PDF.",
    )
    safety_subparsers.add_parser(
        "documents",
        help="Write the four attributed safety Document provenance nodes to the graph.",
    )
    safety_subparsers.add_parser(
        "mine",
        help=(
            "Re-run mining for the safety genre against already-written "
            "segments/mentions, without re-running extract/link."
        ),
    )
    safety_subparsers.add_parser(
        "ingest",
        help=(
            "Run extract, documents, link, mine, and the second-phase safety "
            "relations extraction over the safety genre, in order."
        ),
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: parse args and dispatch to the matching subcommand handler."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = _build_parser()
    args = parser.parse_args(argv)
    config = Config.from_env()

    if args.command == "link":
        try:
            reports = _resolve_link_reports(
                curated.CURATED_REPORTS, args.report, args.limit
            )
        except ValueError as exc:
            print(f"link: {exc}", file=sys.stderr)
            return 1
        return _cmd_link(config, reports=reports)

    if args.command == "extract":
        try:
            reports = _resolve_link_reports(
                curated.CURATED_REPORTS, args.report, args.limit
            )
        except ValueError as exc:
            print(f"extract: {exc}", file=sys.stderr)
            return 1
        return _cmd_extract(config, reports=reports)

    if args.command == "safety":
        safety_handler = _SAFETY_HANDLERS[args.safety_command]
        return safety_handler(config)

    handler = _HANDLERS[args.command]
    return handler(config)


if __name__ == "__main__":
    raise SystemExit(main())
