"""
decisions.py — DecisionGraph: every choice the runtime makes, as a typed node.

Before this module the runtime *made* decisions (which command, whether policy
allows it, whether the outcome matches) but never *reified* them: telemetry
recorded actions, `decisions` was always []. The decision-engine
(brain/decision-engine/) therefore ran in RECONSTRUCTED mode — metacognition
without observations.

This module is the runtime spine of the Predict → Observe → Compare → Update
cycle:

  PROPOSED   a command is about to be attempted (with a prediction: the step's
             success criteria — what the world should look like afterwards)
  BLOCKED    the deterministic policy layer vetoed it (ExecutionPolicyGuard,
             OCKE, safety) — the model never gets to be wrong
  EXECUTED   the action ran; observation attached (exit, achieved, error class)
  CONFIRMED  observation matches prediction  → the world model was right
  DIVERGED   observation contradicts prediction → the divergence IS the
             learning signal (belief conclusions captured on the node)

Nodes are linked, not listed: RETRY_OF chains attempts on one step, REPLACES
marks a fix-command substitution, RECOVERS ties a recovery-pass step to the
failed final verify. The per-run result is a DecisionGraph the decision-engine
consumes as-is (provenance=OBSERVED, no reconstruction).

Deterministic, stdlib-only, in-RAM per run (invariant 1). No model calls.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DecisionState(str, Enum):
    PROPOSED = "proposed"
    BLOCKED = "blocked"  # deterministic veto — never executed
    EXECUTED = "executed"  # ran, observation attached, not yet compared
    CONFIRMED = "confirmed"  # observation matches prediction
    DIVERGED = "diverged"  # observation contradicts prediction


class DecisionKind(str, Enum):
    PLAN = "plan"  # supervisor produced the initial plan
    REPLAN = "replan"  # supervisor re-planned after incomplete verify
    STEP = "step"  # a plan step attempt
    FIX = "fix"  # executor-suggested replacement command
    TOOL_SUGGESTION = "tool_suggestion"  # tool self-reported replacement
    FINAL_VERIFY = "final_verify"  # end-of-plan goal verification


class EdgeKind(str, Enum):
    RETRY_OF = "retry_of"  # attempt n → attempt n-1 on the same step
    REPLACES = "replaces"  # fix command → the command it replaced
    RECOVERS = "recovers"  # recovery-pass decision → the failed final verify
    FOLLOWS = "follows"  # plan-order dependency (implicit, step_index)


@dataclass
class Prediction:
    """What the runtime expects the world to look like if this goes right."""

    expects_success: bool = True
    success_criteria: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "expects_success": self.expects_success,
            "success_criteria": list(self.success_criteria),
        }


@dataclass
class Observation:
    """What actually happened. Compare against Prediction → CONFIRMED/DIVERGED."""

    run_ok: bool = False
    achieved: bool = False
    reason: str = ""
    error_class: str = ""
    latency_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "run_ok": self.run_ok,
            "achieved": self.achieved,
            "reason": self.reason[:200],
            "error_class": self.error_class,
            "latency_s": round(self.latency_s, 3),
        }


@dataclass
class Decision:
    id: str
    kind: DecisionKind
    state: DecisionState
    step_id: str = ""
    step_type: str = ""
    attempt: int = 0
    command: str = ""  # truncated at ingestion
    source: str = ""  # "plan" | "executor_fix" | "tool_suggestion" | "supervisor"
    policy_reason: str = ""  # set when BLOCKED
    prediction: Prediction = field(default_factory=Prediction)
    observation: Optional[Observation] = None
    conclusions: list[str] = field(default_factory=list)  # belief/world updates (the Update)
    parent_id: str = ""
    edge: str = ""  # EdgeKind linking this node to parent_id
    ts: float = field(default_factory=time.time)

    @property
    def diverged(self) -> bool:
        return self.state == DecisionState.DIVERGED

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "state": self.state.value,
            "step_id": self.step_id,
            "step_type": self.step_type,
            "attempt": self.attempt,
            "command": self.command[:200],
            "source": self.source,
            "policy_reason": self.policy_reason[:200],
            "prediction": self.prediction.to_dict(),
            "observation": self.observation.to_dict() if self.observation else None,
            "conclusions": [c[:160] for c in self.conclusions[:8]],
            "parent_id": self.parent_id,
            "edge": self.edge,
            "ts": self.ts,
        }


class DecisionLog:
    """The per-run DecisionGraph. Append-only nodes + typed parent edges.

    Linking is automatic where the structure implies it: a second attempt on
    the same step_id gets a RETRY_OF edge to the previous attempt without the
    caller doing bookkeeping.
    """

    def __init__(self, run_id: str):
        self.run_id = run_id
        self._nodes: list[Decision] = []
        self._last_by_step: dict[str, Decision] = {}
        self._last_failed_verify: Optional[Decision] = None
        self._seq = 0

    # ── Node creation ──────────────────────────────────────────────────────────

    def _new(self, kind: DecisionKind, **kw) -> Decision:
        self._seq += 1
        d = Decision(
            id=f"{self.run_id}_d{self._seq}", kind=kind, state=DecisionState.PROPOSED, **kw
        )
        self._nodes.append(d)
        return d

    def propose_step(
        self,
        step_id: str,
        step_type: str,
        command: str,
        success_criteria: list[str],
        attempt: int,
        source: str = "plan",
        recovery_pass: bool = False,
    ) -> Decision:
        """Register a step attempt about to run. Auto-links: RETRY_OF to the
        previous attempt on this step; RECOVERS to the failed final verify when
        this is a recovery-pass step; REPLACES when the command is a fix."""
        kind = DecisionKind.STEP
        if source == "executor_fix":
            kind = DecisionKind.FIX
        elif source == "tool_suggestion":
            kind = DecisionKind.TOOL_SUGGESTION
        d = self._new(
            kind,
            step_id=step_id,
            step_type=step_type,
            command=command[:200],
            attempt=attempt,
            source=source,
            prediction=Prediction(
                expects_success=True, success_criteria=list(success_criteria or [])
            ),
        )
        prev = self._last_by_step.get(step_id)
        if prev is not None:
            d.parent_id = prev.id
            d.edge = (
                EdgeKind.REPLACES
                if kind in (DecisionKind.FIX, DecisionKind.TOOL_SUGGESTION)
                else EdgeKind.RETRY_OF
            ).value
        elif recovery_pass and self._last_failed_verify is not None:
            d.parent_id = self._last_failed_verify.id
            d.edge = EdgeKind.RECOVERS.value
        self._last_by_step[step_id] = d
        return d

    def propose_control(
        self,
        kind: DecisionKind,
        command: str = "",
        success_criteria: list[str] | None = None,
        source: str = "supervisor",
    ) -> Decision:
        """Plan / replan / final-verify decisions (supervisor-level)."""
        return self._new(
            kind,
            command=command[:200],
            source=source,
            prediction=Prediction(success_criteria=list(success_criteria or [])),
        )

    # ── FSM transitions ────────────────────────────────────────────────────────

    def block(self, d: Decision, reason: str) -> None:
        d.state = DecisionState.BLOCKED
        d.policy_reason = reason[:200]

    def close(
        self,
        d: Decision,
        *,
        run_ok: bool,
        achieved: bool,
        reason: str = "",
        error_class: str = "",
        latency_s: float = 0.0,
        conclusions: list[str] | None = None,
    ) -> None:
        """Attach the observation and compare with the prediction (the
        Compare step): matches → CONFIRMED, contradicts → DIVERGED."""
        d.observation = Observation(
            run_ok=run_ok,
            achieved=achieved,
            reason=reason[:200],
            error_class=error_class,
            latency_s=latency_s,
        )
        d.conclusions = list(conclusions or [])
        d.state = (
            DecisionState.CONFIRMED
            if achieved == d.prediction.expects_success
            else DecisionState.DIVERGED
        )
        if d.kind == DecisionKind.FINAL_VERIFY and not achieved:
            self._last_failed_verify = d

    # ── Queries / projections ──────────────────────────────────────────────────

    @property
    def nodes(self) -> list[Decision]:
        return list(self._nodes)

    def retry_chain(self, step_id: str) -> list[Decision]:
        """All attempts on a step, oldest first (walks parent edges)."""
        chain: list[Decision] = []
        cur = self._last_by_step.get(step_id)
        by_id = {d.id: d for d in self._nodes}
        while cur is not None:
            chain.append(cur)
            cur = by_id.get(cur.parent_id) if cur.parent_id else None
        return list(reversed(chain))

    def stats(self) -> dict:
        """Deterministic run-level decision metrics (Decision Quality KPIs)."""
        by_state: dict[str, int] = {}
        diverged_by_error: dict[str, int] = {}
        for d in self._nodes:
            by_state[d.state.value] = by_state.get(d.state.value, 0) + 1
            if d.diverged and d.observation is not None:
                key = d.observation.error_class or "UNKNOWN"
                diverged_by_error[key] = diverged_by_error.get(key, 0) + 1
        n = len(self._nodes)
        confirmed = by_state.get("confirmed", 0)
        closed = confirmed + by_state.get("diverged", 0)
        return {
            "n_decisions": n,
            "by_state": by_state,
            "first_shot_accuracy": round(confirmed / closed, 4) if closed else 0.0,
            "blocked_by_policy": by_state.get("blocked", 0),
            "diverged_by_error_class": diverged_by_error,
        }

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "stats": self.stats(),
            "nodes": [d.to_dict() for d in self._nodes],
        }
