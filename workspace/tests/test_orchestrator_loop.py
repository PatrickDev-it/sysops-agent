"""The invariants are verified WHERE THEY COMPOSE — inside the run loop.

Every invariant in AGENTS.md is unit-tested in isolation, and every one of those unit tests
would stay green if the loop simply stopped calling the thing it tests. `safety_gate.classify`
is covered; that a DESTRUCTIVE goal never reaches the planner is not. `ocke.filter_plan` is
covered; that its verdict is applied is not. The REFUTED veto is covered; that a blocked step
halts the plan is not.

That gap is not hypothetical — it is the defect class this repository has now paid for four
times: a guard that exists, is correct, and is not wired to the path that needs it. The loop
sat at 11% coverage because it was believed to be untestable. It is not: `_run_loop` takes
session, terminal and supervisor as parameters, so the seam was there all along.

Nothing here asserts that a method was called. The fakes behave, and the assertions are about
what the loop did to the workspace and in what order.
"""

import pytest
from src.orchestrator import Orchestrator
from src.state import SystemState
from src.verdict import RunVerdict

from tests.fake_agent import (
    FakeRouter,
    FakeSession,
    FakeSupervisor,
    FakeTerminal,
    file_exists,
    plan,
    step,
)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    from src import orchestrator as orch_mod
    from src.tools import confinement, safety_gate

    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(confinement, "_root", ws.resolve())
    # The authoring path stays live; only the model behind it is deterministic.
    monkeypatch.setattr(orch_mod, "model_router", FakeRouter())
    # The goal gate is a separate model owner. A loop composition test must never depend on a
    # live llama-server, but it must still traverse the real safety_gate.classify implementation.
    monkeypatch.setattr(
        safety_gate.model_router,
        "safety_call",
        lambda ctx: {"risk": safety_gate.SAFE, "reason": "hermetic benign fixture"},
    )
    return ws


def _drive(workspace, supervisor, session=None, goal="build a small service"):
    """Run the real loop against fakes and return (verdict, note, session).

    `init_db()` is a precondition of `_run_loop` that `run()` satisfies on its behalf — the
    loop writes an episodic event per step and assumes the schema exists. Calling it here
    states the dependency instead of inheriting it by accident.
    """
    from src import memory

    memory.init_db()

    orch = Orchestrator(workspace=str(workspace))
    session = session or FakeSession(workspace=workspace)
    terminal = FakeTerminal()
    sysstate = SystemState(session.workspace)
    verdict, note = orch._run_loop(goal, session, terminal, supervisor, sysstate)
    return verdict, note, session


# ── The happy path composes ──────────────────────────────────────────────────


def test_a_plan_whose_steps_produce_the_declared_artifacts_completes(workspace):
    sup = FakeSupervisor(
        plans=[
            plan(
                step("create the manifest", "npm init -y", success=[file_exists("package.json")]),
                success=[file_exists("package.json")],
            )
        ],
        verify_results=[(True, "manifest present")],
    )
    session = FakeSession(
        workspace=workspace, creates={"npm init": {"package.json": '{"name":"svc"}'}}
    )
    verdict, note, session = _drive(workspace, sup, session)

    assert verdict is RunVerdict.COMPLETE, note
    assert (workspace / "package.json").exists()
    assert any("npm init" in c for c in session.commands)


def test_a_plan_that_produces_nothing_does_not_complete(workspace):
    """The filesystem overrules the verifier: a model saying 'done' over an empty workspace
    is the vacuous-success failure this tree was built around."""
    sup = FakeSupervisor(
        plans=[
            plan(
                step("create the manifest", "npm init -y", success=[file_exists("package.json")]),
                success=[file_exists("package.json")],
            )
        ],
        verify_results=[(True, "I believe it worked")],
    )
    verdict, note, _ = _drive(workspace, sup)
    assert verdict is not RunVerdict.COMPLETE
    assert not (workspace / "package.json").exists()


# ── Invariant #7: destructive goals never reach planning ─────────────────────


def test_a_destructive_goal_is_refused_before_the_planner_is_consulted(workspace):
    sup = FakeSupervisor(plans=[plan(step("wipe", "rm -rf /"))])
    verdict, note, session = _drive(
        workspace, sup, goal="delete everything on the whole system, format the disk"
    )

    assert verdict is RunVerdict.REFUSED, note
    assert sup.plan_calls == [], "the planner was consulted for a goal that was refused"
    assert session.commands == [], "a refused goal must execute nothing"


def test_a_safe_goal_does_reach_the_planner(workspace):
    """The counterpart, so the test above cannot pass by the gate refusing everything."""
    sup = FakeSupervisor(plans=[plan(step("list", "Get-ChildItem", step_type="DISCOVERY"))])
    _drive(workspace, sup, goal="list the files in this directory")
    assert sup.plan_calls, "a benign goal never reached the planner"


def test_a_recoverable_goal_is_refused_without_operator_approval(workspace, monkeypatch):
    from src.tools import safety_gate

    monkeypatch.setattr(
        safety_gate,
        "classify",
        lambda goal: (safety_gate.RECOVERABLE, "bounded mutation needs explicit approval"),
    )
    sup = FakeSupervisor(plans=[plan(step("remove cache", "Remove-Item cache -Recurse"))])

    verdict, note, session = _drive(workspace, sup, goal="delete the project cache")

    assert verdict is RunVerdict.REFUSED, note
    assert sup.plan_calls == []
    assert session.commands == []


# ── Invariant: nothing is deleted without it being a planned, gated action ───


def test_a_cleanup_wording_in_the_goal_does_not_delete_the_workspace(workspace):
    """A pre-flight block used to run `clear_workspace()` whenever the goal contained one of
    delete/clean/empty/remove/wipe/clear and the directory did not look like a project — before
    the safety gate, before any model call, with no confirmation."""
    (workspace / "important.txt").write_text("do not lose me")
    sup = FakeSupervisor(plans=[plan(step("inspect", "Get-ChildItem", step_type="DISCOVERY"))])
    _, _, session = _drive(workspace, sup, goal="clean up the PATH variable for my user")

    assert session.cleared is False, "the workspace was cleared by a keyword reflex"
    assert (workspace / "important.txt").read_text() == "do not lose me"


# ── Invariant #11: the platform filter's verdict is applied ─────────────────


def test_a_cross_platform_step_is_not_executed_verbatim(workspace):
    """`filter_plan` annotates a step it rejects. Annotating and then running it anyway is the
    same as not filtering at all."""
    import sys

    if sys.platform != "win32":
        pytest.skip("the fixture's violation is Unix-on-Windows")
    sup = FakeSupervisor(
        plans=[plan(step("install ripgrep", "sudo apt-get install -y ripgrep"))],
        verify_results=[(False, "nothing installed")],
    )
    _, _, session = _drive(workspace, sup, goal="install ripgrep")
    assert not any("apt-get" in c for c in session.commands), (
        f"a step the OCKE rejected was executed anyway: {session.commands}"
    )


# ── The run is recorded whatever happens ────────────────────────────────────


def test_every_terminal_path_produces_a_typed_verdict(workspace):
    """The loop returned None on all four terminal paths and the process exited 0 regardless,
    so no caller could distinguish completed from refused from gave-up."""
    sup = FakeSupervisor(
        plans=[plan(step("noop", "echo hi", step_type="DISCOVERY"))],
        verify_results=[(False, "not done")],
    )
    verdict, _, _ = _drive(workspace, sup)
    assert isinstance(verdict, RunVerdict)
    assert verdict.exit_code == 0 if verdict is RunVerdict.COMPLETE else verdict.exit_code != 0


def test_a_failing_step_does_not_report_completion(workspace):
    sup = FakeSupervisor(
        plans=[
            plan(
                step("build", "npm run build", success=[file_exists("dist/app.js")]),
                success=[file_exists("dist/app.js")],
            )
        ],
        verify_results=[(False, "build failed")],
    )
    session = FakeSession(workspace=workspace, default=("npm ERR! build failed", 1))
    verdict, note, _ = _drive(workspace, sup, session)
    assert verdict is not RunVerdict.COMPLETE


# ── Placeholders never reach the shell ──────────────────────────────────────


def test_an_unresolved_placeholder_is_never_executed(workspace):
    """Invariant #2 at the point that matters: the planner's launcher, not just the coder's."""
    sup = FakeSupervisor(
        plans=[
            plan(
                step(
                    "copy the artifact",
                    "Copy-Item ${TARGET} ./out.txt",
                    success=[file_exists("out.txt")],
                ),
                success=[file_exists("out.txt")],
            )
        ],
        verify_results=[(False, "nothing copied")],
    )
    _, _, session = _drive(workspace, sup)
    assert not any("${TARGET}" in c for c in session.commands), (
        f"an unresolved slot reached the shell: {session.commands}"
    )
    assert any("${TARGET}" in c for c in session.blocked), (
        "the step never reached the execution point, so this proves nothing about the guard"
    )
