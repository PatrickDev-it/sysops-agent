"""
Regression guard for PATCH-015 — a failed external tool must not be "recovered"
by fabricating the artifact it was supposed to generate (FORBIDDEN_ALWAYS
'create_fake_output', previously dead code).

Run: python -m pytest tests/test_fabrication_guard.py -v
"""

from src.config import ROOT
from src.error_classifier import is_recovery_forbidden
from src.orchestrator import _has_fabricated_workspace_path, _is_fabrication_fix


def test_scaffold_failure_recovered_by_handwritten_manifest_is_fabrication():
    # The exact observed pathology: create-next-app fails, "fix" writes package.json.
    assert _is_fabrication_fix(
        "npx create-next-app@latest . --ts --tailwind",
        'write_file|package.json|{"name":"my-next-app"}',
    )
    assert _is_fabrication_fix("npm init", "append_file|package.json|{}")


def test_fileop_step_recovered_by_fileop_is_legitimate():
    # A step whose OWN tool was a fileop may legitimately retry with a fileop.
    assert not _is_fabrication_fix("write_file|config.js|x", "write_file|config.js|y")


def test_external_tool_recovered_by_another_command_is_legitimate():
    # Recovering a failed external tool with a corrected command is fine —
    # only hand-writing its OUTPUT is forbidden.
    assert not _is_fabrication_fix(
        "npx create-next-app@latest",
        "npx create-next-app@latest . --ts --app --use-npm",
    )
    assert not _is_fabrication_fix("npm install foo", "npm install foo --save-dev")


def test_empty_inputs_are_not_fabrication():
    assert not _is_fabrication_fix("", "write_file|x|y")
    assert not _is_fabrication_fix("npx create-next-app", "")


def test_forbidden_invariant_is_live():
    # The invariant the guard enforces must actually be consultable (not dead).
    forbidden, why = is_recovery_forbidden("create_fake_output")
    assert forbidden and why


# ── _has_fabricated_workspace_path ────────────────────────────────────────────
# The guard used to key on a literal `.workspace` path segment, so renaming the checkout
# silently disabled it. It is now anchored to the project root itself. These pin both the
# behaviour and the property that made the old spelling fragile.

REAL = ROOT / "_sandbox" / "_try"


def test_invented_sibling_inside_the_project_tree_is_fabrication():
    # The observed pathology: a plausible sibling that is not the workspace it was given.
    assert _has_fabricated_workspace_path(f"Remove-Item {ROOT}\\_try\\src", REAL)


def test_the_real_workspace_and_its_children_are_legitimate():
    assert not _has_fabricated_workspace_path(f"cd {REAL}", REAL)
    assert not _has_fabricated_workspace_path(f"Set-Content {REAL}\\out.txt", REAL)
    # An ancestor of the workspace is a prefix, not an invention.
    assert not _has_fabricated_workspace_path(f"ls {ROOT}", REAL)


def test_paths_outside_the_project_tree_are_none_of_the_guards_business():
    # This is what the guard is FOR: only our own tree is suspect. A model may legitimately
    # name any other absolute path on the machine — a tool, a system dir, the user's code.
    assert not _has_fabricated_workspace_path(r"C:\Program Files\Git\cmd\git.exe --version", REAL)
    assert not _has_fabricated_workspace_path(r"cd C:\Users\dev\workspace\other", REAL)


def test_forward_slash_spelling_of_a_project_path_still_trips_it():
    # A model handed `C:\a\b` frequently echoes it back as `C:/a/b`.
    posix = str(ROOT).replace("\\", "/")
    assert _has_fabricated_workspace_path(f"rm -rf {posix}/_try/src", REAL)


def test_sibling_sharing_a_string_prefix_is_not_the_workspace():
    # `.../_try_old` starts with `.../_try` as a raw string but is a different directory.
    # Comparing on component boundaries is what catches this.
    assert _has_fabricated_workspace_path(f"Remove-Item {REAL}_old\\src", REAL)


def test_checkout_sharing_the_project_string_prefix_is_outside_the_tree():
    assert not _has_fabricated_workspace_path(f"ls {ROOT}_old", REAL)


def test_exact_workspace_ancestor_is_legitimate_but_its_other_child_is_not():
    parent = REAL.parent
    assert not _has_fabricated_workspace_path(f"ls {parent}", REAL)
    assert _has_fabricated_workspace_path(f"Remove-Item {parent}\\other\\src", REAL)


def test_one_fabricated_reference_is_not_hidden_by_a_real_one():
    command = f"Get-ChildItem {REAL}; Remove-Item {ROOT}\\invented\\src"
    assert _has_fabricated_workspace_path(command, REAL)
