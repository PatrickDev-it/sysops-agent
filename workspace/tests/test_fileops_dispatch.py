"""Regression tests for fileops.dispatch argument normalization.

These guard the C2 fix from the Windows Validation Lab (run `full-safe30`): the 3B
executor routinely emits malformed `|`-delimited tool calls — an over-split path
(`make_dir|.github|workflows`) or a `|` inside content — which used to crash with a raw
TypeError that classified as UNKNOWN and gave the recovery layer nothing.

Run: python -m pytest tests/test_fileops_dispatch.py -v
"""

import tempfile
from pathlib import Path

from src.tools import fileops as F


def _cwd() -> Path:
    return Path(tempfile.mkdtemp())


def test_over_split_path_is_rejoined():
    cwd = _cwd()
    ok, _ = F.dispatch("make_dir", [".github", "workflows"], cwd)
    assert ok
    assert (cwd / ".github" / "workflows").is_dir()


def test_list_dir_over_split_path():
    cwd = _cwd()
    (cwd / ".github" / "workflows").mkdir(parents=True)
    ok, _ = F.dispatch("list_dir", [".github", "workflows"], cwd)
    assert ok


def test_pipe_inside_content_is_preserved():
    cwd = _cwd()
    ok, _ = F.dispatch("write_file", ["a.txt", "line1|line2"], cwd)
    assert ok
    assert (cwd / "a.txt").read_text(encoding="utf-8") == "line1|line2"


def test_too_few_args_gives_actionable_error_not_typeerror():
    cwd = _cwd()
    ok, msg = F.dispatch("replace_in_file", ["a.txt", "old"], cwd)
    assert not ok
    assert "needs 3 arg(s)" in msg and "path|old|new" in msg  # names the expected shape


def test_optional_param_not_required():
    # web_search(query, cwd=None, max_results=6) — one arg must be enough.
    cwd = _cwd()
    ok, _ = F.dispatch("web_search", ["some query"], cwd)
    assert ok is True or ok is False  # network optional; must NOT raise / must not 'need 2 args'
    _, msg = F.dispatch("web_search", ["some query"], cwd)
    assert "needs" not in msg


def test_exact_arity_unchanged():
    cwd = _cwd()
    (cwd / "a.txt").write_text("hello", encoding="utf-8")
    ok, out = F.dispatch("read_file", ["a.txt"], cwd)
    assert ok and "hello" in out
