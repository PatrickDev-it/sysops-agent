"""The CLI contract: what an operator or a scheduler observes.

`main.py` was at 0% coverage. It is small, but it owns three things that are externally
observable and were all wrong: the exit code (always 0, so no caller could distinguish
completed from refused from gave-up), the startup preflight (absent, so a missing GGUF
surfaced as a 180 s boot-loop timeout), and the workspace default (the home directory).
"""

import sys

import pytest
from src import main as main_mod
from src.verdict import RunVerdict


@pytest.fixture
def cli(monkeypatch, tmp_path):
    """Drive cli_entry with a scripted verdict and no real agent behind it."""
    recorded = {}

    class _Orch:
        def __init__(self, workspace=None):
            recorded["workspace"] = workspace

        def run(self, goal):
            recorded["goal"] = goal
            return recorded.get("verdict", RunVerdict.COMPLETE)

    monkeypatch.setattr(main_mod, "Orchestrator", _Orch)
    monkeypatch.setattr(main_mod.config, "validate", lambda: recorded.get("problems", []))
    recorded["ws"] = tmp_path
    return recorded


def _run(argv):
    with pytest.raises(SystemExit) as exc:
        main_mod.cli_entry()
    return exc.value.code


@pytest.mark.parametrize(
    "verdict,code",
    [
        (RunVerdict.COMPLETE, 0),
        (RunVerdict.INCOMPLETE, 1),
        (RunVerdict.REFUSED, 2),
        (RunVerdict.ERROR, 3),
        (RunVerdict.ABORTED, 130),
    ],
)
def test_the_verdict_reaches_the_exit_code(cli, monkeypatch, verdict, code):
    """The process used to exit 0 on every path, so automation read every outcome as success."""
    cli["verdict"] = verdict
    monkeypatch.setattr(sys, "argv", ["sistemista", "do a thing", "--workspace", str(cli["ws"])])
    assert _run(sys.argv) == code


def test_a_broken_configuration_stops_before_the_agent_is_built(cli, monkeypatch, capsys):
    """A missing GGUF used to surface only as a 180 s boot-loop timeout, and a port collision
    not at all — health() would answer from whatever already owned the port."""
    cli["problems"] = ["NAV_MODEL not found: models/nav.gguf", "llama-server not found"]
    monkeypatch.setattr(sys, "argv", ["sistemista", "do a thing", "--workspace", str(cli["ws"])])

    assert _run(sys.argv) == 2
    err = capsys.readouterr().err
    assert "NAV_MODEL not found" in err and "llama-server not found" in err, (
        "an operator fixing a fresh install must see every problem at once"
    )
    assert "goal" not in cli, "the agent ran despite an unusable configuration"


def test_an_empty_goal_is_refused(cli, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["sistemista", "   ", "--workspace", str(cli["ws"])])
    monkeypatch.setattr(main_mod, "read_multiline_goal", lambda: "")
    assert _run(sys.argv) == 1


def test_an_oversized_goal_is_refused(cli, monkeypatch):
    """The goal is interpolated into every planner prompt; an unbounded paste evicts the fixed
    instruction block that the prefix cache and invariant #13 depend on."""
    monkeypatch.setattr(
        sys,
        "argv",
        ["sistemista", "x" * (main_mod.MAX_GOAL_CHARS + 1), "--workspace", str(cli["ws"])],
    )
    assert _run(sys.argv) == 1


def test_the_workspace_is_passed_through(cli, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["sistemista", "a goal", "--workspace", str(cli["ws"])])
    _run(sys.argv)
    assert cli["workspace"] == str(cli["ws"])


def test_an_omitted_workspace_is_refused_rather_than_defaulted(monkeypatch, capsys):
    """`--workspace` used to default to Path.home(), and a pre-flight keyword reflex then
    force-deleted every entry of it. The refusal is the whole point, so it is asserted against
    the REAL Orchestrator, not the stand-in."""
    monkeypatch.setattr(main_mod.config, "validate", lambda: [])
    monkeypatch.setattr(sys, "argv", ["sistemista", "clean up my PATH"])
    with pytest.raises(ValueError) as exc:
        main_mod.cli_entry()
    assert "--workspace is required" in str(exc.value)
