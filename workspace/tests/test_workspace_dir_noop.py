"""A bare `mkdir <workspace-name>` inside the workspace is a NO-OP, not a failure.

Measured on `react` three times in a row (known-issues, debt #7): the planner led with
`New-Item react -ItemType Directory` inside a workspace called `react`; the guard refused it
with exit 126, the orchestrator treated a failed MODIFY prerequisite as fatal, HALTED, and the
replan led with the same mkdir — framework-init deadlocked (`workspace is empty`).

Two properties are pinned here:
  1. `recreates_the_workspace_dir` fires ONLY on the intersection (bare mkdir == workspace name),
     never on legit `mkdir src` or `ng new <name>` / `django-admin startproject <name>`.
  2. At the execution seam the refusal is exit 0 (no-op success), so the plan PROCEEDS to the
     real initializer instead of halting. A guard without a test is not a guard.
"""

from pathlib import Path

import pytest
from src.tools.session import Session
from src.tools.template_guard import recreates_the_workspace_dir


@pytest.mark.parametrize(
    "cmd",
    [
        "New-Item react -ItemType Directory",
        'New-Item -ItemType Directory -Path "react"',
        'New-Item -ItemType Directory -Path "./react"',
        "mkdir react",
    ],
)
def test_guard_fires_on_a_bare_mkdir_of_the_workspace_name(cmd):
    # Fires = returns the offending directory token (truthy); the exact token may keep a
    # `./` prefix, what matters is that the guard recognises the workspace-recreating mkdir.
    assert recreates_the_workspace_dir(cmd, Path("/tmp/react"))


@pytest.mark.parametrize(
    "cmd",
    [
        "New-Item -ItemType Directory src",  # a real subdir
        "ng new react",  # an initializer that names its own dir (hoisted later)
        "django-admin startproject react",  # same
        "npm create vite@latest . -- --template react-ts",  # runs in place, not a bare mkdir
        'New-Item -ItemType Directory -Path "components"',
    ],
)
def test_guard_allows_legit_directory_commands(cmd):
    assert recreates_the_workspace_dir(cmd, Path("/tmp/react")) == ""


def test_execution_seam_returns_noop_success_not_a_failure(tmp_path):
    ws = tmp_path / "react"
    ws.mkdir()
    session = Session(ws)
    out, rc = session.run('New-Item -ItemType Directory -Path "react"')
    # The deadlock fix: exit 0 (no-op), NOT 126 (which halted the plan and looped).
    assert rc == 0, f"a benign workspace-dir mkdir must be a no-op success, got exit {rc}"
    assert "no-op" in out.lower() or "skipped" in out.lower()
    # And it must genuinely do nothing: no nested react/react/ created.
    assert not (ws / "react").exists()
