"""Guarded ontology-mining integration test (mine-ontology-candidates,
OpenSpec tasks 8.8/8.9, design.md D8-D10).

Mirrors ``test_link_integration.py``/``test_integration.py``'s opt-in
pattern (see those modules' docstrings for the established guard style):
this module is skipped entirely during normal/CI collection (no stack, no
live GraphDB) and only runs once explicitly opted into via
``GRAPHDB_REQUIRED=1``. Once opted in, the test is a hard gate -- it FAILS
(rather than skips) if the live, SHACL-enabled ``msr`` repository is
unreachable, because passing here is the actual acceptance criterion for
tasks 8.8/8.9.

How to run it
--------------
Point at a live, SHACL-enabled GraphDB ``msr`` repository (already running)::

    GRAPHDB_REQUIRED=1 GRAPHDB_URL=http://localhost:7200 \\
        uv run --extra test python -m pytest extraction/tests/test_mine_integration.py -q

No live LLM is ever contacted -- an injected :class:`StubClassifier`
deterministically classifies the fixture's three candidates
(``solubility``/``graphite``/a fictitious salt-formula miss), honoring the
"Flash is stubbed in every test" rule (design.md D10) even in this guarded
integration module.

The fixture corpus is built fresh under pytest's ``tmp_path`` for each test
(a handful of ``msr-archive/*.txt`` OCR sidecars plus one curated report
directory's ``segments.jsonl``/``mentions.jsonl``/``normalized.txt``) --
never the real 637-doc corpus -- with ``salience_threshold=1`` so the small
fixture archive's single-occurrence term frequencies clear the bar.
``MSR_CORPUS_DIR`` is deliberately NOT consulted: each test is
self-contained and builds/tears down its own tmp corpus, so the module
works whether or not that variable happens to be set in the invoking shell.

TEARDOWN (critical -- the live ``msr`` repository is shared, non-ephemeral
state): every test in this module writes only deterministic, locally-known
IRIs (the mined candidates' own deterministic proposal/individual/evidence
IRIs for 8.8; a unique ``msrd:test-mine-shacl-*`` prefix for 8.9's
direct-write probes) and cleans every one of them up in a ``try/finally``
block, verified by an explicit post-teardown existence check at the end of
each test. Per-run ``urn:msr:run:mine/<ts>`` activity nodes and their
generation edges are cleaned via a ``urn:msr:run:mine/`` prefix match --
safe here because the 8.8 test confirms, before running, that
``msrd:activity-mine`` is not yet typed in ``urn:msr:data`` (i.e. no other
mine invocation has ever touched this repository), so any such node found
afterward is guaranteed to be ours.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("GRAPHDB_REQUIRED") != "1",
    reason=(
        "guarded mine-pipeline integration test skipped: set GRAPHDB_REQUIRED=1 "
        "(pointed at a live, SHACL-enabled `msr` GraphDB repository) to run it"
    ),
)

from msr_extraction.config import Config
from msr_extraction.graph_reader import CORE_GRAPHS
from msr_extraction.mining_types import term_slug
from msr_extraction.sparql import SparqlClient, ValidationError

MSR = "https://w3id.org/msr-kg/ontology#"
MSRD = "https://w3id.org/msr-kg/data#"

# A real curated report id: `novelty.mine_candidates`'s default `reports`
# param is the hardcoded `curated.CURATED_REPORTS` list, and
# `mine_runner.run_mine` exposes no override -- so the fixture report
# directory must use one of those ids for its segments/mentions to
# actually be read (any other curated id's segments.jsonl/mentions.jsonl
# are simply absent under our tmp corpus_dir and skipped with a warning,
# not an error).
REPORT = "ORNL-TM-2316"

SOLUBILITY_SENTENCE = "The solubility of PuF3 in LiF-BeF2 was measured at 280 mole %."
GRAPHITE_SENTENCE = "Graphite was used as the moderator material in the reactor core."

# Deliberately fictitious -- never appears in the real corpus or the live
# graph, so cleanup-by-IRI is exact and there is no risk of colliding with
# real data.
SALT_SURFACE = "TestMineSaltA9F2"
SALT_TERM = SALT_SURFACE.casefold()
SALT_SLUG = term_slug(SALT_TERM)
SALT_SENTENCE = f"A new compound {SALT_SURFACE} was observed forming a stable salt."

QUDT_PATH = Path(__file__).resolve().parents[2] / "ontology" / "qudt-units.json"

PROPOSAL_SOLUBILITY_IRI = f"{MSRD}proposal-property-solubility"
PROPOSAL_GRAPHITE_IRI = f"{MSRD}proposal-class-graphite"
GRAPHITE_RIDES_WITH_IRI = f"{MSRD}graphite"
SALT_INDIVIDUAL_IRI = f"{MSRD}{SALT_SLUG}"
ACTIVITY_MINE_IRI = f"{MSRD}activity-mine"

PROPOSAL_GRAPH_SOLUBILITY = "urn:msr:proposal/property-solubility"
PROPOSAL_GRAPH_GRAPHITE = "urn:msr:proposal/class-graphite"

# 8.9's direct-write probes -- unique, greppable test IRIs.
SHACL_GOOD_IRI = f"{MSRD}test-mine-shacl-good"
SHACL_BAD_NO_GENBY_IRI = f"{MSRD}test-mine-shacl-bad-nogenby"
SHACL_BAD_NO_DERIVED_IRI = f"{MSRD}test-mine-shacl-bad-noderived"
SHACL_DOC_IRI = f"{MSRD}test-mine-shacl-doc"


def _evidence_curie(report: str, start: int, end: int) -> str:
    """Mirror `proposals._evidence_iri`'s deterministic evidence-node scheme."""
    return f"msrd:evidence-{report}-{start}-{end}"


# --- Shared SPARQL helpers (mirrors test_link_integration.py/test_integration.py) --


def _sparql_select(config: Config, query: str) -> list[dict[str, dict[str, str]]]:
    import httpx

    endpoint = f"{config.graphdb_url}/repositories/{config.graphdb_repo}"
    response = httpx.post(
        endpoint,
        data={"query": query},
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/sparql-results+json",
        },
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()["results"]["bindings"]


def _sparql_ask(config: Config, query: str) -> bool:
    import httpx

    endpoint = f"{config.graphdb_url}/repositories/{config.graphdb_repo}"
    response = httpx.post(
        endpoint,
        data={"query": query},
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/sparql-results+json",
        },
        timeout=30.0,
    )
    response.raise_for_status()
    return bool(response.json()["boolean"])


def _core_restricted_ask(config: Config, query: str) -> bool:
    """ASK restricted to the three core graphs (mirrors `GraphReader`'s
    `default-graph-uri` enforcement) -- used to confirm a staged proposal is
    invisible to a core-dataset read."""
    import httpx

    params = [("query", query)]
    params.extend(("default-graph-uri", graph) for graph in CORE_GRAPHS)
    response = httpx.get(
        config.sparql_query_endpoint,
        params=params,
        headers={"Accept": "application/sparql-results+json"},
        timeout=30.0,
    )
    response.raise_for_status()
    return bool(response.json()["boolean"])


def _triple_count(config: Config, graph: str) -> int:
    bindings = _sparql_select(
        config,
        f"SELECT (COUNT(*) AS ?c) WHERE {{ GRAPH <{graph}> {{ ?s ?p ?o }} }}",
    )
    return int(bindings[0]["c"]["value"])


class StubClassifier:
    """Deterministic per-term classifier -- no live model (Flash is stubbed
    in every test, mine-ontology-candidates design.md D10, even in this
    guarded integration module). Matches on the literal `Candidate term:`
    line `triage._build_user_prompt` always emits."""

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if 'Candidate term: "solubility"' in user_prompt:
            return json.dumps({"kind": "property"})
        if 'Candidate term: "graphite"' in user_prompt:
            return json.dumps({"kind": "class", "broaderClass": "Moderator"})
        if f'Candidate term: "{SALT_TERM}"' in user_prompt:
            return json.dumps({"kind": "instance", "broaderClass": "msr:MoltenSalt"})
        # Any other lexical n-gram our small fixture prose happens to also
        # surface (e.g. "reactor core") is deliberately dropped rather than
        # guessed at -- only the three demo terms above are asserted on.
        return json.dumps({"unexpected": "shape"})


def _write_curated_report(config: Config, report: str, sentences: list[str]) -> list[dict]:
    """Write `normalized.txt` + `segments.jsonl` for `report`, one segment per sentence.

    Mirrors test_novelty.py's helper of the same name: offsets are computed
    so `normalized_text[start:end] == sentence` holds exactly.
    """
    segments: list[dict] = []
    offset = 0
    for index, sentence in enumerate(sentences):
        if index > 0:
            offset += 1  # single-space separator
        start = offset
        end = start + len(sentence)
        segments.append(
            {
                "report": report,
                "index": index,
                "text": sentence,
                "char_start": start,
                "char_end": end,
            }
        )
        offset = end

    normalized_text = " ".join(sentences)
    normalized_path = config.normalized_path(report)
    normalized_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_path.write_text(normalized_text, encoding="utf-8")

    with config.segments_path(report).open("w", encoding="utf-8") as fh:
        for seg in segments:
            fh.write(json.dumps(seg))
            fh.write("\n")

    return segments


def _write_mentions(config: Config, report: str, records: list[dict]) -> None:
    path = config.mentions_path(report)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record))
            fh.write("\n")


def _write_archive_docs(config: Config, docs: dict[str, str]) -> None:
    config.archive_dir.mkdir(parents=True, exist_ok=True)
    for name, text in docs.items():
        (config.archive_dir / name).write_text(text, encoding="utf-8")


def _build_mine_config(tmp_path: Path) -> tuple[Config, dict]:
    """Build the fixture corpus under `tmp_path` and return `(config, segments)`.

    `salience_threshold=1` so the small fixture archive's single-occurrence
    term frequencies clear the bar (task 8.8 instruction). `GRAPHDB_URL`/
    `GRAPHDB_REPO` are the only environment-sourced fields.
    """
    seed_config = Config(corpus_dir=tmp_path)
    segments = _write_curated_report(
        seed_config,
        REPORT,
        [SOLUBILITY_SENTENCE, GRAPHITE_SENTENCE, SALT_SENTENCE],
    )
    sol_seg, graphite_seg, salt_seg = segments

    salt_offset_in_sentence = salt_seg["text"].index(SALT_SURFACE)
    salt_char_start = salt_seg["char_start"] + salt_offset_in_sentence
    salt_char_end = salt_char_start + len(SALT_SURFACE)

    _write_mentions(
        seed_config,
        REPORT,
        [
            {
                "status": "novel",
                "surface_form": SALT_SURFACE,
                "char_start": salt_char_start,
                "char_end": salt_char_end,
            }
        ],
    )

    _write_archive_docs(
        seed_config,
        {
            "doc-solubility.txt": (
                "A survey of solubility behavior in fluoride salt mixtures."
            ),
            "doc-graphite.txt": (
                "Graphite blocks moderate the neutron flux in the core."
            ),
            "doc-salt.txt": f"Trace mention of {SALT_SURFACE} in an unrelated survey.",
            "doc-misc.txt": "A general-purpose filler document about corrosion testing.",
        },
    )

    config = Config(
        graphdb_url=os.environ.get("GRAPHDB_URL", "http://localhost:7200"),
        graphdb_repo=os.environ.get("GRAPHDB_REPO", "msr"),
        corpus_dir=tmp_path,
        salience_threshold=1,
    )
    return config, {"solubility": sol_seg, "graphite": graphite_seg}


def _teardown_mine_run(config: Config, evidence_curies: list[str]) -> None:
    """Remove every triple/graph the 8.8 test could have written.

    Safe as a broad `urn:msr:run:mine/` prefix match in `urn:msr:provenance`
    because the test confirms beforehand that no other mine invocation has
    ever touched this repository (`msrd:activity-mine` is untyped before it
    runs) -- so any such node found afterward is guaranteed to be ours.
    """
    client = SparqlClient.from_config(config)

    client.update(f"DROP SILENT GRAPH <{PROPOSAL_GRAPH_SOLUBILITY}>")
    client.update(f"DROP SILENT GRAPH <{PROPOSAL_GRAPH_GRAPHITE}>")

    prefixes = "PREFIX msrd: <https://w3id.org/msr-kg/data#>\n"
    client.update(
        prefixes
        + "DELETE WHERE { GRAPH <urn:msr:staging> { msrd:proposal-property-solubility ?p ?o } }"
    )
    client.update(
        prefixes
        + "DELETE WHERE { GRAPH <urn:msr:staging> { msrd:proposal-class-graphite ?p ?o } }"
    )
    for evidence_curie in evidence_curies:
        client.update(
            prefixes
            + f"DELETE WHERE {{ GRAPH <urn:msr:staging> {{ {evidence_curie} ?p ?o }} }}"
        )
    client.update(
        prefixes + f"DELETE WHERE {{ GRAPH <urn:msr:data> {{ msrd:{SALT_SLUG} ?p ?o }} }}"
    )
    client.update(
        prefixes + "DELETE WHERE { GRAPH <urn:msr:data> { msrd:activity-mine ?p ?o } }"
    )
    # `DELETE WHERE { ... FILTER(...) }` shorthand does not permit a FILTER
    # (its pattern doubles as the delete template) -- the full DELETE
    # { template } WHERE { pattern } form is required whenever a FILTER is
    # needed to select what to delete.
    client.update(
        "PREFIX prov: <http://www.w3.org/ns/prov#>\n"
        "DELETE { GRAPH <urn:msr:provenance> { ?fact prov:wasGeneratedBy ?run } }\n"
        "WHERE {\n"
        "  GRAPH <urn:msr:provenance> {\n"
        "    ?fact prov:wasGeneratedBy ?run .\n"
        '    FILTER(STRSTARTS(STR(?run), "urn:msr:run:mine/"))\n'
        "  }\n"
        "}"
    )
    client.update(
        "DELETE { GRAPH <urn:msr:provenance> { ?run ?p ?o } }\n"
        "WHERE {\n"
        "  GRAPH <urn:msr:provenance> {\n"
        "    ?run ?p ?o .\n"
        '    FILTER(STRSTARTS(STR(?run), "urn:msr:run:mine/"))\n'
        "  }\n"
        "}"
    )


def test_mine_run_stages_proposals_auto_accepts_instance_and_is_idempotent(
    tmp_path: Path,
) -> None:
    """8.8: a full `run_mine` invocation against the live GraphDB, with an
    injected StubClassifier (no live LLM), stages the solubility/graphite
    proposals, auto-accepts the salt-formula miss with full provenance, and
    re-running the pipeline leaves staging/proposal triple counts unchanged
    while provenance grows."""
    from msr_extraction import mine_runner
    from msr_extraction.graph_reader import GraphReader

    config, segments = _build_mine_config(tmp_path)
    reader = GraphReader.from_config(config)
    sparql = SparqlClient.from_config(config)
    classifier = StubClassifier()

    evidence_curies = [
        _evidence_curie(REPORT, segments["solubility"]["char_start"], segments["solubility"]["char_end"]),
        _evidence_curie(REPORT, segments["graphite"]["char_start"], segments["graphite"]["char_end"]),
    ]

    # Precondition: no other mine invocation has ever touched this repo --
    # this is what makes the broad `urn:msr:run:mine/` prefix-match teardown
    # safe (see _teardown_mine_run's docstring).
    assert not _sparql_ask(
        config, f"ASK {{ GRAPH <urn:msr:data> {{ <{ACTIVITY_MINE_IRI}> ?p ?o }} }}"
    ), "precondition failed: msrd:activity-mine already present -- a prior mine run left state behind"

    try:
        summary_1 = mine_runner.run_mine(
            config, reader=reader, client=classifier, sparql=sparql, qudt_path=QUDT_PATH
        )
        assert summary_1["candidates"] >= 3

        # -- staging: both proposals present with governance predicates --
        assert _sparql_ask(
            config,
            f"""
            PREFIX msr: <{MSR}>
            ASK {{ GRAPH <urn:msr:staging> {{
                <{PROPOSAL_SOLUBILITY_IRI}> a msr:ChangeProposal ;
                    msr:kind "property" ;
                    msr:reviewStatus "pending" ;
                    msr:hasEvidence ?ev .
            }} }}
            """,
        ), "expected msrd:proposal-property-solubility in urn:msr:staging with kind/reviewStatus/hasEvidence"

        assert _sparql_ask(
            config,
            f"""
            PREFIX msr: <{MSR}>
            ASK {{ GRAPH <urn:msr:staging> {{
                <{PROPOSAL_GRAPHITE_IRI}> a msr:ChangeProposal ;
                    msr:kind "class" ;
                    msr:reviewStatus "pending" ;
                    msr:hasEvidence ?ev .
            }} }}
            """,
        ), "expected msrd:proposal-class-graphite in urn:msr:staging with kind/reviewStatus/hasEvidence"

        # -- proposed axioms live in the dedicated urn:msr:proposal/... graphs --
        assert _sparql_ask(
            config,
            f"""
            PREFIX msr: <{MSR}>
            ASK {{ GRAPH <{PROPOSAL_GRAPH_SOLUBILITY}> {{ msr:solubility a msr:PhysicalProperty }} }}
            """,
        ), "expected the proposed msr:PhysicalProperty axiom in urn:msr:proposal/property-solubility"

        assert _sparql_ask(
            config,
            f"""
            PREFIX msr: <{MSR}>
            PREFIX owl: <http://www.w3.org/2002/07/owl#>
            ASK {{ GRAPH <{PROPOSAL_GRAPH_GRAPHITE}> {{ msr:Moderator a owl:Class }} }}
            """,
        ), "expected the proposed msr:Moderator owl:Class axiom in urn:msr:proposal/class-graphite"

        # the graphite class candidate's rides-with individual also lands in
        # its proposal graph, not urn:msr:data, until approval
        assert _sparql_ask(
            config,
            f"""
            PREFIX msr: <{MSR}>
            ASK {{ GRAPH <{PROPOSAL_GRAPH_GRAPHITE}> {{
                <{GRAPHITE_RIDES_WITH_IRI}> msr:autoAccepted true .
            }} }}
            """,
        ), "expected the graphite rides-with individual in urn:msr:proposal/class-graphite"

        # -- the auto-accepted salt instance carries full provenance in urn:msr:data --
        assert _sparql_ask(
            config,
            f"""
            PREFIX msr: <{MSR}>
            PREFIX prov: <http://www.w3.org/ns/prov#>
            ASK {{ GRAPH <urn:msr:data> {{
                <{SALT_INDIVIDUAL_IRI}> a msr:MoltenSalt ;
                    msr:autoAccepted true ;
                    prov:wasGeneratedBy <{ACTIVITY_MINE_IRI}> ;
                    prov:wasDerivedFrom ?doc .
            }} }}
            """,
        ), (
            "expected the auto-accepted salt individual in urn:msr:data carrying both "
            "prov:wasGeneratedBy msrd:activity-mine and prov:wasDerivedFrom -- its "
            "presence is what proves it passed CatalogIndividualProvenanceShape"
        )

        # -- the per-run activity + generation edges are in urn:msr:provenance --
        run_bindings = _sparql_select(
            config,
            f"""
            PREFIX prov: <http://www.w3.org/ns/prov#>
            SELECT DISTINCT ?run WHERE {{
                GRAPH <urn:msr:provenance> {{
                    <{SALT_INDIVIDUAL_IRI}> prov:wasGeneratedBy ?run .
                    ?run a prov:Activity .
                    FILTER(STRSTARTS(STR(?run), "urn:msr:run:mine/"))
                }}
            }}
            """,
        )
        assert run_bindings, (
            "expected a urn:msr:run:mine/<ts> prov:Activity node in urn:msr:provenance "
            "generating the auto-accepted salt individual"
        )

        # -- proposals are invisible via a core-dataset (GraphReader-style) read --
        assert not _core_restricted_ask(
            config,
            f"""
            PREFIX msr: <{MSR}>
            ASK {{ <{PROPOSAL_SOLUBILITY_IRI}> a msr:ChangeProposal }}
            """,
        ), "the staged proposal must be invisible to a core-graph-restricted (GraphReader) read"

        # -- ...but visible via a raw, unrestricted staging query --
        assert _sparql_ask(
            config,
            f"""
            PREFIX msr: <{MSR}>
            ASK {{ GRAPH <urn:msr:staging> {{ <{PROPOSAL_SOLUBILITY_IRI}> a msr:ChangeProposal }} }}
            """,
        ), "the staged proposal must be visible via a raw urn:msr:staging query"

        staging_count_1 = _triple_count(config, "urn:msr:staging")
        proposal_sol_count_1 = _triple_count(config, PROPOSAL_GRAPH_SOLUBILITY)
        proposal_graphite_count_1 = _triple_count(config, PROPOSAL_GRAPH_GRAPHITE)
        provenance_count_1 = _triple_count(config, "urn:msr:provenance")

        # -- second run: staging/proposal counts unchanged, provenance grows --
        summary_2 = mine_runner.run_mine(
            config, reader=reader, client=classifier, sparql=sparql, qudt_path=QUDT_PATH
        )
        assert summary_2["candidates"] >= 3

        staging_count_2 = _triple_count(config, "urn:msr:staging")
        proposal_sol_count_2 = _triple_count(config, PROPOSAL_GRAPH_SOLUBILITY)
        proposal_graphite_count_2 = _triple_count(config, PROPOSAL_GRAPH_GRAPHITE)
        provenance_count_2 = _triple_count(config, "urn:msr:provenance")

        assert staging_count_2 == staging_count_1, (
            f"urn:msr:staging triple count changed across re-runs: {staging_count_1} -> {staging_count_2}"
        )
        assert proposal_sol_count_2 == proposal_sol_count_1, (
            f"{PROPOSAL_GRAPH_SOLUBILITY} triple count changed across re-runs: "
            f"{proposal_sol_count_1} -> {proposal_sol_count_2}"
        )
        assert proposal_graphite_count_2 == proposal_graphite_count_1, (
            f"{PROPOSAL_GRAPH_GRAPHITE} triple count changed across re-runs: "
            f"{proposal_graphite_count_1} -> {proposal_graphite_count_2}"
        )
        assert provenance_count_2 > provenance_count_1, (
            f"expected urn:msr:provenance to grow across re-runs (a new per-run activity "
            f"+ generation edges), was {provenance_count_1} then {provenance_count_2}"
        )
    finally:
        _teardown_mine_run(config, evidence_curies)

    # -- verify teardown: every subject we wrote is gone --
    assert not _sparql_ask(
        config, f"ASK {{ GRAPH <urn:msr:staging> {{ <{PROPOSAL_SOLUBILITY_IRI}> ?p ?o }} }}"
    )
    assert not _sparql_ask(
        config, f"ASK {{ GRAPH <urn:msr:staging> {{ <{PROPOSAL_GRAPHITE_IRI}> ?p ?o }} }}"
    )
    assert _triple_count(config, PROPOSAL_GRAPH_SOLUBILITY) == 0
    assert _triple_count(config, PROPOSAL_GRAPH_GRAPHITE) == 0
    assert not _sparql_ask(
        config, f"ASK {{ GRAPH <urn:msr:data> {{ <{SALT_INDIVIDUAL_IRI}> ?p ?o }} }}"
    )
    assert not _sparql_ask(
        config, f"ASK {{ GRAPH <urn:msr:data> {{ <{ACTIVITY_MINE_IRI}> ?p ?o }} }}"
    )
    assert not _sparql_ask(
        config,
        'ASK { GRAPH <urn:msr:provenance> { ?run ?p ?o . '
        'FILTER(STRSTARTS(STR(?run), "urn:msr:run:mine/")) } }',
    )


def test_shacl_rejects_catalog_individual_missing_required_provenance_edge() -> None:
    """8.9: direct writes (no LLM involved) against the live, SHACL-enabled
    repo -- a catalog individual with both required prov edges succeeds;
    one missing either edge is atomically rejected by SHACL and leaves no
    trace."""
    config = Config(
        graphdb_url=os.environ.get("GRAPHDB_URL", "http://localhost:7200"),
        graphdb_repo=os.environ.get("GRAPHDB_REPO", "msr"),
    )
    client = SparqlClient.from_config(config)

    prefixes = (
        "PREFIX msr: <https://w3id.org/msr-kg/ontology#>\n"
        "PREFIX msrd: <https://w3id.org/msr-kg/data#>\n"
        "PREFIX prov: <http://www.w3.org/ns/prov#>\n"
    )

    try:
        # -- a fully provenance-complete individual is accepted --
        client.update(
            prefixes
            + "INSERT DATA { GRAPH <urn:msr:data> {\n"
            "    msrd:test-mine-shacl-good a msr:MoltenSalt ;\n"
            "        prov:wasGeneratedBy msrd:activity-mine ;\n"
            "        prov:wasDerivedFrom msrd:test-mine-shacl-doc .\n"
            "} }"
        )
        assert _sparql_ask(
            config, f"ASK {{ GRAPH <urn:msr:data> {{ <{SHACL_GOOD_IRI}> a <{MSR}MoltenSalt> }} }}"
        ), "expected the provenance-complete individual to persist"

        # -- missing prov:wasGeneratedBy is rejected atomically --
        with pytest.raises(ValidationError) as excinfo_nogenby:
            client.update(
                prefixes
                + "INSERT DATA { GRAPH <urn:msr:data> {\n"
                "    msrd:test-mine-shacl-bad-nogenby a msr:MoltenSalt ;\n"
                "        prov:wasDerivedFrom msrd:test-mine-shacl-doc .\n"
                "} }"
            )
        nogenby_report = excinfo_nogenby.value.report
        assert nogenby_report, "expected the SHACL rejection to carry a non-empty validation report"
        nogenby_lowered = nogenby_report.lower()
        assert any(
            marker in nogenby_lowered
            for marker in ("wasgeneratedby", "validationreport", "conforms", "sh:result", "shacl")
        ), f"expected SHACL-report evidence in rejection body, got: {nogenby_report!r}"
        assert not _sparql_ask(
            config,
            f"ASK {{ GRAPH <urn:msr:data> {{ <{SHACL_BAD_NO_GENBY_IRI}> ?p ?o }} }}",
        ), "the rejected INSERT DATA must leave no triples for that subject"

        # -- missing prov:wasDerivedFrom is rejected atomically --
        with pytest.raises(ValidationError) as excinfo_noderived:
            client.update(
                prefixes
                + "INSERT DATA { GRAPH <urn:msr:data> {\n"
                "    msrd:test-mine-shacl-bad-noderived a msr:MoltenSalt ;\n"
                "        prov:wasGeneratedBy msrd:activity-mine .\n"
                "} }"
            )
        noderived_report = excinfo_noderived.value.report
        assert noderived_report, "expected the SHACL rejection to carry a non-empty validation report"
        noderived_lowered = noderived_report.lower()
        assert any(
            marker in noderived_lowered
            for marker in ("wasderivedfrom", "validationreport", "conforms", "sh:result", "shacl")
        ), f"expected SHACL-report evidence in rejection body, got: {noderived_report!r}"
        assert not _sparql_ask(
            config,
            f"ASK {{ GRAPH <urn:msr:data> {{ <{SHACL_BAD_NO_DERIVED_IRI}> ?p ?o }} }}",
        ), "the rejected INSERT DATA must leave no triples for that subject"
    finally:
        client.update(
            prefixes
            + "DELETE WHERE { GRAPH <urn:msr:data> { msrd:test-mine-shacl-good ?p ?o } }"
        )
        client.update(
            prefixes
            + "DELETE WHERE { GRAPH <urn:msr:data> { msrd:test-mine-shacl-bad-nogenby ?p ?o } }"
        )
        client.update(
            prefixes
            + "DELETE WHERE { GRAPH <urn:msr:data> { msrd:test-mine-shacl-bad-noderived ?p ?o } }"
        )
        # msrd:activity-mine itself is untyped by this test (only referenced
        # as an object) -- but the "good" probe's insert is the only source
        # of any msrd:test-mine-shacl-doc reference, so nothing else to clean.

    assert not _sparql_ask(
        config, f"ASK {{ GRAPH <urn:msr:data> {{ <{SHACL_GOOD_IRI}> ?p ?o }} }}"
    )
    assert not _sparql_ask(
        config, f"ASK {{ GRAPH <urn:msr:data> {{ <{SHACL_BAD_NO_GENBY_IRI}> ?p ?o }} }}"
    )
    assert not _sparql_ask(
        config, f"ASK {{ GRAPH <urn:msr:data> {{ <{SHACL_BAD_NO_DERIVED_IRI}> ?p ?o }} }}"
    )


# --- refine-mine-salience 7.5: exclusion-against-live-graph + triage-reject ---
#
# A real curated report id (`novelty.mine_candidates`'s default `reports`
# param is `curated.CURATED_REPORTS`, and `mine_runner.run_mine` exposes no
# override), distinct from the 8.8 test's `REPORT` above so the two tests'
# fixture corpora never share a report directory under their own `tmp_path`.
MINE_75_REPORT = "ORNL-TM-0728"

# A real msr:PhysicalProperty label already loaded in the live `msr` core
# dataset (confirmed via a live SPARQL read against http://localhost:7200
# while writing this test) -- the exclusion-against-a-real-core-label probe.
MINE_75_EXCLUDED_TERM = "density"

# A synthetic, concept-shaped noun phrase that is NOT modeled anywhere in the
# live core dataset (verified against a live dump of every skos:Concept/
# owl:Class/msr:MoltenSalt/msr:SaltRole label while writing this test) -- the
# "novel concept survives to a proposal" probe. Deliberately NOT
# "solubility"/"graphite": the design.md/task-contract note explicitly defers
# real-corpus solubility/graphite acceptance to the manual 8.1 gate, and (as
# it happens) "solubility" is already present as a live skos:Concept in this
# repository from earlier evolution runs, which would make it excluded here
# for the wrong reason (already-known, not a corpus miss).
MINE_75_NOVEL_TERM = "cesium migration behavior"

# A synthetic noun phrase the stubbed classifier explicitly rejects --
# proves an explicit `"kind":"reject"` triage verdict is counted
# `triage_rejected` and produces no proposal anywhere.
MINE_75_NOISE_TERM = "noise study artifact"

MINE_75_NOVEL_SLUG = term_slug(MINE_75_NOVEL_TERM)
MINE_75_NOISE_SLUG = term_slug(MINE_75_NOISE_TERM)


class _CapturingSparqlClient:
    """A capturing fake `SparqlClient` stand-in for 7.5's write side.

    Records every `update()` call's raw SPARQL body instead of sending it
    anywhere, so this guarded test's writes (staged proposals, provenance
    activity/generation-edge inserts) never touch the shared live `msr`
    repository -- only the injected real `GraphReader`'s reads (exclusion
    lookups, the KG-schema prompt prefix) hit the live graph. Matches the
    `SparqlClient.update(sparql_update: str) -> None` interface every
    `mine_runner`/`proposals`/`mine_provenance`/`auto_accept` write call site
    already depends on, so no source change is needed to inject it.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def update(self, sparql_update: str) -> None:
        self.calls.append(sparql_update)


class _Mine75StubClassifier:
    """Deterministic Completer stub for 7.5 -- never contacts a live model.

    Confirms the designated novel fixture concept
    (`MINE_75_NOVEL_TERM`) into a `property` proposal and explicitly rejects
    everything else: the designated noise candidate (`MINE_75_NOISE_TERM`)
    plus whatever else the tiny fixture prose incidentally surfaces (e.g.
    "salt mixture", "run", "engineer", "reviewer" chunks) -- keeping this
    test's assertions scoped to only the two designated fixture concepts.
    """

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if f'Candidate term: "{MINE_75_NOVEL_TERM}"' in user_prompt:
            return json.dumps({"kind": "property"})
        return json.dumps({"kind": "reject"})


def test_mine_excludes_real_core_label_rejects_noise_proposes_novel_concept(
    tmp_path: Path,
) -> None:
    """refine-mine-salience 7.5: novelty exclusion reads + triage reject
    verdict, exercised against the LIVE, SHACL-enabled `msr` repository.

    Wiring (per the refine-mine-salience 7.5 task contract):
    - `reader` is a REAL `GraphReader.from_config(config)` pointed at the
      live `msr` repository, so `build_exclusion_set`'s core-dataset reads
      hit real data -- proven by `MINE_75_EXCLUDED_TERM` ("density", a real
      `msr:PhysicalProperty` label) being excluded.
    - `client` is a stubbed `Completer` (`_Mine75StubClassifier`) that
      classifies the one designated novel concept and explicitly rejects
      every other candidate (including the designated noise candidate) --
      no live LLM is ever contacted.
    - `sparql` is a capturing fake (`_CapturingSparqlClient`), not a real
      `SparqlClient`, so this test's writes never touch the shared live
      `msr` repository at all -- no scratch-repo REST lifecycle or
      teardown is needed for the write side.

    NOTE (explicitly deferred): the real-corpus "solubility"/"graphite"
    acceptance demo is task 8.1's manual gate, not asserted here.
    """
    from msr_extraction import mine_runner, novelty
    from msr_extraction.graph_reader import GraphReader

    seed_config = Config(corpus_dir=tmp_path)
    _write_curated_report(
        seed_config,
        MINE_75_REPORT,
        [
            "The density of the salt mixture was studied during the run.",
            "The cesium migration behavior was analyzed carefully by the engineers.",
            "The noise study artifact was rejected outright by the reviewers.",
        ],
    )
    _write_mentions(seed_config, MINE_75_REPORT, [])

    config = Config(
        graphdb_url=os.environ.get("GRAPHDB_URL", "http://localhost:7200"),
        graphdb_repo=os.environ.get("GRAPHDB_REPO", "msr"),
        corpus_dir=tmp_path,
        # No archive/*.txt sidecars are written for this tiny fixture --
        # salience_threshold=0 makes the document-frequency floor a no-op
        # (score_document_frequency returns 0 for every term when
        # archive_dir is absent, and 0 >= 0 always clears the floor), per
        # the task contract's "or set salience_threshold=0" alternative.
        salience_threshold=0,
        mine_max_candidates=50,
    )

    reader = GraphReader.from_config(config)

    # -- novelty-level assertion: exclusion reads hit the REAL live core
    # dataset, and the tiny fixture's novel/noise concepts are enumerated --
    candidates = novelty.mine_candidates(config, reader, reports=[MINE_75_REPORT])
    candidate_terms = {c.term for c in candidates}

    assert MINE_75_EXCLUDED_TERM not in candidate_terms, (
        f"{MINE_75_EXCLUDED_TERM!r} matches a real core msr:PhysicalProperty "
        "label in the live msr repository and must be excluded by "
        "build_exclusion_set's core-dataset read"
    )
    assert MINE_75_NOVEL_TERM in candidate_terms
    assert MINE_75_NOISE_TERM in candidate_terms
    assert len(candidates) <= config.mine_max_candidates

    # -- end-to-end run_mine: triage confirms/rejects, proposals are staged
    # (into the capturing fake sparql client only -- never the live graph) --
    sparql = _CapturingSparqlClient()
    classifier = _Mine75StubClassifier()

    summary = mine_runner.run_mine(
        config, reader=reader, client=classifier, sparql=sparql, qudt_path=QUDT_PATH
    )

    assert summary["candidates"] <= config.mine_max_candidates
    assert summary["triage_rejected"] >= 1, (
        "expected at least the designated noise candidate to be counted "
        "triage_rejected"
    )

    all_writes = "\n---\n".join(sparql.calls)
    assert f"proposal-property-{MINE_75_NOVEL_SLUG}" in all_writes, (
        "expected the novel concept to survive to a staged property proposal"
    )
    assert "msr:hasEvidence" in all_writes, (
        "expected the staged proposal to carry evidence"
    )
    assert f"proposal-property-{MINE_75_EXCLUDED_TERM}" not in all_writes, (
        f"the excluded core-label term {MINE_75_EXCLUDED_TERM!r} must never "
        "reach a staged proposal"
    )
    for rejected_kind in ("property", "class", "instance", "relation"):
        assert f"proposal-{rejected_kind}-{MINE_75_NOISE_SLUG}" not in all_writes, (
            "the stubbed-reject noise candidate must produce NO proposal "
            f"(kind={rejected_kind})"
        )
