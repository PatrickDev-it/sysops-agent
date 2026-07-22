"""A hang is not a pass, and a crash is not a pass.

`agent_eval` caught `subprocess.TimeoutExpired` with a bare `pass`, set no flag, and ran
`subprocess.run(..., check=False)` so the exit code was discarded too. `_metrics_from_run` then
scored the FILESYSTEM alone and could not distinguish a finished run from a killed one.

This was not hypothetical. The stored baseline read:

    {"id": "node_backend", "passed": true, "verdict": "?", "wall_s": 600.0, "fail_reasons": []}

600.0 s is `--timeout` to the tenth of a second. The single "pass" behind `pass_rate: 0.333`
was the hang, so the true rate was 0/3 — and every future commit would have been compared
against that number. A patch that made the agent hang LESS would have registered as a
regression.

The sibling harness `stress_frameworks.py` already got this right. These tests keep the two
from diverging again.
"""

from benchmarks.agent_eval import _aggregate, _metrics_from_run
from benchmarks.stress_frameworks import CASES

CASE = CASES[0]


def _artifacts_present(tmp_path, case):
    """Build a workspace the scorer accepts, so `passed` turns only on run outcome."""
    for name in (
        "package.json",
        "server.js",
        "main.py",
        "manage.py",
        "index.html",
        "pyproject.toml",
        "tsconfig.json",
    ):
        (tmp_path / name).write_text("{}\n")
    return tmp_path


def test_a_timed_out_run_is_not_a_pass(tmp_path):
    ws = _artifacts_present(tmp_path, CASE)
    m = _metrics_from_run(CASE, ws, "TASK COMPLETE", 600.0, timed_out=True, exit_code=None)
    assert m["passed"] is False
    assert m["timed_out"] is True
    assert any("timed out" in r for r in m["fail_reasons"]), (
        "a timeout must be NAMED in the reasons, not merely flip a boolean"
    )


def test_a_crashed_run_is_not_a_pass(tmp_path):
    """The django case died in planning on a connection reset and left a partial workspace."""
    ws = _artifacts_present(tmp_path, CASE)
    m = _metrics_from_run(CASE, ws, "", 12.0, timed_out=False, exit_code=1)
    assert m["passed"] is False
    assert any("exited 1" in r for r in m["fail_reasons"])


def test_a_clean_run_with_artifacts_still_passes(tmp_path):
    """The guard must bound the pathological cases without breaking the normal one."""
    ws = _artifacts_present(tmp_path, CASE)
    m = _metrics_from_run(CASE, ws, "TASK COMPLETE", 42.0, timed_out=False, exit_code=0)
    assert m["passed"] is True
    assert m["fail_reasons"] == []


def test_the_exact_stored_baseline_row_would_now_fail(tmp_path):
    """Replays `node_backend` as recorded: artifacts on disk, no verdict line, killed at 600 s."""
    ws = _artifacts_present(tmp_path, CASE)
    m = _metrics_from_run(CASE, ws, "(no verdict line)", 600.0, timed_out=True, exit_code=None)
    assert m["passed"] is False, "this row is what made pass_rate 0.333 instead of 0.0"
    assert m["verdict"] == "?"


def test_timeouts_and_unparsed_verdicts_are_visible_in_the_aggregate():
    """Both used to hide: a timeout inside pass_rate, an unparsed verdict inside a
    false_complete_rate of 0.0 that read as honesty rather than as a broken parser."""
    results = [
        {
            "passed": False,
            "false_complete": False,
            "empty_files": 0,
            "hallucinated_cmd": False,
            "content_authored": False,
            "wall_s": 600.0,
            "timed_out": True,
            "verdict": "?",
        },
        {
            "passed": True,
            "false_complete": False,
            "empty_files": 0,
            "hallucinated_cmd": False,
            "content_authored": True,
            "wall_s": 40.0,
            "timed_out": False,
            "verdict": "COMPLETE",
        },
    ]
    agg = _aggregate(results)
    assert agg["timeout_rate"] == 0.5
    assert agg["unparsed_verdict_rate"] == 0.5
    assert agg["pass_rate"] == 0.5


def test_false_complete_still_fires_on_a_real_overclaim(tmp_path):
    """The honesty metric must survive the change: agent says COMPLETE, scorer disagrees."""
    m = _metrics_from_run(CASE, tmp_path, "TASK COMPLETE", 30.0, timed_out=False, exit_code=0)
    assert m["passed"] is False
    assert m["false_complete"] is True
