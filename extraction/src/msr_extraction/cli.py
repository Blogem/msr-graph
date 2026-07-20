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
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from msr_extraction import (
    acquisition,
    curated,
    disambig_cache,
    documents,
    linker,
    manifest,
    mentions,
    provenance,
    segmenter,
)
from msr_extraction.config import Config
from msr_extraction.disambiguation import FlashClient, disambiguate
from msr_extraction.graph_reader import GraphReader
from msr_extraction.kg_prompt import KGSchemaPromptCache
from msr_extraction.seeding import build_matcher
from msr_extraction.sparql import SparqlClient

logger = logging.getLogger(__name__)


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


_HANDLERS = {
    "acquire": _cmd_acquire,
    "manifest": _cmd_manifest,
    "normalize": _cmd_normalize,
    "documents": _cmd_documents,
    "ingest": _cmd_ingest,
    "link": _cmd_link,
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

    handler = _HANDLERS[args.command]
    return handler(config)


if __name__ == "__main__":
    raise SystemExit(main())
