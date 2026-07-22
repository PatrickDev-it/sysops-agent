"""Single owner of the per-run event trace: what happened, in order, and why.

`telemetry.py` records the END STATE of a run — what the agent concluded. This answers the
complementary question the end state cannot: which model was asked what, how long it took,
whether the answer was cached, and whether the runtime accepted or rejected it.

WHY THIS FILE WAS REWRITTEN. `begin()` used to disable itself unless SISTEMISTA_TRACE_DIR was
set in the environment, and the only caller that set it was `benchmarks/run_suite.py`. So every
`emit()` in the product — the confinement blocks in `session.py`, the refused writes in
`fileops.py`, the coder gate verdicts, the oracle degradations, every model call — was a
guaranteed no-op whenever a real user ran the agent. An agent that executes shell commands on a
live host produced NO per-action record of what it executed. Post-incident reconstruction was
impossible, and every claim in this tree that something was "measured" was unmeasurable outside
the lab.

Four further properties were missing, each of which alone disqualifies a record from being an
audit trail:

  * `write_text("")` on begin TRUNCATED an existing file for the same run id;
  * records carried `t`, a float offset from process start, and no absolute timestamp, so a
    line could not be correlated with a syslog entry or with anything else on the host;
  * `except Exception: pass` on write meant a full disk erased the trail with no signal;
  * nothing was redacted, so `git clone https://user:token@host` was recorded verbatim.

Ordering note: redaction had to exist BEFORE this file was allowed to default to on. Switching
the trail on without it would have written credentials to disk on every run.

Never raises. A trace that breaks a run is worse than no trace — but it fails LOUDLY once, and
withholds a record it cannot redact, rather than emitting it raw.
"""

from __future__ import annotations

import itertools
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .redact import redact

_lock = threading.Lock()
_path: Path | None = None
_run_id: str = ""
_t0: float = 0.0
_seq = itertools.count()
_write_failed = False


def _trace_dir() -> Path:
    """Resolved per call, so relocating `config.VAR` relocates the trail with it."""
    return Path(os.environ.get("SISTEMISTA_TRACE_DIR") or (config.VAR / "trace"))


def begin(run_id: str, out_dir: str | Path | None = None) -> Path | None:
    """Start a trace. Defaults to `var/trace/`; an unset environment no longer disables it.

    First-wins: while a trail is active, a second `begin()` cannot redirect it. The benchmark
    harness opens the trail per task and then calls `Orchestrator.run`, which opens its own;
    last-wins silently moved every event to `var/trace/` and left the harness file at 0 bytes —
    the per-call ledger the suite exists to produce. The refusal leaves a record in the active
    trail, so a stolen-begin attempt is visible where the events actually went.
    """
    global _path, _run_id, _t0, _seq, _write_failed
    if _path is not None:
        print(
            f"[trace] begin({run_id!r}) ignored: trail {_run_id!r} is active at {_path}",
            file=sys.stderr,
        )
        emit("trace_begin_ignored", requested_run_id=run_id)
        return None
    try:
        d = Path(out_dir) if out_dir else _trace_dir()
        d.mkdir(parents=True, exist_ok=True)
        _run_id, _t0 = run_id, time.time()
        _seq = itertools.count()
        _write_failed = False
        path = d / f"{run_id}.calls.jsonl"
        # Exclusive create: an existing trace for this run id is never truncated. run_id now
        # carries a uuid suffix, so a collision means something is wrong and must be visible.
        with path.open("x", encoding="utf-8"):
            pass
        _path = path
        return _path
    except FileExistsError:
        print(
            f"[trace] {run_id} already has a trace file; refusing to overwrite it", file=sys.stderr
        )
        _path = None
        return None
    except Exception as exc:
        print(f"[trace] could not start the audit trail: {exc}", file=sys.stderr)
        _path = None
        return None


def end() -> None:
    global _path
    _path = None


def emit(kind: str, **fields) -> None:
    """Append one record. Every string value passes through redaction on the way out."""
    global _write_failed
    if _path is None:
        return
    try:
        rec = {
            "run_id": _run_id,
            # Absolute UTC first: a record that cannot be correlated with the rest of the host's
            # logs is a diary, not an audit trail. `t` (offset) and `seq` are kept because they
            # order records inside the run even when two land in the same millisecond.
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "t": round(time.time() - _t0, 3),
            "seq": next(_seq),
            "kind": kind,
            **{k: (redact(v) if isinstance(v, str) else v) for k, v in fields.items()},
        }
        line = json.dumps(rec, default=str, ensure_ascii=False)
        with _lock:
            with _path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception as exc:
        # Once, not per record: a full disk would otherwise produce one stderr line per event.
        if not _write_failed:
            _write_failed = True
            print(
                f"[trace] audit record lost ({type(exc).__name__}: {exc}); "
                f"further losses will not be reported",
                file=sys.stderr,
            )


def active() -> bool:
    return _path is not None
