"""
Unified telemetry schema v2 (M0/F0).

The v1 telemetry captures run-level facts + a history of actions with `duration`,
but does NOT capture the two metrics the v2 thesis lives or dies by:
  - tokens per decision (prompt + completion)     → tokens/task
  - parse success per model decision               → parse-error rate

This module defines the unified record and a minimal, dependency-free recorder.
It is INTENTIONALLY additive: it does not touch the live telemetry.py writer.
The single integration point is documented below (INTEGRATION) so the migration
can wire it once the A/B validates the thesis.

Design (aligned with brain/architecture-next/telemetry.md):
  Run = { meta, environment, decisions[], actions[], outcome }
  Decision = one model call OR one deterministic control action, with cost/latency/parse.
Everything is append-only and machine-aggregatable by arr_aggregator.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

SCHEMA_VERSION = "2.0"

DecisionKind = Literal[
    "plan", "verify", "recover", "pty_fallback", "fix", "safety", "deterministic"
]


@dataclass
class Decision:
    """One cognitive decision. `kind=deterministic` = no model was called (System-1)."""

    kind: DecisionKind
    model: str = ""  # "" for deterministic
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    parse_ok: bool = True  # did the model output validate to the expected schema?
    retries: int = 0
    context_mode: str = "current"  # "current" | "compiled" — for A/B tagging
    ts: float = field(default_factory=time.time)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def used_model(self) -> bool:
        return self.kind != "deterministic" and bool(self.model)


@dataclass
class Action:
    """One executed effect (mirrors v1 history entry, kept for continuity)."""

    command: str
    success: bool
    exit_code: int | None
    duration: float
    stderr: str = ""


@dataclass
class RunRecord:
    run_id: str
    goal: str
    verdict: str = "INCOMPLETE"  # COMPLETE | INCOMPLETE | REFUSED
    ts: str = ""
    schema_version: str = SCHEMA_VERSION
    environment: dict = field(default_factory=dict)
    decisions: list[Decision] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    note: str = ""

    # ---- derived metrics (the numbers the thesis is judged on) ----
    def tokens_total(self) -> int:
        return sum(d.total_tokens for d in self.decisions)

    def model_calls(self) -> int:
        return sum(1 for d in self.decisions if d.used_model)

    def model_call_ratio(self) -> float:
        return self.model_calls() / len(self.decisions) if self.decisions else 0.0

    def parse_error_rate(self) -> float:
        model_decisions = [d for d in self.decisions if d.used_model]
        if not model_decisions:
            return 0.0
        return sum(1 for d in model_decisions if not d.parse_ok) / len(model_decisions)

    def model_latency_ms(self) -> float:
        return sum(d.latency_ms for d in self.decisions if d.used_model)

    def action_latency_s(self) -> float:
        return sum(a.duration for a in self.actions)

    def metrics(self) -> dict:
        return {
            "verdict": self.verdict,
            "tokens_total": self.tokens_total(),
            "model_calls": self.model_calls(),
            "model_call_ratio": round(self.model_call_ratio(), 4),
            "parse_error_rate": round(self.parse_error_rate(), 4),
            "model_latency_ms": round(self.model_latency_ms(), 1),
            "action_latency_s": round(self.action_latency_s(), 3),
            "n_decisions": len(self.decisions),
            "n_actions": len(self.actions),
        }

    def to_dict(self) -> dict:
        d = asdict(self)
        d["metrics"] = self.metrics()
        return d

    def write(self, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / f"{self.run_id}.json"
        p.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return p


def normalize_legacy(rec: dict) -> RunRecord:
    """Best-effort upgrade of a v1 telemetry record to the v2 schema.

    Legacy records have no per-decision token/parse data, so `decisions` stays empty
    and token/parse metrics are 0 (correctly signalling "not instrumented").
    """
    actions = []
    for h in rec.get("history", []) or []:
        if not isinstance(h, dict):
            continue
        actions.append(
            Action(
                command=str(h.get("command", ""))[:200],
                success=bool(h.get("success", False)),
                exit_code=h.get("exit_code"),
                duration=float(h.get("duration", 0) or 0),
                stderr=str(h.get("stderr", ""))[:200],
            )
        )
    return RunRecord(
        run_id=rec.get("run_id", "legacy"),
        goal=rec.get("goal", ""),
        verdict=(rec.get("verdict", "INCOMPLETE") or "INCOMPLETE").upper(),
        ts=rec.get("ts", ""),
        schema_version="1.0-legacy",
        environment=rec.get("environment", {}) or {},
        actions=actions,
        note=rec.get("note", ""),
    )


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRATION (for the migration, not wired now — keeps the running system stable):
#
#   In model_router.py, each *_call() that invokes a model should return, alongside
#   its result, the token usage and a parse_ok flag, e.g. from llama_cpp:
#       out = llm.create_completion(prompt, ...)
#       usage = out["usage"]              # {prompt_tokens, completion_tokens}
#       parse_ok = _json_loaded_cleanly
#   The orchestrator then appends:
#       run.decisions.append(Decision(kind="plan", model="supervisor-4B",
#           prompt_tokens=usage["prompt_tokens"], completion_tokens=usage["completion_tokens"],
#           latency_ms=elapsed_ms, parse_ok=parse_ok, context_mode=ctx_mode))
#   At run end: run.write(validation/telemetry/).  arr_aggregator already reads it.
# ─────────────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    # Self-test: build a synthetic record and print its metrics.
    r = RunRecord(run_id="selftest", goal="demo", verdict="COMPLETE")
    r.decisions.append(
        Decision(
            kind="plan",
            model="supervisor-4B",
            prompt_tokens=1800,
            completion_tokens=220,
            latency_ms=2400,
            parse_ok=True,
        )
    )
    r.decisions.append(Decision(kind="deterministic"))
    r.decisions.append(
        Decision(
            kind="verify",
            model="supervisor-4B",
            prompt_tokens=900,
            completion_tokens=60,
            latency_ms=1100,
            parse_ok=False,
            retries=1,
        )
    )
    r.actions.append(
        Action(command="systemctl status nginx", success=True, exit_code=0, duration=0.4)
    )
    print(json.dumps(r.metrics(), indent=2))
