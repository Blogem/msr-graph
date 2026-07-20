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
    KIND_RELATION,
    TriagedCandidate,
    safe_type_ref,
    term_slug,
)
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


def run_mine(
    config: Config,
    *,
    reader: GraphReader | None = None,
    client: FlashClient | None = None,
    sparql: SparqlClient | None = None,
    qudt_path: Path | None = None,
) -> dict:
    """Run the full mine pipeline once and return a summary dict.

    Collaborators (`reader`/`client`/`sparql`) are injectable for testing;
    any left `None` is built from `config` (mirrors `_cmd_link`'s
    collaborator-construction style). Orchestration:

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
    6. Triage each; route `property`/`relation`/`class` through the
       QUDT-guarded proposal bundler (`class` additionally builds and
       rides its proposal's companion individual, per design.md D7/D8 and
       the `graphite` demo), and `instance` through the
       auto-accept/rides-with split (`instance` candidates that resolve
       against neither core schema nor a proposal bundle are out of scope
       and dropped, logged).
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

    candidates = novelty.mine_candidates(config, reader)
    logger.info("mine: %d candidate(s) surviving novelty scoring", len(candidates))

    proposals_by_kind: dict[str, int] = {}
    auto_accepted: list[auto_accept.Individual] = []
    fact_iris: list[str] = []
    rejected = 0
    dropped = 0

    for candidate in candidates:
        triaged = triage.triage_candidate(candidate, prompt_prefix, client)
        if triaged is None:
            dropped += 1
            logger.info("mine: candidate=%r dropped by triage", candidate.term)
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

        # Unreachable: `triage.classify` only ever returns a kind in
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
        "dropped": dropped,
    }
