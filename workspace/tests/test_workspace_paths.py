"""The workspace root must never reach a model. A JSON grammar allows an unbounded run of
legal `\\\\` escape pairs, and the 0.6B planner fell into exactly that hole (857 consecutive
backslashes, string never closed, 39 of 48 runs dead). Remove the source, not the symptom."""

import pytest
from src import workspace_paths as wp


@pytest.fixture(autouse=True)
def _reset():
    yield
    wp.set_root(None)


ROOT = r"C:\Users\ExampleUser\Desktop\Agents\Sistemista\workspace\var\benchmark\oracle_off\workspaces\T01"


def test_disabled_when_no_root():
    wp.set_root(None)
    assert wp.scrub(ROOT) == ROOT


def test_native_spelling_becomes_relative():
    wp.set_root(ROOT)
    assert wp.scrub(rf"Set-Content -Path {ROOT}\os_info.txt") == "Set-Content -Path os_info.txt"


def test_forward_slash_spelling():
    wp.set_root(ROOT)
    posix = ROOT.replace("\\", "/")
    assert wp.scrub(f"cat {posix}/os_info.txt") == "cat os_info.txt"


def test_json_escaped_spelling_is_the_one_that_matters():
    """This is the form the planner actually emitted, and the one that seeds the loop."""
    wp.set_root(ROOT)
    escaped = ROOT.replace("\\", "\\\\")
    out = wp.scrub(f'{{"launcher":"Set-Content -Path \\"{escaped}\\\\os_info.txt\\""}}')
    assert "\\\\" not in out
    assert "os_info.txt" in out


def test_bare_root_becomes_dot():
    wp.set_root(ROOT)
    assert wp.scrub(f"cwd: {ROOT}") == "cwd: ."


def test_paths_outside_the_root_are_untouched():
    """`locate` returns absolute tool paths outside the workspace; they must survive."""
    wp.set_root(ROOT)
    other = r"C:\Program Files\Git\cmd\git.exe"
    assert wp.scrub(f"found: {other}") == f"found: {other}"


def test_scrub_is_idempotent():
    wp.set_root(ROOT)
    once = wp.scrub(rf"{ROOT}\a.txt")
    assert wp.scrub(once) == once


def test_root_level_artifact_carries_no_backslash_at_all():
    """The property that matters for the benchmark: its artifacts live at the workspace
    root, so after scrubbing there is no backslash left to escape, in any spelling."""
    wp.set_root(ROOT)
    for spelling in (ROOT, ROOT.replace("\\", "/"), ROOT.replace("\\", "\\\\")):
        assert "\\" not in wp.scrub(f"{spelling}\\os_info.txt")


def test_nested_relative_paths_still_carry_separators():
    """Honest bound on the fix: only the ROOT prefix is removed. `sub\\file.txt` keeps its
    separator, so a deep tree still offers the model something to escape — just ~10x less
    of it. Eliminating the root removes the long run that actually triggered the loop."""
    wp.set_root(ROOT)
    assert wp.scrub(rf"{ROOT}\sub\file.txt") == r"sub\file.txt"
