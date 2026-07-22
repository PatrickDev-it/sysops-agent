"""A step whose postcondition already holds must not run its command.

Measured on two isolated 48-task runs: 41 and 47 re-plans, which discarded 55 and 65 commands
that had ALREADY SUCCEEDED — about 1.35 per re-plan, roughly 22% of all successful work. The
planner produces a genuinely different plan almost every time (only 2% of re-plans repeat a
fingerprint), so the cost is not duplicate inference: it is valid work thrown away, because a
regenerated plan cannot inherit the previous plan's progress.

A step declares what "done" means as typed predicates the runtime can evaluate without
executing anything. Asking that question BEFORE the step is the same question `_artifact_check`
already asks after it.

These tests pin the skip AND its three exclusions — the exclusions are the load-bearing part,
because skipping a DISCOVERY step would silently starve the DISCOVERY→ACTION channel.
"""

import pytest
from src import config, memory, model_router
from src.orchestrator import Orchestrator


class _Session:
    """The real signature is `run(command, timeout) -> (output, exit_code)`."""

    def __init__(self, cwd):
        self._cwd = cwd
        self.workspace = cwd
        self.ran: list[str] = []

    def run(self, command, timeout=None):  # must never be reached by a skipped step
        self.ran.append(command)
        return "", 0


@pytest.fixture
def orch(tmp_path, monkeypatch):
    # A step that is NOT skipped runs on: to `memory.save_event`, and then into the coder's
    # retry loop. Both need neutralising or this stops being a unit test.
    # State must not live under the task workspace: workspace-shape normalization is allowed
    # to hoist unexpected child directories. Linux permits moving an open SQLite file, while
    # Windows masks that invalid fixture layout by locking it.
    monkeypatch.setattr(config, "MEMORY_DIR", tmp_path.parent / f"{tmp_path.name}-memory")
    memory.init_db()

    # known-issues.md: mocking `_text_call` alone is not enough — `_coder()` is evaluated as
    # an ARGUMENT, so Python calls it first and a real llama-server gets spawned. Mock both.
    monkeypatch.setattr(model_router, "_coder", lambda: None)
    monkeypatch.setattr(model_router, "_nav", lambda: None)
    monkeypatch.setattr(model_router, "executor_call", lambda ctx: "")
    return Orchestrator(workspace=str(tmp_path))


def _content(path):
    """The predicate vocabulary is owned by tools/predicates.py — {"check", "path"}."""
    return [{"check": "file_has_content", "path": str(path)}]


def test_a_satisfied_modify_step_does_not_run_its_command(orch, tmp_path):
    (tmp_path / "report.txt").write_text("already produced by the previous plan", encoding="utf-8")
    session = _Session(tmp_path)

    ok = orch._execute_step(
        "goal",
        "write report.txt",
        "Get-Date > report.txt",
        _content("report.txt"),
        [],
        session,
        None,
        0,
        None,
        step_type="MODIFY",
    )
    assert ok is True
    assert session.ran == [], "the command must not reach the shell"


def test_an_unsatisfied_step_is_not_skipped(orch, tmp_path):
    """The file is missing, so the step has real work to do — it must proceed past the gate."""
    session = _Session(tmp_path)
    orch._execute_step(
        "goal",
        "write missing.txt",
        "Get-Date > missing.txt",
        _content("missing.txt"),
        [],
        session,
        None,
        0,
        None,
        step_type="MODIFY",
    )
    assert session.ran, "a step whose postcondition is unmet must still execute"


def test_an_empty_file_does_not_count_as_satisfied(orch, tmp_path):
    """`file_has_content` is the predicate precisely because an empty file is a placeholder."""
    (tmp_path / "empty.txt").write_text("", encoding="utf-8")
    session = _Session(tmp_path)
    orch._execute_step(
        "goal",
        "write empty.txt",
        "Get-Date > empty.txt",
        _content("empty.txt"),
        [],
        session,
        None,
        0,
        None,
        step_type="MODIFY",
    )
    assert session.ran, "an empty artifact must not satisfy the postcondition"


def test_a_discovery_step_is_never_skipped(orch, tmp_path):
    """DISCOVERY exists to populate facts later steps consume. Its value is the knowledge, not
    the artifact — skipping it would starve the DISCOVERY→ACTION channel while looking correct.
    """
    (tmp_path / "probe.txt").write_text("stale content", encoding="utf-8")
    session = _Session(tmp_path)
    orch._execute_step(
        "goal",
        "probe the host",
        "Get-Command git > probe.txt",
        _content("probe.txt"),
        [],
        session,
        None,
        0,
        None,
        step_type="DISCOVERY",
    )
    assert session.ran, "DISCOVERY must run even when its declared artifact exists"


def test_a_step_with_no_declared_postcondition_is_never_skipped(orch, tmp_path):
    """No predicate means unverifiable, and unverifiable must never be read as satisfied —
    that is the vacuous-success defect this project already paid for once."""
    session = _Session(tmp_path)
    orch._execute_step(
        "goal",
        "do something",
        "Get-Date",
        [],
        [],
        session,
        None,
        0,
        None,
        step_type="MODIFY",
    )
    assert session.ran
