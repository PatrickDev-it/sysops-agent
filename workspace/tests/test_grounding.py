"""Web search as a structural defence against model obsolescence.

A model's memory of how to invoke a CLI is frozen at its training cutoff, and it does not know
that it does not know. Observed on a live React + Vite scaffold with the 8B planner:

    `vite create --template react-ts $P`   -> a command that has never existed
    `npm install -g vite`                  -> EPERM into C:\\Program Files
    `npm install -g vite`                  -> EPERM again

`supervisor.jinja` already tells the planner to search the web whenever it is unsure of the
current method. It did not. A rule that lives only in a prompt is a suggestion; three separate
defects in this codebase have now taught the same lesson. So the runtime enforces it: a command
whose leading executable the OS cannot resolve is a guess, and the web — not the weights — is
where the current answer lives.

Nothing in `grounding.py` knows what `vite`, `npm` or `npx` are.
"""

import pytest
from src import grounding
from src.config import SRC


@pytest.mark.parametrize(
    "cmd,expected",
    [
        ("vite create --template react-ts", "vite"),
        ('& "C:/tools/foo.exe" --help', "C"),  # a drive-qualified path still yields a name
        ("npm install -g vite", "npm"),
        ("Get-ChildItem .", "Get-ChildItem"),
        ("cd project", ""),  # builtins are resolvable by definition
        ("echo hi", ""),
        ("", ""),
    ],
)
def test_leading_executable(cmd, expected):
    assert grounding.leading_executable(cmd) == expected


class _State:
    def __init__(self):
        self.facts = {}

    def add_fact(self, key, value, source=""):
        self.facts[key] = value


def test_grounding_fires_only_on_a_missing_tool(monkeypatch):
    st = _State()
    assert (
        grounding.should_ground("vite : The term 'vite' is not recognized", "vite create x", st)
        == "vite"
    )


@pytest.mark.parametrize(
    "stderr",
    [
        "npm error code EPERM",  # a permission failure, not a missing tool
        "ERROR: Cannot install urllib3 and botocore",  # a dependency conflict
        "Missing closing '}'",  # a syntax error
        "Timeout after 240s",  # a slow network
    ],
)
def test_other_failures_are_not_grounded(stderr):
    """Grounding a failure it does not understand would be guessing on the model's behalf."""
    assert grounding.should_ground(stderr, "npm install -g vite", _State()) == ""


# The tool EXISTS and rejects the invocation: the model's memory of this CLI is older than the
# CLI. Observed live, right after `vite` was grounded: `npm init vite@latest <name> --template
# react-ts`. `npm` is present, so a missing-tool check alone never fires.
@pytest.mark.parametrize(
    "stderr,cmd,tool",
    [
        (
            "npm error Unknown option: --template",
            "npm init vite@latest app --template react-ts",
            "npm",
        ),
        (
            "error: unrecognized arguments: --typescript",
            "django-admin startproject app --typescript",
            "django-admin",
        ),
        ('ng: Did you mean "generate"?', "ng create app", "ng"),
        ("error: no such command 'create'", "cargo create app", "cargo"),
    ],
)
def test_a_stale_invocation_of_an_existing_tool_is_grounded(stderr, cmd, tool):
    assert grounding.should_ground(stderr, cmd, _State()) == tool


def test_a_tool_is_grounded_at_most_once_per_run(monkeypatch):
    calls = []

    def _fake_search(query, cwd=None, max_results=6):
        calls.append(query)
        return True, "use `npm create vite@latest`"

    monkeypatch.setattr(grounding, "search", _fake_search)
    st = _State()

    found, text = grounding.ground_tool(st, "vite")
    assert found and "npm create" in text
    assert grounding.already_grounded(st, "vite")
    assert grounding.should_ground("'vite' is not recognized", "vite create x", st) == ""

    assert not grounding.ground_tool(st, "vite")[0]
    assert len(calls) == 1


def test_the_query_is_short_and_carries_no_version_os_or_year(monkeypatch):
    """A narrow query returns a stale page — the same rule `supervisor.jinja` prescribes."""
    seen = {}

    def _fake_search(query, cwd=None, max_results=6):
        seen["q"] = query
        return True, "answer"

    monkeypatch.setattr(grounding, "search", _fake_search)
    grounding.ground_tool(_State(), "vite")
    q = seen["q"]
    assert q == "vite latest cli usage"
    assert '"' not in q and "windows" not in q.lower()
    assert not any(ch.isdigit() for ch in q)


def test_a_failed_search_records_nothing(monkeypatch):
    monkeypatch.setattr(grounding, "search", lambda *a, **k: (False, ""))
    st = _State()
    assert not grounding.ground_tool(st, "vite")[0]
    assert not grounding.already_grounded(st, "vite"), "a failed search must not look grounded"


def test_the_runtime_grounds_before_re_authoring():
    src = (SRC / "orchestrator.py").read_text(encoding="utf-8")
    author = src.split("authored = model_router.executor_call(ctx)")[0]
    assert "grounding.should_ground" in author[-1500:], (
        "the web lookup must happen BEFORE the coder re-authors, or the notes arrive too late"
    )


def test_project_name_is_a_runtime_variable_not_a_slot():
    """The project has no name of its own: it IS the workspace.

    Planners kept inventing one (`vite create $PROJECT_NAME`) and leaving `vars.PROJECT_NAME`
    empty. The placeholder guard then refused the command BEFORE the shell could report that
    `vite` does not exist — and grounding, which fires on exactly that report, never ran. Two
    correct guards, composed into a deadlock. The runtime knows the answer, so it supplies it.
    """
    from src.tools.template_guard import unresolved_placeholder

    assert not unresolved_placeholder("vite create $PROJECT_NAME --template react-ts")
    assert not unresolved_placeholder("ng new $PROJECT_NAME")
    assert not unresolved_placeholder("echo $WORKSPACE_PATH")
    # Everything else in SCREAMING_CASE is still a leak.
    assert unresolved_placeholder('& "$DISCOVERED_PATH" --version') == "$DISCOVERED_PATH"


def test_the_runtime_substitutes_project_name_before_execution():
    src = (SRC / "orchestrator.py").read_text(encoding="utf-8")
    assert 'tool.replace("$PROJECT_NAME", _pn)' in src, (
        "PROJECT_NAME is exempted from the placeholder guard, so it MUST be substituted, or an "
        "unresolved token reaches the shell"
    )


@pytest.mark.parametrize(
    "stderr,tool",
    [
        ("vite : The term 'vite' is not recognized as the name of a cmdlet", "vite"),
        ("bash: ng: command not found", "ng"),
        ("'django-admin' is not recognized as an internal or external command", "django-admin"),
        ("command not found: bun", "bun"),
    ],
)
def test_the_tool_is_taken_from_the_error_not_from_the_command(stderr, tool):
    """The error names the thing the shell could not find. The command about to run may name
    something else entirely.

    Observed live: `vite create ...` failed with "the term 'vite' is not recognized"; the coder,
    correctly grounded, re-authored an `npm ...` command; the next pass then received the OLD
    stderr with the NEW command and "discovered" that `npm` — which is on PATH — was
    unresolvable, and searched the web for it. A stale pairing of an error with a command that
    never produced it."""
    assert grounding._missing_tool_name(stderr) == tool
    assert grounding.should_ground(stderr, "npm init vite@latest app", _State()) == tool
