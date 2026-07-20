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

from msr_extraction import (
    acquisition,
    curated,
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
    documents.write_documents(curated_records, client)
    provenance.write_activity(run_ts, client)
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
    documents.write_documents(curated_records, client)
    provenance.write_activity(run_ts, client)

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

    Generates a single run timestamp for this invocation (design.md D2/D6)
    and writes one timestamped extraction-run `Activity` record after all
    reports have been linked, so every mention written across the whole
    invocation is covered by the same `urn:msr:run:extraction/<ts>` graph.
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
            return result.status, result.target_iri

    else:
        logger.warning("link: DEEPSEEK_BASE_URL not configured; layer 5 spans fall to novel")

    sparql = SparqlClient.from_config(config)
    run_ts = provenance.run_timestamp()

    logger.info("link: %d curated report(s) to process", len(reports))
    for report in reports:
        segments_path = config.segments_path(report)
        if not segments_path.exists():
            logger.warning("link: report=%s missing %s, skipping", report, segments_path)
            continue

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
        mentions.write_mentions(linked_mentions, sparql)

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

    provenance.write_activity(run_ts, sparql)
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
