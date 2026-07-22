"""
PATCH-016 — the runtime must not believe signals that prove nothing.

Pins three tightly-coupled fixes for the belief-corruption class (weak point #4)
+ the ANSI-noise that feeds it:
  1. ANSI colour codes are stripped before classification.
  2. a malformed fileops-style call leaked to the shell → COMMAND_SYNTAX
     (regenerate), never FILE_NOT_FOUND (refute a file the shell never checked).
  3. _real_tool yields the VERB, not the whole "verb|path|value" garbage key.

Run: python -m pytest tests/test_garbage_signals.py -v
"""

from src.error_classifier import ErrorClass, classify, is_missing_tool_signal
from src.tools.terminal import _strip_ansi

# ── 1. ANSI hygiene ───────────────────────────────────────────────────────────


def test_ansi_codes_stripped_so_signal_matches():
    coloured = "\x1b[31mThe term 'foo' is not recognized\x1b[39m as a cmdlet"
    assert "\x1b" not in _strip_ansi(coloured)
    # Without stripping, the coloured create-next-app error classified UNKNOWN.
    assert classify(_strip_ansi(coloured), exit_code=1, command="foo") == ErrorClass.FILE_NOT_FOUND


def test_coloured_npm_naming_error_is_not_swallowed():
    raw = 'Could not create a project called \x1b[31m"_try"\x1b[39m because of npm naming restrictions'
    clean = _strip_ansi(raw)
    assert "_try" in clean and "\x1b" not in clean


# ── 2. Malformed fileops-leak → COMMAND_SYNTAX, never FILE_NOT_FOUND ──────────


def test_leaked_fileops_call_is_command_syntax_not_file_not_found():
    out = "test-path-exists : The term 'test-path-exists' is not recognized as the name of a cmdlet"
    cmd = "test-path-exists|postcss.config.js|true"
    assert classify(out, exit_code=1, command=cmd) == ErrorClass.COMMAND_SYNTAX


def test_leaked_fileops_call_is_not_a_missing_tool_signal():
    out = "The term 'test-path-exists' is not recognized"
    cmd = "test-path-exists|app|true"
    assert not is_missing_tool_signal(out, cmd)  # must NOT refute a file


def test_genuine_missing_tool_still_file_not_found():
    out = "The term 'winget' is not recognized as the name of a cmdlet"
    assert classify(out, exit_code=1, command="winget install x") == ErrorClass.FILE_NOT_FOUND
    assert is_missing_tool_signal(out, "winget install x")


def test_real_shell_pipe_is_not_treated_as_fileops_leak():
    # A genuine shell pipe (spaces around |) with a missing first tool stays
    # FILE_NOT_FOUND — the guard keys on the no-space fileops syntax only.
    out = "The term 'realtool' is not recognized"
    assert (
        classify(out, exit_code=1, command="realtool -a | findstr x") == ErrorClass.FILE_NOT_FOUND
    )


def test_locate_probe_is_not_mistaken_for_fileops_leak():
    # A REAL fileop (locate|X) is dispatched internally and never hits the shell
    # with "is not recognized"; its "not found" stays a genuine absence signal.
    assert is_missing_tool_signal("yt-dlp: not found on PATH", "locate|yt-dlp")
