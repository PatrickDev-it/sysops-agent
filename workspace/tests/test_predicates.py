"""Invariant #9 — "a step is COMPLETE only if its expected artifacts exist" — was vacuous:
measured over 127 real plans, 0 of 19 declared criteria were machine-checkable, because the
prompt advertised a vocabulary the evaluator did not implement. These tests pin the single
table both now share, and the distinction that was missing: an empty file is not an artifact.
"""

import pytest
from src.model_router import SUPERVISOR_SCHEMA
from src.tools import predicates


def test_schema_enum_is_exactly_the_evaluable_vocabulary():
    """The grammar the decoder is constrained by, and the table the runtime evaluates, are
    the same object. Drift between them is what made the check vacuous."""
    assert predicates.SCHEMA["properties"]["check"]["enum"] == sorted(predicates.CHECKS)
    step = SUPERVISOR_SCHEMA["properties"]["plan"]["items"]
    assert step["properties"]["success"]["items"] is predicates.SCHEMA


def test_prompt_reference_names_every_check_and_nothing_else():
    """The prompt used to advertise twelve predicates; four existed; one overlapped."""
    ref = predicates.prompt_reference()
    for name in predicates.CHECKS:
        assert f'"check":"{name}"' in ref
    # The vocabulary the model was previously shown, and which nothing could evaluate.
    for invented in (
        "not_empty",
        "command_exits_ok",
        "version_matches",
        "service_running",
        "package_installed",
        "env_var_set",
        "absent",
    ):
        assert f'"check":"{invented}"' not in ref


def test_empty_file_fails_file_has_content(tmp_path):
    """The exact defect: 15 of 48 tasks created an empty .txt and passed every check."""
    (tmp_path / "os_info.txt").write_text("")
    ok, reason = predicates.evaluate(
        [{"check": "file_has_content", "path": "os_info.txt"}], tmp_path
    )
    assert not ok and "empty" in reason


def test_non_empty_file_passes(tmp_path):
    (tmp_path / "os_info.txt").write_text("Windows 10")
    ok, _ = predicates.evaluate([{"check": "file_has_content", "path": "os_info.txt"}], tmp_path)
    assert ok


def test_path_exists_still_tolerates_an_empty_file(tmp_path):
    """`path_exists` keeps its permissive meaning — it is the escape hatch for the cases
    where emptiness is a legitimate outcome, and the prompt says so explicitly."""
    (tmp_path / "empty.log").write_text("")
    ok, _ = predicates.evaluate([{"check": "path_exists", "path": "empty.log"}], tmp_path)
    assert ok


def test_unknown_check_fails_rather_than_being_skipped(tmp_path):
    """Silently ignoring an invented criterion is precisely how the invariant died."""
    ok, reason = predicates.evaluate([{"check": "exit_code_zero", "path": "x"}], tmp_path)
    assert not ok and "unknown check" in reason


@pytest.mark.parametrize(
    "prose",
    [
        "FileExists:python_path.txt",
        "Content not empty",
        "Exit code 0",
        "file_exists($WORKSPACE_PATH\\disk.txt)",
    ],
)
def test_prose_criteria_are_rejected_not_ignored(prose, tmp_path):
    """Real strings emitted by the 8B planner before the schema was typed."""
    ok, reason = predicates.evaluate([prose], tmp_path)
    assert not ok and "not a predicate object" in reason


def test_path_absent_and_dir_not_empty(tmp_path):
    (tmp_path / "d").mkdir()
    assert not predicates.evaluate([{"check": "dir_not_empty", "path": "d"}], tmp_path)[0]
    (tmp_path / "d" / "f").write_text("x")
    assert predicates.evaluate([{"check": "dir_not_empty", "path": "d"}], tmp_path)[0]
    assert predicates.evaluate([{"check": "path_absent", "path": "gone"}], tmp_path)[0]
    assert not predicates.evaluate([{"check": "path_absent", "path": "d"}], tmp_path)[0]


def test_file_contains(tmp_path):
    (tmp_path / "v.txt").write_text("python 3.12.4")
    assert predicates.evaluate(
        [{"check": "file_contains", "path": "v.txt", "text": "3.12"}], tmp_path
    )[0]
    assert not predicates.evaluate(
        [{"check": "file_contains", "path": "v.txt", "text": "3.13"}], tmp_path
    )[0]


def test_render_is_readable_and_lossless_enough_for_the_graph():
    assert predicates.render([{"check": "file_has_content", "path": "a.txt"}]) == [
        "file_has_content(a.txt)"
    ]
    assert predicates.render([{"check": "file_contains", "path": "a", "text": "b"}]) == [
        "file_contains(a, 'b')"
    ]


def test_evaluation_executes_nothing(tmp_path, monkeypatch):
    """A verifier with side effects cannot be trusted to report on what it changed."""
    import subprocess

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: pytest.fail("predicates executed a command")
    )
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **k: pytest.fail("predicates spawned a process")
    )
    predicates.evaluate([{"check": "tool_on_path", "path": "python"}], tmp_path)
