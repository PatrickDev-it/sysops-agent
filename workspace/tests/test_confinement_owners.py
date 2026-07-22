"""Every execution owner must actually REFUSE a write outside the root — not merely mention it.

The previous version of this file asserted that each owner's source text contained the strings
`"Confinement"` and `"from_env()"`. Both assertions passed throughout the entire period in
which the filter was inert: `Confinement.from_env()` returned None unless SISTEMISTA_CONFINE_ROOT
was set, and the only callers that set it were the three benchmark harnesses. So on every
production run the guards read `if self._confine is not None:` and did nothing, while this test
stayed green. A substring is not a behaviour.

It also allow-listed `tools/behavior_verifier.py` as "read-only smoke tests". That module was
running `subprocess.run(spec.command, shell=True)` with a command built from package.json
script names taken out of the workspace — the fourth execution owner, ungated, exempted by the
very test written to prevent a fourth execution owner.

These tests now attempt the escape and require it to fail.
"""

import ast
import pathlib

import pytest
from src.config import ROOT
from src.tools import fileops
from src.tools.confinement import Confinement
from src.tools.session import Session

SRC = pathlib.Path(ROOT) / "src"

EXECUTION_OWNERS = {
    "tools/session.py": "subprocess + __SAFE_FS__ sentinels",
    "tools/fileops.py": "direct filesystem writes",
    "tools/terminal.py": "PTY keystrokes",
    "tools/behavior_verifier.py": "workspace smoke tests",
}


@pytest.fixture
def rooted(tmp_path, monkeypatch):
    """A workspace root, and a sibling directory that must remain unreachable for writes.

    Sets the run-level root the way `Orchestrator.__init__` does, because that is the thing
    under test: every owner must resolve writes against the WORKSPACE, not against whatever
    directory the current step happens to run in.
    """
    from src.tools import confinement as confinement_module

    root = tmp_path / "ws"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    monkeypatch.delenv("SISTEMISTA_CONFINE_ROOT", raising=False)
    monkeypatch.delenv("SISTEMISTA_UNCONFINED", raising=False)
    monkeypatch.setattr(confinement_module, "_root", root.resolve())
    return root, outside


# ── The default is confined ──────────────────────────────────────────────────


def test_the_filter_is_active_without_any_environment_variable(rooted):
    """The whole defect in one assertion. This is the case that was unprotected in production."""
    root, _ = rooted
    c = Confinement.for_workspace(root)
    assert c.rooted, "an unset SISTEMISTA_CONFINE_ROOT must not disable path scoping"


def test_fatal_patterns_apply_even_with_no_root(monkeypatch):
    """`_ALWAYS_FATAL` used to live inside the object that from_env() returned as None, so on
    every production run `mkfs` and `diskpart` were unfiltered."""
    monkeypatch.setenv("SISTEMISTA_UNCONFINED", "1")
    c = Confinement.for_workspace(None)
    assert not c.rooted
    assert c.check("mkfs.ext4 /dev/sda1") is not None
    assert c.check("diskpart /s script.txt") is not None


def test_opting_out_is_explicit(monkeypatch, tmp_path):
    monkeypatch.setenv("SISTEMISTA_UNCONFINED", "1")
    assert not Confinement.for_workspace(tmp_path).rooted


# ── Relative paths resolve against the real cwd ──────────────────────────────


def test_a_relative_write_is_judged_against_the_cwd_not_the_root(rooted):
    """MEASURED before the fix: root and cwd were different directories, `check_path` returned
    None for a bare relative name, and the write landed outside the root. Relative names are
    the DOMINANT form, because workspace_paths deliberately forces every prompt to use them."""
    root, outside = rooted
    c = Confinement.for_workspace(root)
    assert c.check_path("pwned.txt", cwd=outside) is not None
    assert c.check_path("fine.txt", cwd=root) is None


def test_fileops_refuses_a_relative_write_outside_the_root(rooted):
    root, outside = rooted
    ok, _ = fileops.write_file("pwned.txt", "OWNED", outside)
    assert ok is False
    assert not (outside / "pwned.txt").exists(), "the write must not happen at all"


def test_fileops_allows_a_write_inside_the_root(rooted):
    root, _ = rooted
    ok, _ = fileops.write_file("app.py", "print(1)", root)
    assert ok and (root / "app.py").read_text() == "print(1)"


# ── The shell owner ──────────────────────────────────────────────────────────


def test_session_refuses_a_mutating_command_aimed_outside(rooted):
    root, outside = rooted
    s = Session(workspace=root)
    try:
        out, code = s.run(f'Set-Content "{outside / "pwned.txt"}" -Value x')
        assert code == 126 and "CONFINEMENT" in out
        assert not (outside / "pwned.txt").exists()
    finally:
        s.shutdown()


def test_session_refuses_to_rebind_the_resolution_path(rooted):
    """`$env:PATH=...` used to be written into the AGENT's own os.environ, and every Popen in
    session.py invokes its target by bare name — powershell.exe, taskkill, robocopy."""
    import os

    root, _ = rooted
    before = os.environ.get("PATH")
    s = Session(workspace=root)
    try:
        s._extract_env_assignments(r"$env:PATH='C:\evil'")
        assert os.environ.get("PATH") == before, "the agent's own PATH was rebound"
        assert s._env.get("PATH") != r"C:\evil", "PATH must not be rebindable at all"
    finally:
        s.shutdown()


# ── Structural guards ────────────────────────────────────────────────────────


@pytest.mark.parametrize("rel", sorted(EXECUTION_OWNERS))
def test_every_execution_owner_imports_the_filter(rel):
    """Kept as a cheap structural net UNDER the behavioural tests above, never instead of them:
    it catches a new owner that forgot the filter before anyone writes its behaviour test."""
    tree = ast.parse((SRC / rel).read_text(encoding="utf-8"))
    names = {
        n.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for n in node.names
    }
    assert "Confinement" in names, (
        f"{rel} ({EXECUTION_OWNERS[rel]}) executes without importing tools/confinement.py"
    )


def test_no_module_executes_a_shell_string():
    """`shell=True` hands the model's string to a shell interpreter with no argv boundary.
    behavior_verifier was the only such call and it was reachable from workspace-controlled
    package.json content."""
    offenders = []
    for p in SRC.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if (
                    kw.arg == "shell"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True
                ):
                    offenders.append(f"{p.relative_to(SRC).as_posix()}:{node.lineno}")
    assert not offenders, f"shell=True found at {offenders}"


def test_no_other_module_spawns_a_process():
    """A new execution owner must be a deliberate, reviewed act — not an import of subprocess
    in a module nobody thought of as an execution path."""
    allowed = set(EXECUTION_OWNERS) | {
        "llm_backend.py",  # spawns llama-server, not agent commands
        "knowledge/system_spec.py",  # read-only probe of the host
        "tools/discovery.py",  # read-only probes
    }
    offenders = []
    for p in SRC.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(SRC).as_posix()
        if rel in allowed:
            continue
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            spawns = (
                isinstance(node, ast.Attribute)
                and node.attr in ("Popen", "run", "call", "check_output")
                and isinstance(node.value, ast.Name)
                and node.value.id == "subprocess"
            )
            if spawns:
                offenders.append(rel)
                break
    assert not offenders, (
        f"new execution owner(s) without confinement review: {sorted(set(offenders))}. "
        f"Either wire tools/confinement.py in, or add to the allow-list with a reason."
    )
