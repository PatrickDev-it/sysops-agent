"""Regression: a machine-checkable question must never be asked of a model.

`DesiredState.artifacts_satisfied()` used to parse prose with two regexes and, when neither
matched, return `(True, [])` — satisfied, nothing missing. The caller read that as "artifacts
are all present", then asked the LLM verifier "is the goal already done?". Handed criteria it
could not evaluate, the model said yes. In the validation pilot, 10 of 10 tasks were reported
COMPLETE against an empty workspace.

Vacuous truth is the failure mode these tests exist to make impossible.
"""

from src.config import SRC
from src.state import DesiredState


def test_unmet_predicate_is_never_vacuously_satisfied(tmp_path):
    ds = DesiredState(success_criteria=[{"check": "file_has_content", "path": "health.txt"}])
    ok, missing = ds.artifacts_satisfied(tmp_path)
    assert not ok
    assert missing and "health.txt" in missing[0]


def test_empty_file_does_not_satisfy_an_artifact(tmp_path):
    (tmp_path / "health.txt").write_text("")
    ds = DesiredState(success_criteria=[{"check": "file_has_content", "path": "health.txt"}])
    assert not ds.artifacts_satisfied(tmp_path)[0]


def test_satisfied_only_when_the_filesystem_agrees(tmp_path):
    (tmp_path / "health.txt").write_text("cpu 12%")
    ds = DesiredState(success_criteria=[{"check": "file_has_content", "path": "health.txt"}])
    assert ds.artifacts_satisfied(tmp_path) == (True, [])


def test_prose_criteria_cannot_pass_silently(tmp_path):
    """The old shape. It must FAIL loudly now, not be skipped as unrecognised."""
    ds = DesiredState(success_criteria=["health.txt exists", "Content not empty"])
    ok, missing = ds.artifacts_satisfied(tmp_path)
    assert not ok and len(missing) == 2


def test_no_criteria_means_no_claim(tmp_path):
    """With nothing declared there is nothing to satisfy — but the caller must not read
    this as 'the goal is done'. It reads as `(True, [])`, so the pre-execution gate is
    guarded by `if global_success and plan:` upstream. Pinned here so that guard is not
    removed by someone reading only this function."""
    assert DesiredState(success_criteria=[]).artifacts_satisfied(tmp_path) == (True, [])


def test_pre_execution_gate_only_trusts_filesystem_predicates():
    """The early exit is gated on FILESYSTEM criteria, and never consults a model.

    `tool_on_path` says a program exists on this host; it can never establish that the work is
    done. The `bun_frontend` scaffold declared it as its only goal criterion and was reported
    COMPLETE in thirteen seconds against an empty workspace — vacuous success entering through
    a new door, one layer above the evaluator this file was first written to guard."""
    src = (SRC / "orchestrator.py").read_text(encoding="utf-8")
    assert "_fs_success = predicates.filesystem_criteria(global_success)" in src
    assert "if _fs_success and plan:" in src, "the vacuous-success guard was removed"
    gate = src.split("if _fs_success and plan:", 1)[1][:900]
    assert "supervisor.verify" not in gate, (
        "the pre-execution gate consults a model again — a predicate the filesystem can "
        "answer must never be delegated to an LLM"
    )


def test_a_capability_predicate_can_never_declare_a_goal_done():
    from src.tools import predicates

    crits = [{"check": "tool_on_path", "path": "bun"}]
    assert predicates.filesystem_criteria(crits) == []
    crits.append({"check": "file_has_content", "path": "package.json"})
    assert predicates.filesystem_criteria(crits) == [
        {"check": "file_has_content", "path": "package.json"}
    ]
