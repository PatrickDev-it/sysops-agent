"""Deterministic stand-ins for everything the orchestrator loop talks to.

`Orchestrator._run_loop(goal, session, terminal, supervisor, sysstate)` takes every collaborator
as a parameter. The dependency inversion was already there — as with the PTY, nothing had ever
been plugged into it except the real thing, so the 2,900-line loop that composes every invariant
in this system sat at 11% coverage and each invariant was verified only in isolation.

That is the gap that matters. `safety_gate.classify` is unit-tested, `ocke.filter_plan` is
unit-tested, the REFUTED veto is unit-tested — and a refactor that simply stopped CALLING any of
them would keep every one of those tests green. What is untested is the wiring.

Nothing here mocks a method and asserts it was called. The fakes behave: FakeSession really
records what it was asked to run and really writes the files a scripted command claims to write,
so the assertions are about what the loop DID.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FakeSession:
    """A shell that runs scripted outcomes and records everything it was asked to execute."""

    workspace: Path
    outcomes: dict[str, tuple[str, int]] = field(default_factory=dict)
    default: tuple[str, int] = ("", 0)
    creates: dict[str, dict[str, str]] = field(default_factory=dict)
    commands: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    cleared: bool = False

    def __post_init__(self) -> None:
        self._cwd = Path(self.workspace)

    def run(self, command: str, *a, **k) -> tuple[str, int]:
        """Applies the REAL execution-point guards before recording the command.

        A fake that skips them is not standing in for `Session.run`; it is standing in for a
        session with no guards, and a test written against it proves nothing about the system.
        Invariant #2 and the confinement filter are enforced here in production — this is the
        single execution point — so they are enforced here too, by calling the same code.
        """
        from src.tools.confinement import Confinement
        from src.tools.template_guard import unresolved_placeholder

        slot = unresolved_placeholder(command)
        if slot:
            self.blocked.append(command)
            return f"TEMPLATE LEAK: refused — unresolved {slot}", 126
        reason = Confinement.current().check(command, cwd=self._cwd)
        if reason:
            self.blocked.append(command)
            return f"CONFINEMENT: refused — {reason}", 126

        self.commands.append(command)
        for marker, files in self.creates.items():
            if marker in command:
                for name, content in files.items():
                    target = Path(self.workspace) / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
        for marker, outcome in self.outcomes.items():
            if marker in command:
                return outcome
        return self.default

    def clear_workspace(self) -> tuple[bool, str]:
        self.cleared = True
        return True, "cleared"

    def shutdown(self) -> None:
        pass


@dataclass
class FakeTerminal:
    closed: bool = False

    def close(self) -> None:
        self.closed = True

    def run_command(self, *a, **k) -> str:
        return ""

    def launch(self, *a, **k):
        return None

    def snapshot(self, *a, **k) -> str:
        return ""

    def write(self, *a, **k) -> None:
        pass


@dataclass
class FakeSupervisor:
    """Returns scripted plans and verdicts instead of calling a model.

    `plans` is consumed in order: the first call is the initial plan, later calls are re-plans
    after a failure. `verify_results` likewise. Both record their inputs, so a test can assert
    the loop asked the right question — for instance that the planner was never reached at all
    for a goal the safety gate refused.
    """

    plans: list[dict] = field(default_factory=list)
    verify_results: list[tuple[bool, str]] = field(default_factory=list)
    plan_calls: list[dict] = field(default_factory=list)
    verify_calls: list[str] = field(default_factory=list)

    def plan(self, goal: str, cwd: str, terminal_snapshot: str = "", **kw) -> dict:
        self.plan_calls.append({"goal": goal, "cwd": cwd, **kw})
        if self.plans:
            return self.plans.pop(0)
        return {"mode": "direct", "constraints": [], "success": [], "plan": []}

    def verify(self, objective: str, session, *a, **k) -> tuple[bool, str, str]:
        """(achieved, reason, corrective_action) — the real signature."""
        self.verify_calls.append(objective)
        achieved, reason = self.verify_results.pop(0) if self.verify_results else (True, "ok")
        return achieved, reason, ""


def step(
    objective: str,
    launcher: str,
    *,
    step_type: str = "MODIFY",
    success: list[dict] | None = None,
    delegation: str = "batch",
) -> dict:
    """One plan step in the shape the orchestrator consumes."""
    return {
        "objective": objective,
        "launcher": launcher,
        "step_type": step_type,
        "delegation": delegation,
        "success": success or [],
        "vars": {},
    }


def plan(
    *steps: dict, success: list[dict] | None = None, constraints: list[str] | None = None
) -> dict:
    return {
        "mode": "plan",
        "constraints": constraints or [],
        "success": success or [],
        "plan": list(steps),
    }


def file_exists(path: str) -> dict:
    return {"check": "file_has_content", "path": path}


@dataclass
class FakeRouter:
    """A model router that authors deterministically instead of calling a 3B coder.

    The orchestrator's authoring path is real code worth exercising, so it is not switched
    off: it runs, and this decides what the "model" returns. By default the planner's launcher
    is echoed back unchanged, which is exactly the fallback the runtime already uses whenever
    the coder returns nothing usable — so the loop's behaviour is the documented one.
    """

    authored: dict[str, str] = field(default_factory=dict)
    content: str = "generated content\n"
    calls: list[dict] = field(default_factory=list)

    def executor_call(self, ctx: dict) -> str:
        self.calls.append(ctx)
        hint = str(ctx.get("launcher") or ctx.get("tool") or "")
        for marker, command in self.authored.items():
            if marker in hint or marker in str(ctx.get("objective", "")):
                return command
        return hint

    def executor_fix_call(self, ctx: dict) -> str:
        self.calls.append(ctx)
        return ""  # no alternative — the step fails, as it does with a real coder

    def content_call(self, ctx: dict) -> str:
        self.calls.append(ctx)
        return self.content

    def executor_pty_fallback_call(self, *a, **k) -> str:
        return "KEY(ENTER)"
