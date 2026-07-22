"""The runtime performs the redirection, not the model.

MEASURED on the 48-task suite: 27 of the 27 failures carry one signature — `X.txt
missing/empty`. On most of them (`T03` PATH, `T06` disk, `T07` python_path, `T12` pip_list,
`T05` mem, `T20` dns, `T30` ping, `T40` ssh) every tool is present and the command runs. The
Coder-3B simply never emits `> X.txt`. Only `T35` (docker) fails for the reason first assumed,
namely that the tool is absent.

That reframes the defect. It is not a missing branch in the planner: it is capacity in a 3B
model being spent on remembering a shell redirection. The step already declares
`file_has_content(X.txt)`; the runtime already holds the command's stdout. Writing one into
the other is a deterministic operation, and a runtime that requires less intelligence from the
model is the whole point.

Two rules keep this from manufacturing false success — the failure mode this codebase has
already made twice:

  1. **Declared, never inferred.** The plan must set `capture_stdout_to`. Deriving the target
     from the success predicate would redirect the log of `pip install` into
     `requirements.txt` and turn a correct FAIL into a PASS. That is vacuous truth with a
     filesystem write attached.
  2. **Never overwrite content.** If the file already exists non-empty, the command wrote it
     and the runtime keeps its hands off. Capture fills a gap; it does not paper over one.

A step whose command produced no output captures nothing: an empty artifact still fails
`file_has_content`, which is exactly what should happen.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import trace
from .confinement import Confinement


@dataclass(frozen=True)
class CaptureResult:
    written: bool
    reason: str
    path: str = ""
    bytes_written: int = 0


def capture(target: str, output: str, cwd: str | Path, *, exit_code: int = 0) -> CaptureResult:
    """Write a SUCCESSFUL step's observed output into the artifact the step declared.

    The first version did not gate on `exit_code`, reasoning that a failed probe
    (`docker --version` → "not recognized") is itself the finding when the goal asks to
    report a tool's absence. MEASURED, and wrong: on T01 the capture wrote the error text of
    `powershell --version` (exit 1) into `os_info.txt`; the never-overwrite rule then blocked
    the *correct* output of the next step, which had succeeded. ARR fell from 32/48 to 29/48.

    A failed probe's stderr is the finding only for the LAST step of a plan. For an
    intermediate DISCOVERY step it is noise, and writing it poisons the artifact. Reporting a
    tool's absence is therefore a job for an explicit step that succeeds at saying so — not
    for the runtime silently promoting an error message to an answer.
    """
    target = (target or "").strip()
    if not target:
        return CaptureResult(False, "no capture target declared")

    if exit_code != 0:
        trace.emit(
            "artifact_capture",
            written=False,
            path=target,
            reason="step failed",
            exit_code=exit_code,
        )
        return CaptureResult(False, "step failed — its output is not the answer")

    text = (output or "").strip()
    if not text:
        return CaptureResult(False, "command produced no output")

    confine = Confinement.from_env()
    if confine is not None:
        violation = confine.check_path(target)
        if violation:
            trace.emit("artifact_capture", written=False, path=target, reason=violation)
            return CaptureResult(False, f"confinement: {violation}")

    p = Path(target)
    path = p if p.is_absolute() else (Path(cwd) / p)
    try:
        if path.is_file() and path.stat().st_size > 0:
            return CaptureResult(False, "artifact already has content — command wrote it")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    except OSError as exc:
        trace.emit("artifact_capture", written=False, path=str(path), reason=str(exc))
        return CaptureResult(False, f"write failed: {exc}")

    n = len(text) + 1
    trace.emit("artifact_capture", written=True, path=str(path), bytes=n, exit_code=exit_code)
    return CaptureResult(True, "captured", str(path), n)
