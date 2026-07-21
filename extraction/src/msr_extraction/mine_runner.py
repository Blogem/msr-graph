"""The `mine` CLI umbrella: orchestrates the full ontology-mining pipeline.

Wires the six mining modules built in earlier tasks (novelty, triage,
proposals, auto_accept, mine_provenance, mining_types) into a single
end-to-end run (mine-ontology-candidates design.md, OpenSpec tasks
1.1-CLI/7.1): enumerate candidates -> triage each -> route
property/class/relation candidates through the QUDT-guarded proposal
bundler and instance candidates through the auto-accept/rides-with split
-> write everything -> return a run summary. `cli.py`'s `_cmd_mine` is a
thin wrapper around :func:`run_mine` that only prints the summary; all
the orchestration logic lives here so it can be unit-tested with injected
fakes.

Mirrors `_cmd_link`'s ordering discipline (cli.py): the stable
per-pipeline Activity typing and the per-run Activity *node* are written
to the graph *before* any fact (proposal/individual) is written, so a
crash mid-run never leaves a generation edge in `urn:msr:provenance`
pointing at an untyped run IRI.

Deliberately stdlib-only at module level (`os`/`logging`/`pathlib`) plus
this package's own zero-import-time-third-party-dependency modules, so
this module has no third-party import-time dependency (`openai`/`httpx`
stay deferred inside the reused `FlashClient`/`SparqlClient`/`GraphReader`
collaborators).
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from msr_extraction import auto_accept, mine_provenance as mp, novelty, proposals, triage
from msr_extraction.config import Config
from msr_extraction.disambiguation import FlashClient
from msr_extraction.graph_reader import GraphReader
from msr_extraction.kg_prompt import KGSchemaPromptCache
from msr_extraction.mining_types import (
    KIND_CLASS,
    KIND_INSTANCE,
    KIND_PROPERTY,
    KIND_REJECT,
    KIND_RELATION,
    Candidate,
    TriagedCandidate,
    safe_type_ref,
    term_slug,
)
from msr_extraction.safety_manifest import SAFETY_SOURCES
from msr_extraction.sparql import SparqlClient

logger = logging.getLogger(__name__)

#: Default vendored QUDT allowlist location, overridable via
#: `MSR_QUDT_UNITS_PATH` (mirrors `config.py`'s env-override convention,
#: but kept out of `Config` itself since this is the only caller).
_DEFAULT_QUDT_UNITS_PATH = "ontology/qudt-units.json"

#: The zeroed summary returned when no triage classifier is configured
#: (mirrors `_cmd_link`'s None-client handling) -- no candidates are even
#: enumerated, since triage is mandatory for every mined candidate.
_ZERO_SUMMARY = {
    "candidates": 0,
    "proposals_by_kind": {},
    "auto_accepted": 0,
    "rejected": 0,
    "triage_rejected": 0,
    "dropped_malformed": 0,
    "dropped": 0,
}


def _as_type_ref(value: str | None) -> str | None:
    """Normalize a placement class reference into a term usable as `a <type>`.

    A bare local name (no `:`/`://`, e.g. `"Moderator"` from a `class`-kind
    placement, or a core class name asserted without its prefix) becomes
    `msr:{value}`; a value that already looks like a CURIE (`msr:MoltenSalt`)
    or a full IRI (`https://...`) is returned unchanged (bracketed, if a
    full IRI). `None`/empty stays `None`. Delegates entirely to
    `mining_types.safe_type_ref`, so an unsafe value -- a SPARQL-breakout
    payload, stray punctuation, or anything else that would corrupt the
    generated `INSERT DATA` -- is rejected (`None`) here too, exactly the
    same as the `proposals.py` guard on the same placement field. This is
    the single normalization point shared by both the `instance`-kind
    auto-accept/rides-with individual and the `class`-kind rides-with
    individual, so the two paths can never diverge into different CURIE
    forms (or different safety guarantees) for the same kind of value.
    """
    return safe_type_ref(value)


def _first_evidence_document_iri(triaged: TriagedCandidate) -> str | None:
    """Return the document IRI of `triaged`'s earliest evidence, or `None`.

    Sorts evidence by `(report, start_offset, end_offset)` -- the same
    ordering `proposals.build_proposal_bundle` applies -- before taking the
    first, so the chosen document is deterministic regardless of the
    dict-iteration order the novelty miner collected evidence in.
    """
    evidence = triaged.candidate.evidence
    if not evidence:
        return None
    ordered = sorted(evidence, key=lambda e: (e.report, e.start_offset, e.end_offset))
    return ordered[0].document_iri


def _default_qudt_path() -> Path:
    return Path(os.environ.get("MSR_QUDT_UNITS_PATH", _DEFAULT_QUDT_UNITS_PATH))


def _triage_worker(
    candidate: Candidate,
    prompt_prefix: str,
    client: FlashClient,
    *,
    genre: str = "chemistry",
) -> TriagedCandidate | None:
    """Run :func:`triage.triage_candidate` for one candidate, defensively.

    `triage.triage_candidate` already never raises for model/JSON anomalies
    (it returns `None` for those); this wrapper additionally catches ANY
    other unexpected exception (e.g. a transient network error the retry
    logic in `FlashClient` didn't absorb) and treats it the same way -- the
    candidate is dropped, never propagated to crash the thread pool or
    `run_mine` itself. `genre` (chunk 11 / ingest-iaea-safety D3, task 3.2)
    is threaded through unchanged to `triage.triage_candidate`.
    """
    try:
        return triage.triage_candidate(candidate, prompt_prefix, client, genre=genre)
    except Exception:  # noqa: BLE001 - triage anomalies must never crash the pool
        logger.warning("mine: candidate=%r triage raised unexpectedly; dropped", candidate.term)
        return None


def _triage_all(
    candidates: list[Candidate],
    prompt_prefix: str,
    client: FlashClient,
    max_workers: int,
    *,
    genre: str = "chemistry",
) -> list[tuple[Candidate, TriagedCandidate | None]]:
    """Triage every candidate concurrently, returning results in `candidates`
    order (mirrors `_cmd_link`'s `prewarm_report` concurrency pattern:
    `ThreadPoolExecutor` + `as_completed`, `Completer.complete` calls are
    blocking network I/O so threads -- not processes -- are the right tool,
    and `FlashClient` is a shared thread-safe pooled client). `genre`
    (chunk 11 / ingest-iaea-safety D3, task 3.2) is threaded through
    unchanged to every :func:`_triage_worker` call.

    Results are collected into a list pre-sized to `candidates` and written
    back by index, so completion order (which is non-deterministic under
    concurrency) never affects the returned order: Phase 2 in `run_mine`
    always iterates this in the original, novelty-sorted candidate order,
    making the whole pipeline's routing/writes/counts deterministic
    regardless of which Flash call finishes first.
    """
    results: list[TriagedCandidate | None] = [None] * len(candidates)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_index = {
            pool.submit(_triage_worker, candidate, prompt_prefix, client, genre=genre): index
            for index, candidate in enumerate(candidates)
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            results[index] = future.result()
    return list(zip(candidates, results))


def run_mine(
    config: Config,
    *,
    reader: GraphReader | None = None,
    client: FlashClient | None = None,
    sparql: SparqlClient | None = None,
    qudt_path: Path | None = None,
    genre: str = "chemistry",
) -> dict:
    """Run the full mine pipeline once and return a summary dict.

    Collaborators (`reader`/`client`/`sparql`) are injectable for testing;
    any left `None` is built from `config` (mirrors `_cmd_link`'s
    collaborator-construction style). `genre` (keyword-only, default
    `"chemistry"` -- chunk 11 / ingest-iaea-safety D3, task 3.2) is threaded
    unchanged to `novelty.mine_candidates` (candidate enumeration) and to
    every triage call (`_triage_all`/`triage.triage_candidate`); the
    `genre="chemistry"` default reproduces this function's pre-chunk-11
    behavior exactly. `genre="safety"` additionally passes `reports=` as
    the safety-manifest source ids (`safety_manifest.SAFETY_SOURCES`)
    instead of `novelty.mine_candidates`' `CURATED_REPORTS` default, so
    enumeration/scoring reads the safety corpus's own documents rather than
    silently falling back to the chemistry corpus's report ids. Orchestration:

    1. Build/accept collaborators, the cached KG-schema prompt prefix, and
       the known-IRI set.
    2. If no triage classifier is configured (`client is None`), log a
       warning and return a zeroed summary without writing anything --
       mining has no fallback path the way `link`'s layer-5 spans do; no
       triage means nothing to mine.
    3. Generate one run timestamp and write the stable + per-run Activity
       nodes *before* any fact write (closes the same crash window
       `_cmd_link` closes).
    4. Load the QUDT allowlist.
    5. Enumerate novelty candidates.
    6. Triage each. A malformed/unrecognized triage result (`None`) is
       counted `dropped_malformed`; an explicit reject verdict
       (`KIND_REJECT`, design.md D4) is counted `triage_rejected` and
       produces no proposal -- both are logged and distinct from each
       other and from the QUDT-allowlist `rejected` count below. Otherwise
       route `property`/`relation`/`class` through the QUDT-guarded
       proposal bundler (`class` additionally builds and rides its
       proposal's companion individual, per design.md D7/D8 and the
       `graphite` demo), and `instance` through the auto-accept/rides-with
       split (`instance` candidates that resolve against neither core
       schema nor a proposal bundle are out of scope and dropped, logged).
    7. Write auto-accepted individuals (and their own generation edges).
    8. Attribute every proposal resource and rides-with individual to the
       run node via one batch of generation edges into
       `urn:msr:provenance` (append-only; `write_auto_accepted` already
       covers its own individuals).
    9. Return the run summary.
    """
    reader = reader if reader is not None else GraphReader.from_config(config)
    sparql = sparql if sparql is not None else SparqlClient.from_config(config)
    client = client if client is not None else FlashClient.from_config(config)
    prompt_prefix = KGSchemaPromptCache().get(reader)
    known_iris = reader.known_iris()

    if client is None:
        logger.warning("mine: DEEPSEEK_BASE_URL not configured; no triage possible")
        return dict(_ZERO_SUMMARY)

    run_ts = mp.run_timestamp()
    mp.write_stable_activity(sparql)
    mp.write_activity(run_ts, sparql)

    allowlist = proposals.load_qudt_allowlist(qudt_path or _default_qudt_path())

    # NOTE: `genre` is passed only when non-default so that a caller who has
    # monkeypatched `novelty.mine_candidates` with a fixed 2-positional-arg
    # test double (as the chemistry-genre test suite does) keeps working
    # unmodified -- the extra keyword is never sent on the byte-identical
    # `genre="chemistry"` default path. `genre="safety"` additionally passes
    # `reports=` as the safety-manifest source ids -- otherwise
    # `novelty.mine_candidates` would default `reports` to
    # `curated.CURATED_REPORTS` (the chemistry corpus's report ids) even
    # though `genre="safety"` -- so enumeration/scoring would look up those
    # chemistry ids in the safety cache and silently enumerate nothing.
    if genre == "chemistry":
        candidates = novelty.mine_candidates(config, reader)
    elif genre == "safety":
        candidates = novelty.mine_candidates(
            config,
            reader,
            reports=[source.id for source in SAFETY_SOURCES],
            genre=genre,
        )
    else:
        candidates = novelty.mine_candidates(config, reader, genre=genre)
    logger.info("mine: %d candidate(s) surviving novelty scoring", len(candidates))

    proposals_by_kind: dict[str, int] = {}
    auto_accepted: list[auto_accept.Individual] = []
    fact_iris: list[str] = []
    rejected = 0
    triage_rejected = 0
    dropped_malformed = 0
    dropped = 0

    # Phase 1 (parallel, network-bound): triage every candidate concurrently
    # via a bounded thread pool -- one blocking Flash round-trip per
    # candidate, the same workload class `_cmd_link`'s layer-5 pre-warm
    # already parallelizes, and `FlashClient` is now a shared thread-safe
    # pooled client with transient-error retry. `_triage_all` returns
    # results in the original `candidates` order regardless of completion
    # order, so Phase 2 below stays byte-for-byte deterministic.
    triaged_candidates = _triage_all(
        candidates, prompt_prefix, client, config.disambig_concurrency, genre=genre
    )

    # Phase 2 (serial, unchanged logic): route each triage result through
    # the existing writes/counts, strictly in original candidate order.
    for candidate, triaged in triaged_candidates:
        if triaged is None:
            dropped_malformed += 1
            logger.info("mine: candidate=%r dropped by triage (malformed)", candidate.term)
            continue

        if triaged.kind == KIND_REJECT:
            triage_rejected += 1
            logger.info("mine: candidate=%r rejected by triage", candidate.term)
            continue

        kind = triaged.kind
        slug = term_slug(candidate.term)

        if kind == KIND_INSTANCE:
            document_iri = _first_evidence_document_iri(triaged)
            if document_iri is None:
                dropped += 1
                logger.info(
                    "mine: instance candidate=%r has no evidence; dropped", candidate.term
                )
                continue
            type_iri = _as_type_ref(triaged.placement.broader_class)
            if not type_iri:
                dropped += 1
                if triaged.placement.broader_class:
                    # A type *was* asserted but `safe_type_ref` rejected it as
                    # SPARQL-unsafe (breakout payload, stray punctuation, an
                    # unbracketable full IRI, ...) -- warn, since this is a
                    # rejected-as-unsafe LLM output, not merely an unset field.
                    logger.warning(
                        "mine: instance candidate=%r has an unsafe asserted "
                        "type (%r); dropped",
                        candidate.term,
                        triaged.placement.broader_class,
                    )
                else:
                    logger.info(
                        "mine: instance candidate=%r has no asserted type; dropped",
                        candidate.term,
                    )
                continue
            individual = auto_accept.Individual(
                iri=f"msrd:{slug}", type_iri=type_iri, document_iri=document_iri
            )
            if auto_accept.resolves_in_core(triaged, known_iris):
                auto_accepted.append(individual)
            else:
                # An instance typed only by a *proposed* class with no
                # owning class-proposal bundle here has nowhere to ride --
                # out of scope per design.md D8 (only the class-bundle
                # rides-with path below is supported).
                dropped += 1
                logger.info(
                    "mine: instance candidate=%r depends on unproposed schema "
                    "(type=%s); dropped",
                    candidate.term,
                    type_iri,
                )
            continue

        if kind == KIND_CLASS:
            bundle = proposals.build_proposal_bundle(triaged, allowlist, run_ts)
            if bundle is None:
                rejected += 1
                logger.info(
                    "mine: class candidate=%r rejected by QUDT-allowlist guard",
                    candidate.term,
                )
                continue

            extra_triples = ""
            rides_with_iri: str | None = None
            type_iri = _as_type_ref(triaged.placement.broader_class)
            document_iri = _first_evidence_document_iri(triaged)
            if type_iri and document_iri is not None:
                individual = auto_accept.Individual(
                    iri=f"msrd:{slug}", type_iri=type_iri, document_iri=document_iri
                )
                extra_triples = auto_accept.individual_triples(individual)
                rides_with_iri = individual.iri
            else:
                logger.info(
                    "mine: class candidate=%r has no rides-with individual "
                    "(missing type or evidence)",
                    candidate.term,
                )

            proposals.write_proposal(bundle, sparql, extra_proposal_triples=extra_triples)
            fact_iris.append(bundle.proposal_iri)
            if rides_with_iri is not None:
                fact_iris.append(rides_with_iri)
            proposals_by_kind[KIND_CLASS] = proposals_by_kind.get(KIND_CLASS, 0) + 1
            continue

        if kind in (KIND_PROPERTY, KIND_RELATION):
            bundle = proposals.build_proposal_bundle(triaged, allowlist, run_ts)
            if bundle is None:
                rejected += 1
                logger.info(
                    "mine: %s candidate=%r rejected by QUDT-allowlist guard",
                    kind,
                    candidate.term,
                )
                continue
            proposals.write_proposal(bundle, sparql)
            fact_iris.append(bundle.proposal_iri)
            proposals_by_kind[kind] = proposals_by_kind.get(kind, 0) + 1
            continue

        # Unreachable: the `KIND_REJECT` verdict is handled above, and
        # `triage.classify` otherwise only ever returns a kind in
        # `mining_types.VALID_KINDS`, which is exactly the four kinds
        # handled above.
        dropped += 1
        logger.warning(
            "mine: candidate=%r triaged to unknown kind=%r; dropped", candidate.term, kind
        )

    auto_accept.write_auto_accepted(auto_accepted, sparql, run_ts)

    if fact_iris:
        mp.write_generation_edges(sorted(set(fact_iris)), run_ts, sparql)

    return {
        "candidates": len(candidates),
        "proposals_by_kind": proposals_by_kind,
        "auto_accepted": len(auto_accepted),
        "rejected": rejected,
        "triage_rejected": triage_rejected,
        "dropped_malformed": dropped_malformed,
        "dropped": dropped,
    }
