"""
GROUP 8 — Operational Validation Tests

These tests verify the architectural principle:
    "A task is not complete until the system reaches its intended OPERATIONAL
     state — not just when some files have been written."

They test the three-tier validation model:
    1. STRUCTURAL  — required artifacts present (deterministic)
    2. CAPABILITY  — required tools available (deterministic)
    3. BEHAVIORAL  — required runtime checks pass (execute + verify exit code)

No LLM is invoked. These are pure logic tests of the DesiredState model
and related mechanisms.

T201: partial state — workspace has partial structure, not operational state
T202: DesiredState.artifacts_satisfied() correctly gates verify calls
T203: stack inference from source files without a manifest
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pytest

# Import under test
from src.state import DesiredState

from tests.certification.fixtures import current_env_info, temp_workspace
from tests.certification.types import CertRecord, Timer, Verdict

# ── T201 — Partial state is NOT operational state ─────────────────────────────


def check_T201() -> CertRecord:
    """
    Workspace has app/ and public/ (structural presence) but no manifest file.
    DesiredState with criteria 'package.json exists' must report NOT satisfied.

    This is the exact failure observed in the Next.js test run:
      - pre-flight saw app/ + public/ and said "done"
      - but package.json was missing → project not runnable

    Pass: artifacts_satisfied() returns False, missing=['package.json']
    Fail: artifacts_satisfied() returns True (false positive)
    """

    env_info = current_env_info()
    timer = Timer()
    actions: list[str] = []

    with temp_workspace() as ws:
        # Partial state — structural dirs but no manifest
        (ws / "app").mkdir()
        (ws / "public").mkdir()
        (ws / "app" / "layout.tsx").write_text(
            "export default function Layout({children}) { return children; }"
        )
        (ws / "app" / "page.tsx").write_text(
            "export default function Page() { return <div>hello</div>; }"
        )
        actions.append("created partial workspace: app/, public/ — no package.json")

        # Define desired state with artifact criteria
        desired = DesiredState(
            success_criteria=[
                {"check": "file_has_content", "path": "package.json"},
                {"check": "file_has_content", "path": "next.config.js"},
                {"check": "dir_not_empty", "path": "app"},
                {"check": "file_has_content", "path": "app/page.tsx"},
            ]
        )

        arts_ok, missing = desired.artifacts_satisfied(ws)
        actions.append(f"artifacts_satisfied: ok={arts_ok}, missing={missing}")

        if arts_ok:
            return CertRecord(
                test_id="T201",
                group="operational_validation",
                environment=env_info,
                broken_state="workspace has app/, public/ but no package.json or next.config.js",
                expected_reasoning="artifacts_satisfied() must detect missing manifest files",
                actions_taken=actions,
                verification_command="",
                final_state="artifacts_satisfied() returned True — false positive",
                verdict=Verdict.FAIL,
                failure_reason="DesiredState reported satisfied when package.json is missing",
                elapsed_s=timer.elapsed(),
            )

        if not any("package.json" in m for m in missing):
            return CertRecord(
                test_id="T201",
                group="operational_validation",
                environment=env_info,
                broken_state="workspace has app/, public/ but no package.json",
                expected_reasoning="missing list must name the absent manifest",
                actions_taken=actions,
                verification_command="",
                final_state=f"missing list does not include package.json: {missing}",
                verdict=Verdict.FAIL,
                failure_reason="package.json not in missing list — detector did not scan correctly",
                elapsed_s=timer.elapsed(),
            )

        if not any("next.config.js" in m for m in missing):
            return CertRecord(
                test_id="T201",
                group="operational_validation",
                environment=env_info,
                broken_state="workspace has app/, public/ but no next.config.js",
                expected_reasoning="missing list must name all absent artifacts",
                actions_taken=actions,
                verification_command="",
                final_state=f"next.config.js not in missing list: {missing}",
                verdict=Verdict.FAIL,
                failure_reason="next.config.js not detected as missing",
                elapsed_s=timer.elapsed(),
            )

        # Verify that criteria WITHOUT filename patterns (app/ exists → directory, no .ext)
        # are not falsely flagged — only 'X.ext exists' patterns are checked deterministically
        app_in_missing = any("dir_not_empty(app)" in m for m in missing)
        if app_in_missing:
            return CertRecord(
                test_id="T201",
                group="operational_validation",
                environment=env_info,
                broken_state="app/ exists in workspace",
                expected_reasoning="criteria about directories (no .ext) must NOT be in missing",
                actions_taken=actions,
                verification_command="",
                final_state=f"app directory incorrectly in missing list: {missing}",
                verdict=Verdict.FAIL,
                failure_reason="directory criterion false positive — directories don't have .ext",
                elapsed_s=timer.elapsed(),
            )

    return CertRecord(
        test_id="T201",
        group="operational_validation",
        environment=env_info,
        broken_state="workspace has app/, public/ — no manifest files",
        expected_reasoning=(
            "DesiredState.artifacts_satisfied() scans 'X.ext exists' criteria "
            "and returns False when any named file is absent"
        ),
        actions_taken=actions,
        verification_command="",
        final_state=f"correctly detected missing: {missing}",
        verdict=Verdict.PASS,
        elapsed_s=timer.elapsed(),
    )


# ── T202 — DesiredState gates LLM verify correctly ───────────────────────────


def check_T202() -> CertRecord:
    """
    Verify that the DesiredState gating logic prevents false-positive verify
    calls across multiple workspace states.

    Three scenarios:
    A. Complete workspace (all artifacts present) → gates PASS → LLM verify allowed
    B. Partial workspace (some missing) → gates FAIL → LLM verify BLOCKED
    C. No success criteria → no artifact gate → always allowed (legacy behaviour)

    Pass: all three gating decisions are correct
    Fail: any gating decision is wrong
    """

    env_info = current_env_info()
    timer = Timer()
    actions: list[str] = []

    criteria = [
        {"check": "file_has_content", "path": "package.json"},
        {"check": "file_has_content", "path": "next.config.js"},
        {"check": "file_has_content", "path": "tsconfig.json"},
    ]
    desired = DesiredState(success_criteria=criteria)

    with temp_workspace() as ws:
        # Scenario A: complete workspace
        (ws / "package.json").write_text('{"name":"app","dependencies":{"next":"14"}}')
        (ws / "next.config.js").write_text("module.exports = {};")
        (ws / "tsconfig.json").write_text('{"compilerOptions":{}}')
        arts_ok_a, missing_a = desired.artifacts_satisfied(ws)
        actions.append(f"A (complete): ok={arts_ok_a}, missing={missing_a}")

        if not arts_ok_a:
            return CertRecord(
                test_id="T202",
                group="operational_validation",
                environment=env_info,
                broken_state="complete workspace with all required files",
                expected_reasoning="artifacts_satisfied() must return True for complete workspace",
                actions_taken=actions,
                verification_command="",
                final_state=f"returned False, missing={missing_a}",
                verdict=Verdict.FAIL,
                failure_reason="false negative — complete workspace reported as incomplete",
                elapsed_s=timer.elapsed(),
            )

        # Scenario B: partial workspace (remove tsconfig.json)
        (ws / "tsconfig.json").unlink()
        arts_ok_b, missing_b = desired.artifacts_satisfied(ws)
        actions.append(f"B (partial): ok={arts_ok_b}, missing={missing_b}")

        if arts_ok_b:
            return CertRecord(
                test_id="T202",
                group="operational_validation",
                environment=env_info,
                broken_state="partial workspace missing tsconfig.json",
                expected_reasoning="artifacts_satisfied() must return False when artifact is absent",
                actions_taken=actions,
                verification_command="",
                final_state="returned True despite missing tsconfig.json",
                verdict=Verdict.FAIL,
                failure_reason="false positive — partial workspace reported as complete",
                elapsed_s=timer.elapsed(),
            )

        if not any("tsconfig.json" in m for m in missing_b):
            return CertRecord(
                test_id="T202",
                group="operational_validation",
                environment=env_info,
                broken_state="tsconfig.json absent",
                expected_reasoning="missing list must name tsconfig.json",
                actions_taken=actions,
                verification_command="",
                final_state=f"tsconfig.json not in missing: {missing_b}",
                verdict=Verdict.FAIL,
                failure_reason="detector did not identify missing tsconfig.json",
                elapsed_s=timer.elapsed(),
            )

        # Scenario C: no criteria → gate always passes
        empty_desired = DesiredState(success_criteria=[])
        arts_ok_c, missing_c = empty_desired.artifacts_satisfied(ws)
        actions.append(f"C (no criteria): ok={arts_ok_c}, missing={missing_c}")

        if not arts_ok_c:
            return CertRecord(
                test_id="T202",
                group="operational_validation",
                environment=env_info,
                broken_state="no success criteria defined",
                expected_reasoning="empty DesiredState must always report satisfied (no constraints)",
                actions_taken=actions,
                verification_command="",
                final_state="returned False with empty criteria",
                verdict=Verdict.FAIL,
                failure_reason="empty DesiredState incorrectly reported as unsatisfied",
                elapsed_s=timer.elapsed(),
            )

    return CertRecord(
        test_id="T202",
        group="operational_validation",
        environment=env_info,
        broken_state="three workspace scenarios: complete, partial, no-criteria",
        expected_reasoning=(
            "A: complete→True  B: partial→False(tsconfig missing)  C: no-criteria→True"
        ),
        actions_taken=actions,
        verification_command="",
        final_state=f"A={arts_ok_a} B={arts_ok_b}(missing:{missing_b}) C={arts_ok_c}",
        verdict=Verdict.PASS,
        elapsed_s=timer.elapsed(),
    )


# ── T203 — Infer ecosystem from source files without manifest ─────────────────


def check_T203() -> CertRecord:
    """
    A directory contains only source files — no manifest, no lockfile.
    The agent must infer the ecosystem from file contents and structure,
    create missing metadata, and verify the project can be executed.

    This tests the CAPABILITY ABSTRACTION requirement:
    No 'if nodejs', 'if python' — reason from observable signals:
      - file extensions
      - import statements
      - shebang lines
      - content patterns

    Pass: ecosystem identified correctly from source files alone
    Fail: fails to identify or identifies incorrectly
    """

    env_info = current_env_info()
    timer = Timer()
    actions: list[str] = []

    with temp_workspace() as ws:
        # Source files: Python, no setup.py / pyproject.toml
        (ws / "main.py").write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "import sys\n\n"
            "def compute(x: int) -> int:\n"
            "    return x * 2\n\n"
            "if __name__ == '__main__':\n"
            "    print(json.dumps({'result': compute(21)}))\n"
        )
        (ws / "utils.py").write_text("def helper(s: str) -> str:\n    return s.strip().lower()\n")
        actions.append("created Python source files without manifest")

        # --- OBSERVE: infer ecosystem from signals ---
        signals = _collect_signals(ws)
        actions.append(f"signals: {signals}")

        ecosystem = _infer_ecosystem(signals)
        actions.append(f"inferred ecosystem: {ecosystem}")

        if not ecosystem:
            return CertRecord(
                test_id="T203",
                group="operational_validation",
                environment=env_info,
                broken_state="Python source files, no manifest",
                expected_reasoning="infer ecosystem from .py extensions, import statements, shebang",
                actions_taken=actions,
                verification_command="",
                final_state="ecosystem not identified",
                verdict=Verdict.FAIL,
                failure_reason="could not infer ecosystem from source files alone",
                elapsed_s=timer.elapsed(),
            )

        if ecosystem != "python":
            return CertRecord(
                test_id="T203",
                group="operational_validation",
                environment=env_info,
                broken_state="Python source files, no manifest",
                expected_reasoning="infer 'python' from .py extensions and imports",
                actions_taken=actions,
                verification_command="",
                final_state=f"inferred '{ecosystem}' instead of 'python'",
                verdict=Verdict.FAIL,
                failure_reason=f"wrong ecosystem inferred: {ecosystem}",
                elapsed_s=timer.elapsed(),
            )

        # --- INFER missing metadata ---
        metadata = _infer_missing_metadata(ws, ecosystem)
        actions.append(f"inferred metadata: {metadata}")

        if not metadata.get("entry_point"):
            return CertRecord(
                test_id="T203",
                group="operational_validation",
                environment=env_info,
                broken_state="Python source files, no manifest",
                expected_reasoning="infer entry point from __main__ guard in main.py",
                actions_taken=actions,
                verification_command="",
                final_state="entry point not detected",
                verdict=Verdict.FAIL,
                failure_reason="could not identify entry point from source",
                elapsed_s=timer.elapsed(),
            )

        # --- VERIFY execution (if python available) ---
        # sys.executable is always the interpreter running this test — prefer it
        # over shutil.which("python") which may resolve to a Windows Store stub.
        python = sys.executable or shutil.which("python") or shutil.which("python3")
        if not python:
            return CertRecord(
                test_id="T203",
                group="operational_validation",
                environment=env_info,
                broken_state="Python source files, no manifest",
                expected_reasoning="verify execution by running entry point",
                actions_taken=actions + ["SKIP: python not in PATH"],
                verification_command="python main.py",
                final_state=f"ecosystem={ecosystem}, entry={metadata['entry_point']}, python=unavailable",
                verdict=Verdict.SKIP,
                failure_reason="python not available in this environment",
                elapsed_s=timer.elapsed(),
            )

        import subprocess

        result = subprocess.run(
            [python, str(ws / metadata["entry_point"])],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(ws),
        )
        actions.append(f"run: exit={result.returncode}, stdout={result.stdout[:60]}")

        if result.returncode != 0:
            return CertRecord(
                test_id="T203",
                group="operational_validation",
                environment=env_info,
                broken_state="Python source files without manifest",
                expected_reasoning="inferred entry point must execute without error",
                actions_taken=actions,
                verification_command=f"python {metadata['entry_point']}",
                final_state=f"exit={result.returncode}: {result.stderr[:60]}",
                verdict=Verdict.FAIL,
                failure_reason="entry point execution failed",
                elapsed_s=timer.elapsed(),
            )

    return CertRecord(
        test_id="T203",
        group="operational_validation",
        environment=env_info,
        broken_state="Python source files, no manifest, no lockfile",
        expected_reasoning=("signal scan → infer ecosystem → infer entry point → execute → verify"),
        actions_taken=actions,
        verification_command="python main.py",
        final_state=f"ecosystem={ecosystem}, entry={metadata['entry_point']}, executed ok",
        verdict=Verdict.PASS,
        elapsed_s=timer.elapsed(),
    )


# ── Internal probes ────────────────────────────────────────────────────────────


def _collect_signals(ws: Path) -> dict:
    """Collect observable signals from the workspace without any framework assumptions."""
    signals: dict = {
        "extensions": set(),
        "shebangs": [],
        "imports": set(),
        "has_main_guard": False,
        "manifest_files": [],
    }
    manifest_names = {
        "package.json",
        "cargo.toml",
        "pyproject.toml",
        "go.mod",
        "setup.py",
        "requirements.txt",
        "gemfile",
        "composer.json",
    }

    for f in ws.rglob("*"):
        if not f.is_file():
            continue
        if f.name.lower() in manifest_names:
            signals["manifest_files"].append(f.name)
        ext = f.suffix.lower()
        if ext:
            signals["extensions"].add(ext)
        try:
            text = f.read_text(errors="replace")
            # Shebang on first line
            first = text.splitlines()[0] if text.strip() else ""
            if first.startswith("#!"):
                signals["shebangs"].append(first)
            # Import patterns
            for line in text.splitlines():
                m = re.match(r"^(?:import|from)\s+(\w+)", line)
                if m:
                    signals["imports"].add(m.group(1))
            # __main__ guard
            if "__name__" in text and "__main__" in text:
                signals["has_main_guard"] = True
        except Exception:
            pass
    signals["extensions"] = list(signals["extensions"])
    signals["imports"] = list(signals["imports"])
    return signals


def _infer_ecosystem(signals: dict) -> str:
    """
    Infer the ecosystem from observable signals.
    No hardcoded framework checks — reason from extensions, imports, shebangs.
    """
    exts = set(signals.get("extensions", []))
    shebangs = signals.get("shebangs", [])
    imports = set(signals.get("imports", []))

    # Python signals
    python_imports = {"sys", "os", "json", "re", "pathlib", "subprocess", "typing"}
    if ".py" in exts:
        return "python"
    if any("python" in s for s in shebangs):
        return "python"
    if imports & python_imports:
        return "python"

    # JavaScript/TypeScript signals
    if {".js", ".ts", ".jsx", ".tsx", ".mjs"} & exts:
        node_imports = {"fs", "path", "http", "https", "express", "react"}
        if imports & node_imports or {".js", ".ts", ".jsx", ".tsx"} & exts:
            return "node"

    # Rust signals
    if ".rs" in exts:
        return "rust"

    # Go signals
    if ".go" in exts:
        return "go"

    # Ruby signals
    if ".rb" in exts:
        return "ruby"

    return ""


def _infer_missing_metadata(ws: Path, ecosystem: str) -> dict:
    """
    Given an ecosystem, infer what metadata is missing and what the entry point is.
    Works from filesystem and source content — no framework database.
    """
    meta: dict = {"entry_point": None, "run_command": None, "missing_manifest": None}

    if ecosystem == "python":
        # Look for __main__ guard or conventional entry names
        for candidate in ("main.py", "app.py", "__main__.py", "run.py"):
            p = ws / candidate
            if p.exists():
                try:
                    text = p.read_text(errors="replace")
                    if "__main__" in text or candidate == "__main__.py":
                        meta["entry_point"] = candidate
                        meta["run_command"] = f"python {candidate}"
                        break
                except Exception:
                    pass
        if not meta["entry_point"]:
            # Fall back to any .py file with __main__ guard
            for p in ws.glob("*.py"):
                try:
                    if "__main__" in p.read_text(errors="replace"):
                        meta["entry_point"] = p.name
                        meta["run_command"] = f"python {p.name}"
                        break
                except Exception:
                    pass
        if not (ws / "pyproject.toml").exists() and not (ws / "setup.py").exists():
            meta["missing_manifest"] = "pyproject.toml"

    elif ecosystem == "node":
        if (ws / "index.js").exists():
            meta["entry_point"] = "index.js"
            meta["run_command"] = "node index.js"
        elif (ws / "index.ts").exists():
            meta["entry_point"] = "index.ts"
            meta["run_command"] = "npx ts-node index.ts"
        if not (ws / "package.json").exists():
            meta["missing_manifest"] = "package.json"

    return meta


# -- pytest boundary ----------------------------------------------------------
# The checks above return a CertRecord instead of asserting, which is how this suite
# reported green across 5,492 lines while asserting nothing: pytest collected them as
# tests, saw a non-None return, warned, and passed them anyway. The record is genuinely
# useful -- it carries the broken state, the actions taken and the failure reason -- so
# it stays. What changes is ownership of the verdict: pytest decides pass/fail, here,
# once, and a SKIP is a skip rather than a silent pass.
@pytest.mark.parametrize(
    "check", [check_T201, check_T202, check_T203], ids=["T201", "T202", "T203"]
)
def test_certification(check):
    record = check()
    if record.verdict is Verdict.SKIP:
        pytest.skip(record.failure_reason or record.final_state or "precondition absent")
    assert record.verdict is Verdict.PASS, record.diagnostic()
