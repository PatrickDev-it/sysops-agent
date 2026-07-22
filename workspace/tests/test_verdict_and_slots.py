"""Three defects the framework stress suite found, each of them a rule that had a hole in it.

1. **The placeholder guard demanded three characters.** `_UNRESOLVED_VAR_RE` was
   `[A-Z][A-Z0-9_]{2,}`, so `$P` and `$D` sailed through — and those are exactly the names
   `supervisor.jinja` teaches by example. PowerShell expanded them to the empty string, the
   command failed for a reason nobody had written down, and grounding blamed the wrong tool.

2. **Grounding trusted a regex over the operating system.** `npx` was searched for on the web
   because a text heuristic saw "is not recognized" in an error that was really about an empty
   argument. `npx` is on PATH. The OS is authoritative about what it can resolve.

3. **The LLM verifier could declare a goal complete over an empty workspace.** The `django`
   scaffold reported `TASK COMPLETE` with no `manage.py` anywhere: the goal's own
   `file_has_content(manage.py)` predicate was never consulted at the moment the verdict was
   issued. A verifier that evidence can overrule is a verifier; one that it cannot is an opinion.
"""

import pytest
from src import grounding
from src.config import SRC
from src.tools.template_guard import unresolved_placeholder

ORCHESTRATOR = SRC / "orchestrator.py"


class _State:
    def __init__(self):
        self.facts = {}

    def add_fact(self, key, value, source=""):
        self.facts[key] = value


@pytest.mark.parametrize(
    "cmd,leak",
    [
        ("npx @angular/cli new $P --no-routing", "$P"),
        ("ng new x --directory $D", "$D"),
        ('& "$DISCOVERED_PATH" --version', "$DISCOVERED_PATH"),
    ],
)
def test_a_one_character_slot_is_still_a_slot(cmd, leak):
    assert unresolved_placeholder(cmd) == leak


@pytest.mark.parametrize(
    "cmd",
    [
        "ng new $PROJECT_NAME",  # substituted by the runtime
        "echo $WORKSPACE_PATH",  # substituted by the runtime
        "echo $env:PATH",  # a real PowerShell variable
        "Set-Content x -Value $totalRAM",  # lowercase: a user variable, not a slot
    ],
)
def test_runtime_variables_and_real_shell_variables_pass(cmd):
    assert not unresolved_placeholder(cmd)


def test_the_os_decides_what_is_missing_not_a_regex():
    """`npx` exists. An error mentioning "is not recognized" does not make it disappear."""
    assert grounding.should_ground("npx: is not recognized as blah", "npx create x", _State()) == ""


def test_a_tool_the_os_cannot_resolve_is_still_grounded():
    assert (
        grounding.should_ground("The term 'vite' is not recognized", "vite create x", _State())
        == "vite"
    )


def test_a_stale_invocation_grounds_the_existing_tool():
    """The tool exists and rejected the call — that is precisely the one to look up. The
    `which()` check applies only to the missing-tool branch."""
    assert (
        grounding.should_ground(
            "npm error Unknown option: --template",
            "npm init vite@latest app --template x",
            _State(),
        )
        == "npm"
    )


def test_the_filesystem_overrules_the_verifier():
    src = ORCHESTRATOR.read_text(encoding="utf-8")
    assert "filesystem_beats_verifier" in src, (
        "the LLM verifier can declare COMPLETE over an empty workspace unless the goal's own "
        "filesystem predicates are evaluated at the moment the verdict is issued"
    )
    # The override must sit BEFORE the COMPLETE verdict is returned, not after. The verdict is
    # a typed value now rather than a string written into a telemetry call: each terminal path
    # returns `RunVerdict.COMPLETE` and `run()` owns the single telemetry write, so that a run
    # which raises still leaves a record instead of vanishing.
    override = src.index("filesystem_beats_verifier")
    complete = src.index("return RunVerdict.COMPLETE", override)
    between = src[override:complete]
    assert "achieved, reason = False" in between


def test_the_override_only_uses_filesystem_predicates():
    """`tool_on_path(python)` must not be able to veto a genuinely finished task, nor to
    rescue an unfinished one."""
    from src.tools import predicates

    assert predicates.filesystem_criteria([{"check": "tool_on_path", "path": "python"}]) == []
