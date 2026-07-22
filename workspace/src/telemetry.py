"""
Telemetry (FASE 8) — every run is explainable.

Writes one JSON record per run to var/telemetry/<run_id>.json containing:
  run_id, goal, environment snapshot, capabilities probed, facts discovered,
  full action history, decisions, failures, final verdict.

The point: the system must be able to answer "why did it choose this action?"
after the fact, from data, not from re-running the model.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from . import config
from .redact import redact_mapping

if TYPE_CHECKING:
    from .state import SystemState


def record_run(
    state: "SystemState",
    goal: str,
    verdict: str,
    note: str = "",
) -> Path | None:
    """Persist a run record. Never raises — telemetry must not break a run."""
    try:
        # Resolved per call so a relocated `config.VAR` takes the telemetry with it.
        telemetry_dir = config.TELEMETRY_DIR
        telemetry_dir.mkdir(parents=True, exist_ok=True)
        record: dict[str, object] = {
            "run_id": state.run_id,
            "goal": goal,
            "verdict": verdict,
            "note": note,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "environment": state.environment.to_dict(),
            "capabilities": {k: v.to_dict() for k, v in state.capabilities.items()},
            "facts": {k: v.to_dict() for k, v in state.facts.items()},
            # The DecisionGraph: typed nodes with prediction/observation/edges —
            # the decision-engine consumes this as provenance=OBSERVED.
            "decisions": state.decisions.to_dict(),
            "world": state.world.to_dict(),
            "history": [r.to_dict() for r in state.history],
        }
        # The record serialises SystemState wholesale, and `facts` holds the raw stdout of
        # DISCOVERY steps — whatever the plan happened to probe, up to and including
        # `Get-ChildItem Env:`. Confirmed in var/telemetry/ before this change: the operator's
        # username and home directory sat there in cleartext. Redaction walks the structure,
        # so it reaches nested history entries and fact values, not just the top level.
        record = redact_mapping(record)
        out = telemetry_dir / f"{state.run_id}.json"
        if out.exists():
            # run_id is timestamp + uuid, so a collision means two runs believe they are the
            # same run. Overwriting would destroy the earlier record silently, which is the
            # single thing an audit artifact must never do.
            out = telemetry_dir / f"{state.run_id}.{int(time.time() * 1000)}.json"
        out.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
        return out
    except Exception as exc:
        # Telemetry must not break a run, but a lost audit record must not be invisible either:
        # a full disk previously produced no file and no signal.
        print(f"[telemetry] run record NOT written ({type(exc).__name__}: {exc})", file=sys.stderr)
        return None
