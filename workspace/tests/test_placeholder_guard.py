"""Invariant #2, as stated: `<token>`, `{SLOT}` and `$VAR` are blocked at the execution point.

The invariant named three syntaxes and the implementation had no brace pattern at all. These
reached the shell: `{SLOT}`, `${TARGET}`, `{{ path }}`, `%USERNAME%`, `<path here>`.

`${TARGET}` is the one that costs real damage. PowerShell expands an undefined variable to the
EMPTY STRING, so `Remove-Item -Recurse ${TARGET}` arrives as `Remove-Item -Recurse` operating on
the current directory. cmd.exe does the same with `%VAR%` inside any `cmd /c` sub-invocation.
This tree has already paid for that exact class once — `$P` and `$D` slipped past a `{2,}`
quantifier — and fixed only the SCREAMING_CASE arm.
"""

import pytest
from src.tools.template_guard import unresolved_placeholder


@pytest.mark.parametrize(
    "command",
    [
        "Remove-Item -Recurse {SLOT}",
        "Remove-Item -Recurse ${TARGET}",
        "npm create vite@latest {{ project }}",
        "echo %USERNAME%",
        "Set-Content <path here> -Value x",
        "& <TOOL> --version",
        "pip install $PACKAGE",
        "python $P",  # one character is enough to be a slot
        "cp file ${DEST}/out",
    ],
)
def test_unresolved_slots_are_blocked(command):
    assert unresolved_placeholder(command), f"reached the shell unresolved: {command!r}"


def test_the_empty_expansion_case_is_named():
    """The reason this matters, pinned as a distinct case."""
    assert unresolved_placeholder("Remove-Item -Recurse -Force ${TARGET}") == "${TARGET}"


@pytest.mark.parametrize(
    "command",
    [
        "npm run build",
        "python -m pip install requests",
        "Get-ChildItem $env:APPDATA",  # a real PowerShell variable
        "echo $HOME",  # a real shell variable, lowercase-adjacent
        'Set-Content out.txt -Value "$totalRAM"',  # a VALUE, not a slot
        "git commit -m 'fix: handle {} in paths'",
        'jq ".items[0]" data.json',
    ],
)
def test_resolved_commands_pass(command):
    """A false positive blocks a legitimate command and the agent cannot make progress, so
    over-blocking is not the safe direction either."""
    assert unresolved_placeholder(command) == "", f"false positive on {command!r}"


def test_the_runtime_substituted_names_are_not_slots():
    """`$WORKSPACE_PATH` and `$PROJECT_NAME` are resolved upstream by the runtime."""
    assert unresolved_placeholder("cd $WORKSPACE_PATH") == ""
    assert unresolved_placeholder("npm create vite@latest ${WORKSPACE_PATH}") == ""


def test_the_guard_is_bounded_on_hostile_input():
    """A stray `<` or `{` must not make the scan quadratic on a long line."""
    import time

    payload = "echo " + "<" + "a" * 200_000
    t0 = time.perf_counter()
    unresolved_placeholder(payload)
    assert time.perf_counter() - t0 < 0.5
