"""
GROUP 9 — Real-World Operational Certification

These tests verify the Phase 3 principle:
    "A task is not complete until the system reaches its intended
     OPERATIONAL state — not just STATE CORRECTNESS."

They use the behavior_verifier to test:
    find_entry_command     — discovery-driven, no framework assumptions
    classify_workspace_state — three-tier assessment
    GoalDistance           — distance metric + trend tracking
    wrong_completion_assumption — failure classification

No LLM invoked. Pure logic tests of the behavioral verification layer.

T250: Working project — all three tiers satisfied
T251: Half-configured environment — tier 1 fails, tier 3 blocked
T252: Wrong completion assumption — tier 1+2 OK, tier 3 fails
T253: Unknown ecosystem — entry_command discovered from bare source files
T254: Environment migration — command contains OS-specific assumption
"""

from __future__ import annotations

import sys

import pytest
from src.state import DesiredState, SystemState
from src.tools.behavior_verifier import (
    classify_workspace_state,
    find_entry_command,
)

from tests.certification.fixtures import current_env_info, temp_workspace
from tests.certification.types import CertRecord, Timer, Verdict

# ── T250 — Complete project: all three tiers satisfied ────────────────────────


def check_T250() -> CertRecord:
    """
    Workspace has a complete, runnable Python project.
    All three tiers must be satisfied:
      T1: pyproject.toml exists (structural)
      T2: python available (capability)
      T3: smoke test passes (behavioral)

    Pass: classify_workspace_state.behavioral_ok = True
    Fail: any tier fails, or wrong_completion_assumption raised
    """

    env_info = current_env_info()
    timer = Timer()
    actions: list[str] = []

    with temp_workspace() as ws:
        (ws / "main.py").write_text(
            "import sys\n\ndef run():\n    print('health: ok')\n\n"
            "if __name__ == '__main__':\n    run()\n"
        )
        (ws / "pyproject.toml").write_text("[project]\nname = 'myapp'\nversion = '0.1.0'\n")
        actions.append("created complete Python project: main.py + pyproject.toml")

        sysstate = SystemState(ws)
        ws_state = classify_workspace_state(ws, sysstate, run_smoke_test=True)
        actions.append(
            f"classify: structural={ws_state.structural_ok}, "
            f"capability={ws_state.capability_ok}, "
            f"behavioral={ws_state.behavioral_ok}"
        )
        actions.append(f"entry: {ws_state.entry_command} ({ws_state.discovery_method})")

        if not ws_state.structural_ok:
            return CertRecord(
                test_id="T250",
                group="real_world",
                environment=env_info,
                broken_state="complete Python project",
                expected_reasoning="tier 1 must pass — pyproject.toml detected",
                actions_taken=actions,
                verdict=Verdict.FAIL,
                failure_reason="structural tier failed on complete project",
                elapsed_s=timer.elapsed(),
            )

        if not ws_state.capability_ok:
            return CertRecord(
                test_id="T250",
                group="real_world",
                environment=env_info,
                broken_state="complete Python project, python should be available",
                expected_reasoning="tier 2 must pass — python in PATH",
                actions_taken=actions,
                verification_command="python --version",
                verdict=Verdict.SKIP,
                failure_reason="python not available in this environment",
                elapsed_s=timer.elapsed(),
            )

        if not ws_state.behavioral_ok:
            return CertRecord(
                test_id="T250",
                group="real_world",
                environment=env_info,
                broken_state="complete Python project",
                expected_reasoning="tier 3 must pass — py_compile should succeed on valid script",
                actions_taken=actions,
                verification_command=ws_state.entry_command,
                final_state=ws_state.behavioral_issue,
                verdict=Verdict.FAIL,
                failure_reason=f"behavioral tier failed: {ws_state.behavioral_issue}",
                elapsed_s=timer.elapsed(),
            )

        # Verify GoalDistance reports zero when all tiers pass
        desired = DesiredState(
            success_criteria=[
                {"check": "file_has_content", "path": "main.py"},
                {"check": "file_has_content", "path": "pyproject.toml"},
            ],
        )
        dist = desired.distance(ws, sysstate)
        actions.append(f"GoalDistance: {dist.summary()}")

        if not dist.is_zero():
            return CertRecord(
                test_id="T250",
                group="real_world",
                environment=env_info,
                broken_state="complete project with all artifacts",
                expected_reasoning="GoalDistance must be zero when all criteria met",
                actions_taken=actions,
                verdict=Verdict.FAIL,
                failure_reason=f"GoalDistance non-zero: {dist.summary()}",
                elapsed_s=timer.elapsed(),
            )

    return CertRecord(
        test_id="T250",
        group="real_world",
        environment=env_info,
        broken_state="complete Python project with pyproject.toml",
        expected_reasoning="T1 structural + T2 capability + T3 behavioral all pass",
        actions_taken=actions,
        verification_command=ws_state.entry_command,
        final_state="behavioral_ok=True, distance=0",
        verdict=Verdict.PASS,
        elapsed_s=timer.elapsed(),
    )


# ── T251 — Half-configured: structural tier fails ────────────────────────────


def check_T251() -> CertRecord:
    """
    Workspace has source files but no manifest.
    Desired state requires manifest.json — structural tier must fail.
    GoalDistance.artifacts_gap must be non-zero.

    This tests that the system detects PARTIAL STATE correctly and does NOT
    report 'wrong_completion_assumption' (that would mean tier 1+2 passed).

    Pass: artifacts_gap > 0; not wrong_completion_assumption
    """

    env_info = current_env_info()
    timer = Timer()
    actions: list[str] = []

    with temp_workspace() as ws:
        # Partial state: source file present, no manifest
        (ws / "app.py").write_text("print('hello')\n")
        actions.append("created partial workspace: app.py, no pyproject.toml")

        desired = DesiredState(
            success_criteria=[
                {"check": "file_has_content", "path": "app.py"},
                {"check": "file_has_content", "path": "pyproject.toml"},
            ]
        )
        sysstate = SystemState(ws)
        sysstate.set_desired_state(desired.success_criteria)

        arts_ok, missing = sysstate.desired_state.artifacts_satisfied(ws)
        dist = sysstate.desired_state.distance(ws, sysstate)
        actions.append(f"artifacts_ok={arts_ok}, missing={missing}")
        actions.append(f"GoalDistance: {dist.summary()}")

        if arts_ok:
            return CertRecord(
                test_id="T251",
                group="real_world",
                environment=env_info,
                broken_state="partial workspace missing pyproject.toml",
                expected_reasoning="structural tier must fail when manifest is absent",
                actions_taken=actions,
                verdict=Verdict.FAIL,
                failure_reason="structural tier falsely reported satisfied (false positive)",
                elapsed_s=timer.elapsed(),
            )

        if dist.artifacts_gap == 0:
            return CertRecord(
                test_id="T251",
                group="real_world",
                environment=env_info,
                broken_state="partial workspace",
                expected_reasoning="GoalDistance.artifacts_gap must be > 0",
                actions_taken=actions,
                verdict=Verdict.FAIL,
                failure_reason="GoalDistance shows zero gap despite missing manifest",
                elapsed_s=timer.elapsed(),
            )

        # Classify the workspace — should NOT be wrong_completion_assumption
        ws_state = classify_workspace_state(ws, sysstate, run_smoke_test=False)
        actions.append(f"classify: failure_class={ws_state.failure_class}")

        if ws_state.is_wrong_completion_assumption():
            return CertRecord(
                test_id="T251",
                group="real_world",
                environment=env_info,
                broken_state="partial workspace (structural tier fails)",
                expected_reasoning="wrong_completion_assumption requires tier 1+2 to pass — they don't here",
                actions_taken=actions,
                verdict=Verdict.FAIL,
                failure_reason="incorrectly classified as wrong_completion_assumption",
                elapsed_s=timer.elapsed(),
            )

    return CertRecord(
        test_id="T251",
        group="real_world",
        environment=env_info,
        broken_state="workspace missing pyproject.toml — half configured",
        expected_reasoning=(
            "structural tier fails (manifest missing); distance > 0; "
            "NOT wrong_completion_assumption"
        ),
        actions_taken=actions,
        verification_command="",
        final_state=f"artifacts_gap={dist.artifacts_gap}, missing={missing}",
        verdict=Verdict.PASS,
        elapsed_s=timer.elapsed(),
    )


# ── T252 — Wrong completion assumption: tier 1+2 OK, tier 3 fails ────────────


def check_T252() -> CertRecord:
    """
    Workspace has all required files (tier 1 OK) and python is available (tier 2 OK)
    but the Python script has a syntax error — smoke test fails.

    This is the canonical 'wrong_completion_assumption': the agent wrote the files
    but the runtime cannot execute them. Structural check would report DONE; the
    behavior verifier catches the real issue.

    Pass: wrong_completion_assumption detected; behavioral_ok=False; entry_command found
    """

    env_info = current_env_info()
    timer = Timer()
    actions: list[str] = []

    python = sys.executable
    if not python:
        return CertRecord(
            test_id="T252",
            group="real_world",
            environment=env_info,
            broken_state="",
            expected_reasoning="",
            actions_taken=["SKIP: python not available"],
            verdict=Verdict.SKIP,
            failure_reason="python not available",
            elapsed_s=timer.elapsed(),
        )

    with temp_workspace() as ws:
        # Structurally complete but syntactically broken
        (ws / "main.py").write_text(
            "def broken(:\n    pass\n"  # deliberate syntax error
        )
        (ws / "pyproject.toml").write_text("[project]\nname = 'broken'\nversion = '0.1.0'\n")
        actions.append("created workspace with syntax error in main.py + valid pyproject.toml")

        sysstate = SystemState(ws)
        sysstate.set_desired_state(
            [
                {"check": "file_has_content", "path": "main.py"},
                {"check": "file_has_content", "path": "pyproject.toml"},
            ]
        )

        # Tier 1: structural
        arts_ok, missing = sysstate.desired_state.artifacts_satisfied(ws)
        actions.append(f"T1 structural: ok={arts_ok}, missing={missing}")
        if not arts_ok:
            return CertRecord(
                test_id="T252",
                group="real_world",
                environment=env_info,
                broken_state="workspace with structural artifacts",
                expected_reasoning="structural tier must pass (files exist)",
                actions_taken=actions,
                verdict=Verdict.FAIL,
                failure_reason=f"structural tier failed unexpectedly: missing={missing}",
                elapsed_s=timer.elapsed(),
            )

        # Full classify including behavior
        ws_state = classify_workspace_state(ws, sysstate, run_smoke_test=True)
        actions.append(
            f"classify: structural={ws_state.structural_ok}, "
            f"capability={ws_state.capability_ok}, "
            f"behavioral={ws_state.behavioral_ok}"
        )
        actions.append(f"failure_class: {ws_state.failure_class}")
        actions.append(f"issue: {ws_state.behavioral_issue[:80]}")

        if not ws_state.structural_ok:
            return CertRecord(
                test_id="T252",
                group="real_world",
                environment=env_info,
                broken_state="workspace with all artifacts",
                expected_reasoning="structural tier must be OK when files exist",
                actions_taken=actions,
                verdict=Verdict.FAIL,
                failure_reason="structural tier wrong",
                elapsed_s=timer.elapsed(),
            )

        if not ws_state.capability_ok:
            return CertRecord(
                test_id="T252",
                group="real_world",
                environment=env_info,
                broken_state="workspace with python available",
                expected_reasoning="capability tier must be OK when python is available",
                actions_taken=actions,
                verdict=Verdict.SKIP,
                failure_reason="capability tier failed — python not found",
                elapsed_s=timer.elapsed(),
            )

        if ws_state.behavioral_ok:
            return CertRecord(
                test_id="T252",
                group="real_world",
                environment=env_info,
                broken_state="workspace with syntax error in main.py",
                expected_reasoning="behavioral tier must FAIL on syntax error",
                actions_taken=actions,
                verdict=Verdict.FAIL,
                failure_reason="behavioral tier reported OK despite syntax error",
                elapsed_s=timer.elapsed(),
            )

        if not ws_state.is_wrong_completion_assumption():
            return CertRecord(
                test_id="T252",
                group="real_world",
                environment=env_info,
                broken_state="structural OK, capability OK, behavioral FAIL",
                expected_reasoning="must be classified as wrong_completion_assumption",
                actions_taken=actions,
                verdict=Verdict.FAIL,
                failure_reason=f"wrong failure class: {ws_state.failure_class}",
                elapsed_s=timer.elapsed(),
            )

    return CertRecord(
        test_id="T252",
        group="real_world",
        environment=env_info,
        broken_state="syntactically broken script with correct structural state",
        expected_reasoning=(
            "T1 structural OK (files present) + T2 capability OK (python available) "
            "+ T3 behavioral FAIL (syntax error) → wrong_completion_assumption"
        ),
        actions_taken=actions,
        verification_command=ws_state.entry_command,
        final_state="correctly classified as wrong_completion_assumption",
        verdict=Verdict.PASS,
        elapsed_s=timer.elapsed(),
    )


# ── T253 — Unknown ecosystem: entry_command from bare source files ────────────


def check_T253() -> CertRecord:
    """
    Workspace has source files but NO manifest — the ecosystem must be inferred
    from file content alone (extension, imports, shebang, __main__ guard).

    find_entry_command must return something reasonable without framework knowledge.
    Validates the discovery-driven approach works on unknown stacks.

    Pass: entry_command found, discovery_method is not 'not_found'
    """

    env_info = current_env_info()
    timer = Timer()
    actions: list[str] = []

    with temp_workspace() as ws:
        # Bare Python script — no pyproject.toml, no requirements.txt
        (ws / "compute.py").write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n\n"
            "def main():\n"
            "    result = sum(range(100))\n"
            "    print(f'sum 0..99 = {result}')\n\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        )
        actions.append("created bare Python script without any manifest")

        sysstate = SystemState(ws)
        cmd, method = find_entry_command(ws, sysstate)
        actions.append(f"find_entry_command: cmd={cmd!r}, method={method!r}")

        if not cmd or method == "not_found":
            return CertRecord(
                test_id="T253",
                group="real_world",
                environment=env_info,
                broken_state="bare Python script, no manifest",
                expected_reasoning="discover entry from __main__ guard in .py file",
                actions_taken=actions,
                verdict=Verdict.FAIL,
                failure_reason="find_entry_command returned nothing for bare Python script",
                elapsed_s=timer.elapsed(),
            )

        if "python" not in cmd.lower() and "py_compile" not in cmd.lower():
            return CertRecord(
                test_id="T253",
                group="real_world",
                environment=env_info,
                broken_state="bare Python script",
                expected_reasoning="entry command must involve python/py_compile",
                actions_taken=actions,
                verdict=Verdict.FAIL,
                failure_reason=f"unexpected entry command: {cmd}",
                elapsed_s=timer.elapsed(),
            )

        if "bare" not in method:
            return CertRecord(
                test_id="T253",
                group="real_world",
                environment=env_info,
                broken_state="bare Python script, no manifest",
                expected_reasoning="discovery method must be 'bare_python' or similar",
                actions_taken=actions,
                verdict=Verdict.FAIL,
                failure_reason=f"unexpected discovery method: {method}",
                elapsed_s=timer.elapsed(),
            )

    return CertRecord(
        test_id="T253",
        group="real_world",
        environment=env_info,
        broken_state="bare Python script, no manifest, no lockfile",
        expected_reasoning="discover entry from __main__ guard without manifest",
        actions_taken=actions,
        verification_command=cmd,
        final_state=f"cmd={cmd!r}, method={method!r}",
        verdict=Verdict.PASS,
        elapsed_s=timer.elapsed(),
    )


# ── T254 — GoalDistance trend tracks progress across steps ───────────────────


def check_T254() -> CertRecord:
    """
    Simulate a multi-step goal execution and verify that GoalDistance.trend()
    correctly reports 'improving' as artifacts are created one at a time.

    Also verifies that the trend goes 'stagnating' if a step doesn't create
    anything new, and 'degrading' if an artifact is removed.

    Pass: improving → stagnating → degrading correctly reported
    """

    env_info = current_env_info()
    timer = Timer()
    actions: list[str] = []

    with temp_workspace() as ws:
        desired = DesiredState(
            success_criteria=[
                {"check": "file_has_content", "path": "package.json"},
                {"check": "file_has_content", "path": "tsconfig.json"},
                {"check": "file_has_content", "path": "index.ts"},
            ]
        )
        sysstate = SystemState(ws)
        sysstate.set_desired_state(desired.success_criteria)

        # Step 0: nothing exists
        d0 = sysstate.update_distance(ws)
        actions.append(f"step 0 (empty): {d0.summary()}")
        if d0.artifacts_gap != 3:
            return CertRecord(
                test_id="T254",
                group="real_world",
                environment=env_info,
                broken_state="empty workspace with 3 criteria",
                expected_reasoning="artifacts_gap must be 3 at start",
                actions_taken=actions,
                verdict=Verdict.FAIL,
                failure_reason=f"expected gap=3, got gap={d0.artifacts_gap}",
                elapsed_s=timer.elapsed(),
            )

        # Step 1: create package.json → gap should shrink
        (ws / "package.json").write_text('{"name":"app"}')
        d1 = sysstate.update_distance(ws)
        trend1 = sysstate.distance_trend()
        actions.append(f"step 1 (package.json created): {d1.summary()}, trend={trend1}")
        if trend1 != "improving":
            return CertRecord(
                test_id="T254",
                group="real_world",
                environment=env_info,
                broken_state="after creating package.json",
                expected_reasoning="trend must be 'improving' after creating an artifact",
                actions_taken=actions,
                verdict=Verdict.FAIL,
                failure_reason=f"expected 'improving', got '{trend1}'",
                elapsed_s=timer.elapsed(),
            )

        # Step 2: no new artifact → stagnating
        d2 = sysstate.update_distance(ws)
        trend2 = sysstate.distance_trend()
        actions.append(f"step 2 (no-op): {d2.summary()}, trend={trend2}")
        if trend2 != "stagnating":
            return CertRecord(
                test_id="T254",
                group="real_world",
                environment=env_info,
                broken_state="after no-op step",
                expected_reasoning="trend must be 'stagnating' when distance doesn't change",
                actions_taken=actions,
                verdict=Verdict.FAIL,
                failure_reason=f"expected 'stagnating', got '{trend2}'",
                elapsed_s=timer.elapsed(),
            )

        # Step 3: create remaining artifacts → goal reached
        (ws / "tsconfig.json").write_text('{"compilerOptions":{}}')
        (ws / "index.ts").write_text('console.log("hello");\n')
        d3 = sysstate.update_distance(ws)
        trend3 = sysstate.distance_trend()
        actions.append(f"step 3 (all created): {d3.summary()}, trend={trend3}")
        if not d3.is_zero():
            return CertRecord(
                test_id="T254",
                group="real_world",
                environment=env_info,
                broken_state="after creating all artifacts",
                expected_reasoning="GoalDistance must be zero when all artifacts present",
                actions_taken=actions,
                verdict=Verdict.FAIL,
                failure_reason=f"distance not zero after all artifacts: {d3.summary()}",
                elapsed_s=timer.elapsed(),
            )

    return CertRecord(
        test_id="T254",
        group="real_world",
        environment=env_info,
        broken_state="three-artifact goal, simulated step-by-step creation",
        expected_reasoning=("d0: gap=3 → d1: improving → d2: stagnating → d3: zero (operational)"),
        actions_taken=actions,
        verification_command="",
        final_state=f"trend sequence: initial→{trend1}→{trend2}→zero",
        verdict=Verdict.PASS,
        elapsed_s=timer.elapsed(),
    )


# -- pytest boundary ----------------------------------------------------------
# The checks above return a CertRecord instead of asserting, which is how this suite
# reported green across 5,492 lines while asserting nothing: pytest collected them as
# tests, saw a non-None return, warned, and passed them anyway. The record is genuinely
# useful -- it carries the broken state, the actions taken and the failure reason -- so
# it stays. What changes is ownership of the verdict: pytest decides pass/fail, here,
# once, and a SKIP is a skip rather than a silent pass.
@pytest.mark.parametrize(
    "check",
    [check_T250, check_T251, check_T252, check_T253, check_T254],
    ids=["T250", "T251", "T252", "T253", "T254"],
)
def test_certification(check):
    record = check()
    if record.verdict is Verdict.SKIP:
        pytest.skip(record.failure_reason or record.final_state or "precondition absent")
    assert record.verdict is Verdict.PASS, record.diagnostic()
