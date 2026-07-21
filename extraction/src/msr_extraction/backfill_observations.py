"""Deterministic, inference-free backfill of observations for staged proposals.

``proposal-observation-provenance`` design.md D4/D6, "Migration Plan" step 4,
tasks 4.1-4.4. Chunk-8's miner collapsed a candidate's corpus support into a
single ``msr:docFrequency`` scalar written onto its ``msr:ChangeProposal``
resource; re-mining a term already staged from another corpus (the same
``term + kind`` mints the identical deterministic proposal IRI) appended a
*second* scalar to the same resource rather than replacing it -- 19 proposals
now carry two conflicting ``docFrequency`` values, which crashes the review
queue's keyed list (duplicate ``id``, one row per value).

This module rebuilds the per-document/per-corpus ``msr:Observation`` records
those already-staged proposals should have had, by re-scanning the two
CACHED corpora (the msr-archive OCR sidecars and the safety corpus's
normalized text) and matching on each proposal's stored ``msr:term`` --
reusing :func:`msr_extraction.novelty.score_document_observations`
unchanged, since that IS the miner's own deterministic matching (the same
tokenize/n-gram path :func:`msr_extraction.novelty.score_document_frequency`
uses). No LLM/triage call is made anywhere in this module, and no corpus is
re-acquired -- everything is read from what is already on disk.

Orchestration (:func:`run_backfill`):

1. Read every staged proposal's IRI/kind/term
   (``graph_reader.GraphReader.read_change_proposals``, task 4.1).
2. Re-scan both cached corpora ONCE for the union of every proposal's term
   (never per-proposal -- the corpora are re-read exactly twice total,
   regardless of how many staged proposals share a term), via
   :func:`~msr_extraction.novelty.score_document_observations`.
3. For each proposal, gather its term's observations from BOTH corpora
   (this is what splits the 19 duplicated proposals by construction, task
   4.2: a proposal that was mined from both genres gets observations
   attributed to both ``corpus-chemistry`` and ``corpus-safety`` on the
   SAME resource, rather than two competing scalars) and write them via
   ``msr:hasObservation`` onto the proposal's *actual* resource IRI (read
   from the graph, never reconstructed).
4. Tag every scanned document with its corpus
   (``documents.write_corpus_tags``, task 4.2).
5. Remove the stale ``msr:docFrequency`` scalars (task 4.3).

**Idempotency (task 4.3, design.md "Risks/Trade-offs").** This backfill uses
a FIXED, deterministic run token (:data:`BACKFILL_RUN_TS`) rather than a
wall-clock timestamp, so every observation IRI
(``msrd:obs-{kind}-{slug}-{doc-slug}-backfill``) and its
``msr:observedInRun``/``prov:generatedAtTime`` content is byte-identical
across repeated invocations. Combined with deterministic IRIs and additive
``INSERT DATA`` (no blank nodes anywhere), re-running the whole backfill is a
pure set-semantics no-op -- nothing needs to be cleared first. This is the
"fixed backfill run id" alternative design.md's idempotency risk names
(rejected alternative: clear prior backfill observations before rewriting,
which would require tracking which observations came from this backfill
specifically).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from msr_extraction import documents, novelty, proposals
from msr_extraction import mine_provenance as mp
from msr_extraction.config import Config
from msr_extraction.corpora import CORPUS_CHEMISTRY, CORPUS_SAFETY
from msr_extraction.graph_reader import GraphReader
from msr_extraction.mining_types import term_slug
from msr_extraction.safety_manifest import SAFETY_SOURCES
from msr_extraction.sparql import SparqlClient

logger = logging.getLogger(__name__)

#: The fixed, deterministic backfill run token (see module docstring for the
#: idempotency rationale). Deliberately NOT `mine_provenance.run_timestamp()`
#: (a wall-clock ISO-8601 string) -- a fixed token is what makes every
#: observation IRI/block this backfill emits byte-identical on re-run.
BACKFILL_RUN_TS = "backfill"

_PREFIXES = """\
PREFIX msr: <https://w3id.org/msr-kg/ontology#>
PREFIX msrd: <https://w3id.org/msr-kg/data#>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>"""

#: `DELETE WHERE` shorthand (SPARQL 1.1 Update): the matched pattern IS the
#: template, so this removes every `<proposal> msr:docFrequency ?v` triple
#: in `urn:msr:staging` -- the stale scalar chunk-8's miner wrote, now
#: superseded by the observation nodes this backfill just wrote (task 4.3).
_DELETE_DOC_FREQUENCY_UPDATE = """\
PREFIX msr: <https://w3id.org/msr-kg/ontology#>
DELETE WHERE {
  GRAPH <urn:msr:staging> {
    ?proposal msr:docFrequency ?v .
  }
}"""


def _indent(block: str) -> str:
    """Indent every line of `block` by four spaces (mirrors `proposals.py`)."""
    return "\n".join(f"    {line}" for line in block.splitlines())


def _observations_insert_data(
    proposal_term: str, observation_iris: list[str], observation_blocks: list[str]
) -> str:
    """Return an `INSERT DATA` update linking `proposal_term` to its rebuilt
    observation nodes and asserting each node's own triples, all into
    `urn:msr:staging` (design.md D6).

    `proposal_term` is a ready-to-use RDF subject term -- a bracketed full
    IRI, since the backfill reads a proposal's resource IRI directly from
    the graph (`graph_reader.GraphReader.read_change_proposals`) rather than
    reconstructing a `msrd:` CURIE from `kind`/`term`. Mirrors
    `proposals.write_proposal`'s staging-graph `INSERT DATA` shape.
    Callers must only invoke this (and send its result) when
    `observation_blocks` is non-empty.
    """
    has_observation = f"{proposal_term} msr:hasObservation {', '.join(observation_iris)} ."
    body = "\n\n".join([has_observation, *observation_blocks])
    return (
        f"{_PREFIXES}\n"
        "INSERT DATA {\n"
        "  GRAPH <urn:msr:staging> {\n"
        f"{_indent(body)}\n"
        "  }\n"
        "}"
    )


@dataclass(frozen=True)
class BackfillSummary:
    """Run summary for one :func:`run_backfill` invocation (task 4.4)."""

    #: Number of staged proposals read from `urn:msr:staging`.
    proposals_processed: int
    #: Total observation nodes written across all proposals (0 for a
    #: proposal whose term matched neither corpus).
    observations_written: int
    #: Number of distinct documents tagged with `msr:inCorpus` (chemistry +
    #: safety, deduplicated within each corpus).
    documents_tagged: int
    #: Number of stale `msr:docFrequency` scalar triples removed from
    #: `urn:msr:staging`.
    doc_frequency_scalars_removed: int


def run_backfill(
    config: Config,
    *,
    reader: GraphReader | None = None,
    sparql: SparqlClient | None = None,
    run_ts: str = BACKFILL_RUN_TS,
) -> BackfillSummary:
    """Run the deterministic, inference-free observation backfill once.

    `reader`/`sparql` are injectable (mirrors `mine_runner.run_mine`'s
    collaborator-construction style) so tests can supply fakes; either left
    `None` is built from `config`. `run_ts` defaults to the fixed
    :data:`BACKFILL_RUN_TS` token (see module docstring for why a fixed
    token, not a wall-clock timestamp, is what makes this backfill
    idempotent) -- overridable only for tests that need to assert on a
    distinct run token.

    No LLM/triage call is made and no corpus is re-acquired: every read is
    either a graph SELECT (`read_change_proposals`) or a scan of already-
    cached corpus text on disk (`novelty.score_document_observations`).

    Mirrors `mine_runner.run_mine`'s ordering discipline: the stable
    per-pipeline Activity typing (`msrd:activity-mine` in `urn:msr:data`)
    and the per-run Activity *node* (`<urn:msr:run:mine/{run_ts}>` in
    `urn:msr:provenance`) are written *before* any observation/tag/delete,
    so every `msr:observedInRun` edge this backfill emits references a run
    IRI that is actually typed `a prov:Activity` -- closing the same crash
    window `_cmd_link`/`run_mine` close (a fact referencing an untyped run
    node). Because `run_ts` is the fixed `BACKFILL_RUN_TS` token by default,
    both writes are themselves idempotent (`write_activity` emits
    fixed-timestamp triples keyed by the fixed run IRI, and
    `write_stable_activity` is timestamp-free by construction) -- re-running
    the backfill still leaves triple counts stable.
    """
    reader = reader if reader is not None else GraphReader.from_config(config)
    sparql = sparql if sparql is not None else SparqlClient.from_config(config)

    mp.write_stable_activity(sparql)
    mp.write_activity(run_ts, sparql)

    staged = reader.read_change_proposals()
    logger.info("backfill: %d staged proposal(s) to process", len(staged))

    terms = {proposal.term for proposal in staged}

    # Re-scan each cached corpus exactly ONCE for the union of every staged
    # proposal's term -- never per-proposal -- so this stays cheap
    # regardless of how many proposals share a term (task 4.1).
    chemistry_observations = novelty.score_document_observations(
        terms, config, genre="chemistry"
    )
    safety_reports = [source.id for source in SAFETY_SOURCES]
    safety_observations = novelty.score_document_observations(
        terms, config, genre="safety", reports=safety_reports
    )

    observations_written = 0
    tagged_chemistry_docs: set[str] = set()
    tagged_safety_docs: set[str] = set()

    for proposal in staged:
        term_observations = list(chemistry_observations.get(proposal.term, ())) + list(
            safety_observations.get(proposal.term, ())
        )
        if not term_observations:
            logger.info(
                "backfill: proposal=%s term=%r matched neither cached corpus; "
                "no observations written",
                proposal.proposal_iri,
                proposal.term,
            )
            continue

        slug = term_slug(proposal.term)
        observation_iris, observation_blocks = proposals.build_observation_bundle(
            tuple(term_observations), proposal.kind, slug, run_ts
        )
        if observation_blocks:
            update = _observations_insert_data(
                f"<{proposal.proposal_iri}>", observation_iris, observation_blocks
            )
            sparql.update(update)
            observations_written += len(observation_blocks)

        for observation in term_observations:
            if observation.corpus == CORPUS_SAFETY:
                tagged_safety_docs.add(observation.document_iri)
            else:
                tagged_chemistry_docs.add(observation.document_iri)

    documents_tagged = 0
    if tagged_chemistry_docs:
        documents.write_corpus_tags(
            [f"<{doc}>" for doc in sorted(tagged_chemistry_docs)],
            CORPUS_CHEMISTRY,
            sparql,
        )
        documents_tagged += len(tagged_chemistry_docs)
    if tagged_safety_docs:
        documents.write_corpus_tags(
            [f"<{doc}>" for doc in sorted(tagged_safety_docs)],
            CORPUS_SAFETY,
            sparql,
        )
        documents_tagged += len(tagged_safety_docs)

    doc_frequency_scalars_removed = reader.count_doc_frequency_scalars()
    if doc_frequency_scalars_removed:
        sparql.update(_DELETE_DOC_FREQUENCY_UPDATE)

    summary = BackfillSummary(
        proposals_processed=len(staged),
        observations_written=observations_written,
        documents_tagged=documents_tagged,
        doc_frequency_scalars_removed=doc_frequency_scalars_removed,
    )
    logger.info(
        "backfill: proposals_processed=%d observations_written=%d "
        "documents_tagged=%d doc_frequency_scalars_removed=%d",
        summary.proposals_processed,
        summary.observations_written,
        summary.documents_tagged,
        summary.doc_frequency_scalars_removed,
    )
    return summary
