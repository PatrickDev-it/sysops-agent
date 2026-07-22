"""`New-Item -ItemType File -Value "<content>"` is routed through native fileops.

A multi-line -Value sent to PowerShell over the PTY breaks: the first physical line ends with an
unterminated string, so the file is never written. Measured on node_backend — the coder authored
a 4-line `New-Item ... -Value "const http = ...` and server.js came out "not a file", looping the
recovery. The runtime writes it directly (Python), no shell quoting.

Left ALONE: a bare `New-Item -ItemType File X` (an empty-file touch, no content) and any
`New-Item -ItemType Directory` (a directory, not a content write).
"""

from src.orchestrator import _intercept_content_cmd


def test_multiline_new_item_value_routes_to_fileops(tmp_path):
    cmd = (
        "New-Item -ItemType File -Path server.js -Value \"const http = require('http');\n"
        "http.createServer((req, res) => res.end('ok')).listen(3000);\""
    )
    res = _intercept_content_cmd(cmd, tmp_path)
    assert res is not None, (
        "a New-Item -Value content write must be intercepted, not sent to the shell"
    )
    ok, _msg = res
    assert ok
    f = tmp_path / "server.js"
    assert f.is_file(), "server.js must actually be created"
    body = f.read_text(encoding="utf-8")
    assert "createServer" in body and "listen(3000)" in body, (
        "the full multi-line content must survive"
    )
    assert "\n" in body, "the newline inside -Value must be preserved, not truncate the command"


def test_path_before_or_value_at_end_single_line(tmp_path):
    res = _intercept_content_cmd(
        'New-Item -ItemType File -Path a.txt -Value "hello world"', tmp_path
    )
    assert res is not None and res[0]
    assert (tmp_path / "a.txt").read_text(encoding="utf-8").strip() == "hello world"


def test_bare_touch_without_value_is_not_intercepted(tmp_path):
    # No -Value = an empty-file touch; that is a legitimate shell op, leave it alone.
    assert _intercept_content_cmd("New-Item -ItemType File -Path .gitkeep", tmp_path) is None


def test_new_item_directory_is_not_intercepted(tmp_path):
    assert _intercept_content_cmd("New-Item -ItemType Directory -Path src", tmp_path) is None
