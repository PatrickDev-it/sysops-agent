"""Content-authoring path routing (architectural fix, seed-42 control experiment).

Control experiment: the same Qwen2.5-Coder-3B, greedy, seed 42 —
  · asked for "the single shell command" to create server.js → emits an empty
    `New-Item -ItemType File` (a 0-byte file);
  · asked for the file's CONTENT → emits a correct Node.js HTTP server.
So a `file_has_content(X)` step whose launcher is a bare file write is routed to
content authoring (the coder writes X's body, the runtime writes it via fileops),
NOT to a single shell command. These tests pin the routing decision.
"""

import pytest
from src.orchestrator import _content_write_target


def FHC(p):
    return {"check": "file_has_content", "path": p}


@pytest.mark.parametrize(
    "tool",
    [
        "New-Item -Path server.js -ItemType File",
        "New-Item -ItemType File -Path server.js -Value 'x'",
        "Set-Content server.js -Value 'x'",
        "Out-File -FilePath server.js -InputObject 'x'",
        "write_file|server.js|const http = ...",
        "touch server.js",
        "echo hi > server.js",
    ],
)
def test_bare_file_writes_route_to_content_authoring(tool):
    assert _content_write_target([FHC("server.js")], tool) == "server.js"


@pytest.mark.parametrize(
    "tool",
    [
        "npm create vite@latest .",  # a scaffolder produces the file itself
        "ng new app",
        "npm init -y",  # package manager
        "django-admin startproject x",
        "New-Item -ItemType Directory src",  # a directory, not a file body
        "Add-Content server.js -Value 'x'",  # an APPEND — never rewrite the whole file
        "echo hi >> server.js",  # append redirection
    ],
)
def test_scaffolders_pkg_dirs_and_appends_do_not_route(tool):
    assert _content_write_target([FHC("server.js")], tool) is None


def test_requires_exactly_one_content_target():
    # No file_has_content → not a content write.
    assert (
        _content_write_target(
            [{"check": "path_exists", "path": "x"}], "New-Item -Path x -ItemType File"
        )
        is None
    )
    # Two content targets → ambiguous, leave to the shell/plan.
    assert _content_write_target([FHC("a"), FHC("b")], "New-Item a") is None
