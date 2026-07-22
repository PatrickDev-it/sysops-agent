"""The runtime performs the redirection the model kept forgetting.

MEASURED on the 48-task suite: all 27 failures carry the signature `X.txt missing/empty`, and
on most of them (T03 PATH, T06 disk, T07 python_path, T12 pip_list, T05 mem, T20 dns, T30 ping,
T40 ssh) every tool is present and the command runs — the Coder-3B simply never emits
`> X.txt`. Only T35 (docker) fails because the tool is absent.

Capacity in a 3B model was being spent remembering a shell redirection. The step already
declares `file_has_content(X.txt)`; the runtime already holds the stdout.

These tests pin the two rules that keep this from manufacturing false success.
"""

from src.tools.artifact_capture import capture


def test_captures_stdout_into_the_declared_artifact(tmp_path):
    r = capture("mem.txt", "TotalVisibleMemorySize: 33488220", tmp_path)
    assert r.written
    assert (tmp_path / "mem.txt").read_text(encoding="utf-8").startswith("TotalVisibleMemory")


def test_a_failed_step_never_writes_the_artifact(tmp_path):
    """The rule this file first asserted, and which the A/B refuted.

    Capturing a failed probe's stderr seemed right: `docker --version` → "not recognized" is
    the finding when the goal asks to report a tool's absence. MEASURED: on T01 the capture
    wrote the error of `powershell --version` (exit 1) into `os_info.txt`; the never-overwrite
    rule then blocked the *correct* output of the next step, which had succeeded. ARR fell
    from 32/48 to 29/48. An intermediate probe's error is noise, and it poisons the artifact.
    Reporting an absence belongs to a step that SUCCEEDS at saying so."""
    r = capture(
        "containers.txt", "docker : The term 'docker' is not recognized", tmp_path, exit_code=1
    )
    assert not r.written and "step failed" in r.reason
    assert not (tmp_path / "containers.txt").exists()


def test_nothing_is_captured_without_a_declared_target(tmp_path):
    """Declared, never inferred. Deriving the target from the success predicate would write
    the log of `pip install` into `requirements.txt` — vacuous truth with a filesystem write."""
    assert not capture("", "some output", tmp_path).written


def test_an_empty_command_output_captures_nothing(tmp_path):
    r = capture("mem.txt", "   \n  ", tmp_path)
    assert not r.written and "no output" in r.reason
    assert not (tmp_path / "mem.txt").exists(), "an empty artifact must still fail file_has_content"


def test_existing_content_is_never_overwritten(tmp_path):
    """The command wrote it. Capture fills a gap; it does not paper over one."""
    (tmp_path / "out.txt").write_text("the command's own output")
    r = capture("out.txt", "the runtime's stdout", tmp_path)
    assert not r.written
    assert (tmp_path / "out.txt").read_text() == "the command's own output"


def test_an_empty_existing_file_is_filled(tmp_path):
    """The exact defect: `New-Item -ItemType File` created it, nothing wrote into it."""
    (tmp_path / "out.txt").write_text("")
    assert capture("out.txt", "real content", tmp_path).written
    assert (tmp_path / "out.txt").read_text(encoding="utf-8").strip() == "real content"


def test_capture_respects_the_confinement_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SISTEMISTA_CONFINE_ROOT", str(tmp_path))
    r = capture(r"C:\Windows\evil.txt", "payload", tmp_path)
    assert not r.written and "confinement" in r.reason


def test_capture_creates_missing_parents(tmp_path):
    assert capture("reports/disk.txt", "C: 40% free", tmp_path).written
    assert (tmp_path / "reports" / "disk.txt").is_file()


def test_the_plan_schema_exposes_the_field_only_when_the_mechanism_is_on():
    """The control arm must not be able to declare a field the runtime will ignore.

    Measured on the first control run: the planner filled `capture_stdout_to` on 13 steps
    despite the prompt telling it not to, and 12 of those launchers then omitted their own
    redirection. The runtime ignored the field, the artifact was never written, and the
    control lost tasks it would otherwise have passed. An effect size measured against that
    control would have been inflated by the absence of the very mechanism under test."""
    import importlib
    import os

    from src import config, model_router

    assert not config.ARTIFACT_CAPTURE, "unproven: shipped off, see config.ARTIFACT_CAPTURE"
    off = model_router.SUPERVISOR_SCHEMA["properties"]["plan"]["items"]
    assert "capture_stdout_to" not in off["properties"], (
        "with the mechanism off, the grammar must not offer the field at all — a control arm "
        "that can declare a field the runtime ignores is not a control"
    )

    os.environ["SISTEMISTA_CAPTURE"] = "1"
    try:
        importlib.reload(config)
        mr = importlib.reload(model_router)
        on = mr.SUPERVISOR_SCHEMA["properties"]["plan"]["items"]
        assert "capture_stdout_to" in on["properties"]
        assert "capture_stdout_to" not in on["required"], "steps with no report omit it"
    finally:
        os.environ.pop("SISTEMISTA_CAPTURE", None)
        importlib.reload(config)
        importlib.reload(model_router)


def test_the_prompt_forbids_hand_written_redirections():
    """The guidance is a module-level constant, injected by `_render`, so the A/B arm can swap
    it without a Jinja conditional in the system block (which would kill the prefix cache)."""
    from src.model_router import _CAPTURE_GUIDANCE, _REDIRECT_GUIDANCE, _render

    assert "the redirection is the runtime's job" in _CAPTURE_GUIDANCE
    assert "Out-File" in _CAPTURE_GUIDANCE
    # The control arm tells the planner the opposite, so the A/B isolates the mechanism.
    assert "the command must write them" in _REDIRECT_GUIDANCE
    assert "Always leave `capture_stdout_to` empty" in _REDIRECT_GUIDANCE

    rendered = _render(
        "supervisor.jinja",
        dict(
            goal="",
            system_spec="",
            workspace_state="",
            task_brief="",
            research_notes="",
            memory="",
            loop=0,
            ev=[],
        ),
    )
    assert "capture_stdout_to" in rendered
