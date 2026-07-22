"""A command that exited 0 and left its artifact empty wrote to the wrong stream.

T40 fails in every archived run of the suite: `ssh -V` prints its version to stderr, so
`& "…\\ssh.exe" -V > ssh_client.txt` exits 0 and leaves a 0-byte file. Seven commands ran,
all exit 0, and the coder — told the command succeeded — re-authored the same redirect.

The runtime does not need a model to settle this: it has the exit code, it can parse the
redirect target, and it can stat the file. These tests pin the rule to STREAMS, never to a
tool name, and pin the two ways it must refuse to fire — an artifact with content, and a
`>` that is not a redirect at all.
"""

from pathlib import Path

import pytest
from src.orchestrator import _redirect_split, _stderr_only_output


@pytest.fixture
def ws(tmp_path):
    return tmp_path


def _empty(ws, name):
    (ws / name).write_text("", encoding="utf-8")
    return ws


def test_the_measured_case_is_repaired(ws):
    _empty(ws, "ssh_client.txt")
    cmd = '& "$env:SystemRoot\\System32\\OpenSSH\\ssh.exe" -V > ssh_client.txt'
    assert _stderr_only_output(cmd, ws) == (
        '& "$env:SystemRoot\\System32\\OpenSSH\\ssh.exe" -V 2>&1 > ssh_client.txt'
    )


def test_the_rule_is_about_streams_not_about_ssh(ws):
    _empty(ws, "v.txt")
    for cmd in ("java -version > v.txt", "gcc --version > v.txt"):
        assert "2>&1" in _stderr_only_output(cmd, ws)


def test_the_pipeline_form_is_repaired(ws):
    _empty(ws, "out.txt")
    assert _stderr_only_output("ssh -V | Out-File -FilePath out.txt", ws) == (
        "ssh -V 2>&1 | Out-File -FilePath out.txt"
    )
    _empty(ws, "s.txt")
    assert "2>&1" in _stderr_only_output("ssh -V | Set-Content s.txt", ws)


def test_a_non_empty_artifact_is_left_alone(ws):
    (ws / "full.txt").write_text("OpenSSH_for_Windows_8.6", encoding="utf-8")
    assert _stderr_only_output("ssh -V > full.txt", ws) == ""


def test_a_missing_artifact_is_left_alone(ws):
    """Nothing was created: that is a different failure, with a different repair."""
    assert _stderr_only_output("ssh -V > never_ran.txt", ws) == ""


def test_a_command_that_already_merges_is_left_alone(ws):
    _empty(ws, "out.txt")
    assert _stderr_only_output("ssh -V 2>&1 > out.txt", ws) == ""
    _empty(ws, "all.txt")
    assert _stderr_only_output("ssh -V *> all.txt", ws) == ""


def test_a_greater_than_inside_quotes_is_not_a_redirect():
    assert _redirect_split('echo "a > b"') == -1
    assert _redirect_split("Write-Output 'x > y'") == -1


def test_comparison_operators_are_not_redirects():
    """`2>` and `1>` already name a stream; `-gt` is not `>` at all."""
    assert _redirect_split("cmd 2> err.txt") == -1
    assert _redirect_split("Where-Object { $_.Length -gt 10 }") == -1


def test_the_last_redirect_wins(ws):
    _empty(ws, "second.txt")
    cmd = "cmd 2> first.txt > second.txt"
    out = _stderr_only_output(cmd, ws)
    assert out.endswith("> second.txt") and "2>&1" in out


def test_an_absolute_target_is_resolved_without_the_cwd(tmp_path):
    target = tmp_path / "abs.txt"
    target.write_text("", encoding="utf-8")
    cmd = f"ssh -V > {target}"
    assert "2>&1" in _stderr_only_output(cmd, Path("C:/nonexistent"))
