"""
PATCH-017 — a scaffolder rejecting the dir-derived project name must not block
a perfect command. Error-driven recovery: scaffold into a valid-named subdir,
then flatten. Pins the pure helpers.

Observed: workspace "_try" → `npx create-next-app . …` (a correct command) →
"Could not create a project called '_try' because of npm naming restrictions".

Run: python -m pytest tests/test_scaffold_name.py -v
"""

from src.orchestrator import (
    _is_name_invalid_error,
    _is_scaffold_init,
    _rewrite_scaffold_target,
    _sanitize_project_name,
)


def test_npm_naming_error_detected():
    out = (
        'Could not create a project called "_try" because of npm naming '
        "restrictions:\n  * name cannot start with an underscore"
    )
    assert _is_name_invalid_error(out)


def test_non_naming_error_not_matched():
    assert not _is_name_invalid_error("At line:1 char:89  parse error")
    assert not _is_name_invalid_error("EACCES: permission denied")
    assert not _is_name_invalid_error("")


def test_sanitize_project_name():
    assert _sanitize_project_name("_try") == "try"
    assert _sanitize_project_name(".hidden") == "hidden"
    assert _sanitize_project_name("My App") == "my-app"
    assert _sanitize_project_name("___") == "app"  # empty after strip → fallback
    assert _sanitize_project_name("valid-name") == "valid-name"


def test_rewrite_scaffold_target_replaces_only_lone_dot():
    cmd = 'npx create-next-app@latest . --ts --tailwind --import-alias "@/*" --yes'
    out = _rewrite_scaffold_target(cmd, "try")
    assert " try " in out
    assert " . " not in out
    # the version pin and the alias (which contain no lone dot) are untouched
    assert "create-next-app@latest" in out
    assert '--import-alias "@/*"' in out


def test_rewrite_leaves_command_without_dot_target_unchanged():
    cmd = "npx create-next-app@latest my-app --ts"
    assert _rewrite_scaffold_target(cmd, "x") == cmd


def test_end_to_end_recovery_shape():
    # The exact failing case, end to end through the pure helpers.
    tool = 'npx create-next-app@latest . --ts --tailwind --app --eslint --no-src-dir --import-alias "@/*" --yes'
    out = 'Could not create a project called "_try" because of npm naming restrictions'
    assert _is_scaffold_init(tool)
    assert _is_name_invalid_error(out)
    safe = _sanitize_project_name("_try")
    retry = _rewrite_scaffold_target(tool, safe)
    assert retry.startswith("npx create-next-app@latest try ")
    assert "--yes" in retry
