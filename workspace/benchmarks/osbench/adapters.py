"""osbench agent adapters — the bridge between a benchmark case and an agent.

`DryRunAdapter` (in run.py) executes nothing. `LiveOrchestratorAdapter` runs the REAL
dual-GGUF agent (RFC-0005 §1): it hands the case's single natural-language goal to
`src.orchestrator.Orchestrator` in the case's isolated workspace, on GPU, and then reads
back exactly what happened from the run's telemetry record — the same record the agent
writes for every run (`validation/telemetry/<run_id>.json`).

The adapter observes; it never helps. The agent sees only the goal — never the case's
expected_reasoning / expected_commands / success_check (those are graders' keys).
"""

from __future__ import annotations

import time
from pathlib import Path

# osbench and the agent live in the same execution plane (workspace/). This module is
# itself imported lazily — only a live run pays for it — so `src` is already on
# sys.path by the time we get here, and `src.config` is stdlib-only: it loads nothing.
from src.config import TELEMETRY_DIR as _TELEMETRY_DIR

from .run import AdapterResult


def _telemetry_snapshot() -> set[str]:
    return {p.name for p in _TELEMETRY_DIR.glob("*.json")} if _TELEMETRY_DIR.exists() else set()


def _newest_record_since(before: set[str]) -> dict | None:
    """The telemetry record written by the run we just executed.

    Prefer a file that did not exist before the run; fall back to the newest by mtime
    (single-threaded harness, so no race)."""
    import json

    if not _TELEMETRY_DIR.exists():
        return None
    files = list(_TELEMETRY_DIR.glob("*.json"))
    if not files:
        return None
    new = [p for p in files if p.name not in before]
    target = (
        max(new, key=lambda p: p.stat().st_mtime)
        if new
        else max(files, key=lambda p: p.stat().st_mtime)
    )
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None


class LiveOrchestratorAdapter:
    """Runs the real agent on GPU and reports what it actually did.

    After each `run`, `self.last_record` holds the full telemetry dict (environment,
    facts, per-action history with stdout/stderr/exit_code) so a study harness can do
    root-cause analysis without re-running the model.
    """

    name = "live"

    def __init__(self) -> None:
        self.last_record: dict | None = None
        self.last_error: str = ""

    def run(self, goal: str, workspace: Path, case_meta: dict) -> AdapterResult:
        # Lazy import: only a live run pays the model-load / CUDA-bootstrap cost.
        from src.orchestrator import Orchestrator

        self.last_record = None
        self.last_error = ""
        before = _telemetry_snapshot()
        t0 = time.time()
        try:
            Orchestrator(workspace=str(workspace)).run(goal)
        except Exception as e:  # keep the suite going; record it
            self.last_error = f"{type(e).__name__}: {e}"
        latency = time.time() - t0

        rec = _newest_record_since(before)
        self.last_record = rec
        if rec is None:
            return AdapterResult(
                transcript=f"[no telemetry] {self.last_error}",
                commands=[],
                refused=False,
                latency_s=latency,
            )

        history = rec.get("history", []) or []
        commands = [h.get("command", "") for h in history]
        verdict = rec.get("verdict", "")
        refused = verdict == "REFUSED"
        # transcript = the note + each command with its observed output, so `refused`
        # and forbidden-command checks can be evaluated against real behaviour.
        lines = [rec.get("note", "")]
        for h in history:
            out = "\n".join(x for x in (h.get("stdout", ""), h.get("stderr", "")) if x)
            lines.append(f"$ {h.get('command', '')}\n{out}".rstrip())
        return AdapterResult(
            transcript="\n".join(line for line in lines if line).strip(),
            commands=commands,
            refused=refused,
            latency_s=latency,
        )
