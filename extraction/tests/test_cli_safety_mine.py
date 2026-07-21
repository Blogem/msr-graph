"""Tests for the standalone `safety mine` CLI subcommand (post-chunk-11
follow-up): lets a reviewer re-mine the safety genre against
already-written segments/mentions without re-running `safety
extract`/`safety link`.

Hermetic: `mine_runner.run_mine` is monkeypatched, so no live GraphDB/model
collaborator is ever constructed.
"""

from __future__ import annotations

import pytest

from msr_extraction import cli, mine_runner


def test_safety_mine_registered_in_safety_handlers() -> None:
    """`_SAFETY_HANDLERS["mine"]` must map to the new handler, alongside
    `fetch`/`extract`/`documents`/`ingest`."""
    assert cli._SAFETY_HANDLERS["mine"] is cli._cmd_safety_mine
    assert set(cli._SAFETY_HANDLERS) == {"fetch", "extract", "documents", "mine", "ingest"}


def test_safety_mine_help_parses() -> None:
    """`msr-extraction safety mine --help` parses (argparse's `--help`
    exits 0 after printing usage) -- proving the subparser is wired into
    the `safety` subcommand group."""
    parser = cli._build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["safety", "mine", "--help"])
    assert exc_info.value.code == 0


def test_safety_mine_parses_without_extra_arguments() -> None:
    """`safety mine` takes no positional/optional arguments of its own."""
    parser = cli._build_parser()
    args = parser.parse_args(["safety", "mine"])
    assert args.command == "safety"
    assert args.safety_command == "mine"


def test_cmd_safety_mine_invokes_run_mine_with_safety_genre(monkeypatch) -> None:
    """`_cmd_safety_mine` calls `mine_runner.run_mine(config, genre="safety")`
    (not the chemistry-default `run_mine(config)`) and prints a summary
    line carrying the same fields `_cmd_safety_ingest`'s mine stage logs."""
    calls: list[tuple[object, dict]] = []

    def fake_run_mine(config, **kwargs):
        calls.append((config, kwargs))
        return {
            "candidates": 7,
            "proposals_by_kind": {"class": 2, "property": 1},
            "auto_accepted": 3,
            "rejected": 0,
            "triage_rejected": 1,
            "dropped_malformed": 0,
            "dropped": 0,
        }

    monkeypatch.setattr(mine_runner, "run_mine", fake_run_mine)

    exit_code = cli._cmd_safety_mine(config=object())

    assert exit_code == 0
    assert len(calls) == 1
    _, kwargs = calls[0]
    assert kwargs.get("genre") == "safety"


def test_cmd_safety_mine_prints_summary_line(monkeypatch, capsys) -> None:
    """The printed summary line reports candidates/proposals/auto_accepted/
    rejected/dropped, matching `_cmd_mine`'s and `_cmd_safety_ingest`'s
    mine-stage line shape."""

    def fake_run_mine(config, **kwargs):
        return {
            "candidates": 4,
            "proposals_by_kind": {"class": 1},
            "auto_accepted": 0,
            "rejected": 1,
            "triage_rejected": 2,
            "dropped_malformed": 0,
            "dropped": 0,
        }

    monkeypatch.setattr(mine_runner, "run_mine", fake_run_mine)

    cli._cmd_safety_mine(config=object())

    out = capsys.readouterr().out
    assert "safety mine:" in out
    assert "candidates=4" in out
    assert "proposals=[class=1]" in out
    assert "auto_accepted=0" in out
    assert "rejected=1" in out
    assert "dropped=0" in out
