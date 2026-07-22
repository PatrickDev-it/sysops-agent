"""
Core state model for the terminal agent.

Design invariant (from the platform rebuild directive):
    The filesystem is NOT the agent's memory.
    A single SystemState object flows through the pipeline:
        GOAL → OBSERVE → CAPABILITY → PLAN → EXECUTE → STATE UPDATE → VERIFY → RECOVER

Everything the agent learns — what OS it is on, which tools exist, what a
discovery step found — lives here, in memory, with explicit contracts. No
module re-derives the environment by guessing or by reading the disk twice.

This module is platform-neutral. It probes the live system through portable
APIs (platform, os, shutil) and never hard-codes framework or tool names.
"""

from __future__ import annotations

import os
import platform
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .tools import predicates

# The prose-matching patterns that used to live here are gone: success criteria are typed
# predicate objects, evaluated by their single owner, `tools.predicates`.


# ── Capability kinds ──────────────────────────────────────────────────────────
# A capability is "a thing the system can do", discovered by probing — not a
# framework name. We classify only by role, never by brand.

CMD = "command"
PACKAGE_MANAGER = "package_manager"
RUNTIME = "runtime"
SERVICE = "service"


@dataclass
class Capability:
    """One probed capability of the host system."""

    name: str
    available: bool
    path: str = ""
    version: str = ""
    kind: str = CMD
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Environment:
    """The execution environment, established once by probing the live host."""

    os_name: str = ""  # "Windows", "Linux", "Darwin"
    os_version: str = ""
    shell: str = ""  # "powershell", "bash"
    cwd: str = ""
    user: str = ""
    home: str = ""
    path_sep: str = os.pathsep

    @classmethod
    def probe(cls, cwd: str | Path) -> "Environment":
        sysname = platform.system()  # Windows / Linux / Darwin
        if sysname == "Windows":
            shell = "powershell"
        else:
            shell = os.environ.get("SHELL", "/bin/sh").rsplit("/", 1)[-1] or "bash"
        try:
            user = os.getlogin()
        except Exception:
            user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
        return cls(
            os_name=sysname,
            os_version=platform.version(),
            shell=shell,
            cwd=str(cwd),
            user=user,
            home=str(Path.home()),
        )

    def summary(self) -> str:
        return (
            f"OS: {self.os_name} {self.os_version}\n"
            f"SHELL: {self.shell}\n"
            f"CWD: {self.cwd}\n"
            f"USER: {self.user}\n"
            f"HOME: {self.home}"
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Fact:
    """A piece of information discovered during execution."""

    key: str
    value: str
    source: str = ""  # which step / command produced it
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


# Entity lifecycle + world identity live in world.py (single owner).
# Re-exported here so existing `from .state import EntityKind, EntityState`
# call sites keep working.
from .reasoning import BeliefKey, EvidenceKind, Predicate  # noqa: E402
from .world import EntityKind, EntityState, WorldGraph, WorldNode, norm_alias  # noqa: E402


@dataclass
class BehaviorSpec:
    """
    A verifiable runtime behavior — not 'file exists' but 'system can do X'.
    Discovered from workspace manifests, not from framework knowledge.
    """

    name: str
    command: str  # lightweight smoke-test command (syntax check, dry-run, --help)
    expected_signal: str = ""  # substring to look for in stdout; "" means exit 0 is enough
    timeout_s: float = 15.0
    discovery_method: str = ""  # how the command was found (for debugging)


@dataclass
class BehaviorResult:
    """The outcome of executing a BehaviorSpec smoke test."""

    spec: BehaviorSpec
    exit_code: int
    stdout: str
    stderr: str
    satisfied: bool
    reason: str  # human-readable verdict

    def to_dict(self) -> dict:
        return {
            "name": self.spec.name,
            "command": self.spec.command,
            "exit_code": self.exit_code,
            "satisfied": self.satisfied,
            "reason": self.reason,
        }


@dataclass
class GoalDistance:
    """
    Measures how far the current system state is from the desired operational state.

    Every action should reduce this distance.
    Zero distance = the system has reached its intended operational state.

    Three tiers (all must be zero for mission success):
      artifacts_gap  — named artifacts from criteria that don't exist yet
      capabilities_gap — required tools not confirmed available
      behaviors_gap  — smoke tests that fail (runtime not operational)
    """

    artifacts_gap: int = 0
    capabilities_gap: int = 0
    behaviors_gap: int = 0

    @property
    def total(self) -> int:
        return self.artifacts_gap + self.capabilities_gap + self.behaviors_gap

    def is_zero(self) -> bool:
        return self.total == 0

    def trend(self, previous: "GoalDistance") -> str:
        if self.total < previous.total:
            return "improving"
        if self.total > previous.total:
            return "degrading"
        return "stagnating"

    def summary(self) -> str:
        if self.is_zero():
            return "distance=0 (operational state reached)"
        parts = []
        if self.artifacts_gap:
            parts.append(f"{self.artifacts_gap} artifact(s)")
        if self.capabilities_gap:
            parts.append(f"{self.capabilities_gap} capability/ies")
        if self.behaviors_gap:
            parts.append(f"{self.behaviors_gap} behavior(s)")
        return "gap: " + " + ".join(parts)


@dataclass
class DesiredState:
    """
    Three-tier operational state model.

    Tier 1 — STRUCTURAL:   required artifacts present (deterministic file check)
    Tier 2 — CAPABILITY:   required tools confirmed available (capability model)
    Tier 3 — BEHAVIORAL:   smoke tests pass (system is actually operational)

    A task is not complete until all three tiers are satisfied.
    "Files written" satisfies tier 1. "Runtime can execute it" satisfies tier 3.
    The gap between tier 1 and tier 3 is `wrong_completion_assumption`.
    """

    # Typed predicate objects (`tools.predicates.SCHEMA`), never prose.
    success_criteria: list[dict] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    required_behaviors: list[BehaviorSpec] = field(default_factory=list)

    # ── Tier 1: structural ────────────────────────────────────────────────────

    def artifacts_satisfied(self, workspace: Path) -> tuple[bool, list[str]]:
        """Evaluate the goal's success predicates against the filesystem.

        `success_criteria` holds predicate OBJECTS (see `tools.predicates`), never prose.
        This method used to run a private regex dialect over natural language — a FOURTH
        vocabulary, alongside the prompt's, `_artifact_check`'s and `success_checker`'s —
        and when neither of its two patterns matched a criterion it returned "satisfied"
        with an empty `missing` list. Vacuously true. The caller then asked the LLM whether
        the goal was already done; shown criteria it could not evaluate, the model said yes,
        and a run was reported COMPLETE against an empty workspace.

        A machine-checkable question is never asked of a model.
        """
        ok, reason = predicates.evaluate(self.success_criteria, workspace)
        return ok, ([] if ok else [r.strip() for r in reason.split(";") if r.strip()])

    # ── Tier 2: capability ────────────────────────────────────────────────────

    def capabilities_satisfied(self, sysstate: "SystemState") -> tuple[bool, list[str]]:
        """
        Check that all required tools are available in the capability model.
        Tools that have never been probed are NOT counted as unavailable.
        """
        unavailable = [t for t in self.required_capabilities if sysstate.is_available(t) is False]
        return len(unavailable) == 0, unavailable

    # ── Combined distance metric ──────────────────────────────────────────────

    def distance(self, workspace: Path, sysstate: "SystemState") -> GoalDistance:
        """
        Compute the current distance to the desired operational state.
        Behaviors gap is set to len(required_behaviors) when behaviors haven't
        been verified yet — the behavior_verifier sets it to 0 when it confirms.
        """
        _, missing_arts = self.artifacts_satisfied(workspace)
        _, missing_caps = self.capabilities_satisfied(sysstate)
        return GoalDistance(
            artifacts_gap=len(missing_arts),
            capabilities_gap=len(missing_caps),
            behaviors_gap=len(self.required_behaviors),
        )

    # ── Prompt projection ─────────────────────────────────────────────────────

    def as_prompt(self) -> str:
        if not self.success_criteria:
            return ""
        return "\n".join(f"- {c}" for c in self.success_criteria)

    def is_empty(self) -> bool:
        return not self.success_criteria and not self.required_behaviors


@dataclass
class ActionResult:
    """
    The contract every action returns. Success is never inferred from
    'a file exists' — it is reported explicitly by the executor.
    """

    command: str
    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration: float = 0.0
    produced_facts: list[Fact] = field(default_factory=list)
    side_effects: list[str] = field(default_factory=list)

    @property
    def output(self) -> str:
        """Combined human-readable output."""
        parts = [p for p in (self.stdout, self.stderr) if p and p.strip()]
        return "\n".join(parts).strip()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["produced_facts"] = [f.to_dict() for f in self.produced_facts]
        return d


# "tool absent" signal — single owner is error_classifier (one invariant, one
# owner). This wrapper is kept only for the existing call sites.
def looks_like_missing_tool(text: str, command: str = "") -> bool:
    from .error_classifier import is_missing_tool_signal

    return is_missing_tool_signal(text, command)


class SystemState:
    """
    The single source of truth for one task run.

    Holds:
      - environment: where we are running
      - capabilities: what tools the host has (probed, cached)
      - facts: what we have discovered (in-memory, not on disk)
      - history: every ActionResult, in order
    """

    def __init__(self, cwd: str | Path):
        self.environment = Environment.probe(cwd)
        self.capabilities: dict[str, Capability] = {}
        self.facts: dict[str, Fact] = {}
        self.world = WorldGraph()  # single owner of world identity (world.py)
        self.history: list[ActionResult] = []
        self.desired_state: DesiredState = DesiredState()
        # UTC and unique. `f"run_{int(time.time())}"` had one-second resolution, so two runs
        # started in the same second SHARED an id — and the id keys the telemetry filename
        # (write_text, an overwrite), the trace file, every `decisions.id`, and the run_id
        # column on four SQLite tables. Back-to-back runs are the normal case for a benchmark
        # harness or a CI loop, so this was reachable, silent, and destroyed the earlier run's
        # audit record. The timestamp stays first so the ids sort chronologically.
        self.run_id = (
            f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
        )
        # DecisionGraph: every runtime choice as a typed node (decisions.py)
        from .decisions import DecisionLog

        self.decisions = DecisionLog(self.run_id)
        self._last_distance: Optional[GoalDistance] = None
        self._prev_distance: Optional[GoalDistance] = None
        self.reasoning: Optional[Any] = None  # ReasoningContext, set by init_reasoning()

    def init_reasoning(self, objective: str) -> Any:
        """Create and attach a ReasoningContext for this run. The reasoning
        layer receives the world graph so policy checks and fact extraction
        read/write ONE identity store instead of parallel string keys."""
        from .reasoning import ReasoningContext

        self.reasoning = ReasoningContext(
            objective=objective,
            run_id=self.run_id,
            world=self.world,
        )
        return self.reasoning

    # ── Capability model (FASE 3: discovery-first) ────────────────────────────

    def capability(self, tool: str) -> Optional[Capability]:
        return self.capabilities.get(_norm_tool(tool))

    def is_available(self, tool: str) -> Optional[bool]:
        """Returns True/False if known, None if never probed."""
        cap = self.capability(tool)
        return cap.available if cap else None

    def probe_capability(self, tool: str, kind: str = CMD) -> Capability:
        """
        Discovery-first: actively probe whether a tool exists on the host,
        using the portable resolver (shutil.which). Caches the result.
        """
        key = _norm_tool(tool)
        if key in self.capabilities:
            return self.capabilities[key]
        path = shutil.which(tool) or shutil.which(key) or ""
        cap = Capability(name=key, available=bool(path), path=path, kind=kind)
        self.capabilities[key] = cap
        return cap

    def observe_capability(self, command: str, exit_code: int, output: str) -> None:
        """
        Passive learning: update the capability model from a command that
        already ran. Exit 0 → available. 'not recognized' → unavailable.
        Non-zero without a missing-tool signal → tool exists but the call failed.
        """
        tool = _base_command(command)
        if not tool:
            return
        key = _norm_tool(tool)
        if key in self.capabilities and self.capabilities[key].available:
            return  # positive knowledge is sticky
        if exit_code == 0:
            self.capabilities[key] = Capability(name=key, available=True)
        elif looks_like_missing_tool(output, command):
            self.capabilities[key] = Capability(
                name=key, available=False, note="not found on this host"
            )
        else:
            # ran but failed for another reason → it exists
            self.capabilities[key] = Capability(
                name=key, available=True, note="present (call failed)"
            )

    def available_tools(self) -> list[str]:
        return [c.name for c in self.capabilities.values() if c.available]

    def unavailable_tools(self) -> list[str]:
        return [c.name for c in self.capabilities.values() if not c.available]

    # ── Facts model (in-memory discovery memory) ──────────────────────────────

    def find_available(self, candidates: list[str]) -> str:
        """Return the first tool from the list that is available (probing if needed)."""
        for tool in candidates:
            known = self.is_available(tool)
            if known is True:
                return tool
            if known is None:
                path = shutil.which(tool)
                if path:
                    self.capabilities[_norm_tool(tool)] = Capability(
                        name=_norm_tool(tool), available=True, path=path
                    )
                    return tool
        return ""

    def set_desired_state(
        self,
        success_criteria: list[str],
        required_capabilities: list[str] | None = None,
        required_behaviors: list[BehaviorSpec] | None = None,
    ) -> None:
        """Store the plan's desired operational state."""
        self.desired_state = DesiredState(
            success_criteria=list(success_criteria),
            required_capabilities=list(required_capabilities or []),
            required_behaviors=list(required_behaviors or []),
        )

    def update_distance(self, workspace: Path) -> GoalDistance:
        """Recompute goal distance and track trend across steps."""
        self._prev_distance = self._last_distance
        self._last_distance = self.desired_state.distance(workspace, self)
        return self._last_distance

    def distance_trend(self) -> str:
        """'improving' / 'stagnating' / 'degrading' / 'unknown'."""
        if self._last_distance is None or self._prev_distance is None:
            return "unknown"
        return self._last_distance.trend(self._prev_distance)

    @property
    def current_distance(self) -> Optional[GoalDistance]:
        return self._last_distance

    # ── World model (delegates to WorldGraph — the single identity owner) ─────

    def register_entity(
        self,
        path: str,
        kind: EntityKind,
        state: EntityState = EntityState.DISCOVERED,
        exists: bool = True,
        metadata: dict | None = None,
    ) -> WorldNode:
        """Register or merge a world node. Positive knowledge (INSTALLED/VERIFIED/
        DIRTY) is sticky against plain re-discovery (enforced by WorldGraph)."""
        provenance = ""
        if metadata:
            provenance = "; ".join(f"{k}={v}" for k, v in metadata.items())[:120]
        return self.world.ensure(kind, path=path, state=state, provenance=provenance)

    def transition_entity(self, path: str, new_state: EntityState) -> None:
        """Transition a node's lifecycle state. The graph cascade propagates
        absence over PROVIDES edges; every cascaded absence also refutes the
        matching existence belief so world and belief layers cannot diverge."""
        transitions = self.world.set_state(path, new_state)
        if self.reasoning is None:
            return
        for tr in transitions:
            if tr.new in (EntityState.DELETED, EntityState.MISSING):
                node = self.world.node(tr.node_id)
                evidence = f"world graph: {tr.node_id} → {tr.new.value}" + (
                    f" (cascade from {tr.cause})" if tr.cause else ""
                )
                for alias in node.aliases if node else []:
                    # score=0.0 is the explicit counter-verification channel — a graph
                    # transition is observed ground truth, so it may overturn PROVEN
                    # (refute() is the heuristic channel and deliberately cannot).
                    #
                    # This used to write BOTH the dash and underscore spellings, because
                    # belief keys were unnormalised and the graph's were not. That hack was
                    # the visible seam between two identity models; with one canonicaliser
                    # there is a single key to write.
                    self.reasoning.observe_belief(
                        BeliefKey.of(alias, Predicate.EXISTS),
                        holds=False,
                        kind=EvidenceKind.PROBE_DIRECT,
                        detail=evidence,
                    )

    def get_entity(self, path: str) -> Optional[WorldNode]:
        return self.world.resolve(path)

    def observe_executable(self, name: str, path: str, provenance: str = "") -> WorldNode:
        """Ingest a located executable: one graph node + the canonical facts
        that later steps resolve $VARs from."""
        node = self.world.observe_executable(name, path, provenance=provenance)
        self.add_fact("discovered_path", path, source=provenance or f"locate:{name}")
        if name:
            self.add_fact(f"tool_path:{name}", path, source="locate")
        return node

    def assert_safe_overwrite(self, path: str) -> tuple[bool, str]:
        """Invariant 3 (no overwrite of executables). Single implementation:
        WorldGraph.write_block_reason — the policy guard uses the same one."""
        reason = self.world.write_block_reason(path)
        return (reason == "", reason)

    def add_fact(self, key: str, value: str, source: str = "") -> None:
        if not value or not value.strip():
            return
        self.facts[key] = Fact(key=key, value=value.strip(), source=source)

    def add_discovery(self, objective: str, output: str) -> None:
        """Record the output of a discovery step keyed by its objective."""
        self.add_fact(f"discovery::{objective[:60]}", output, source=objective)

    def facts_summary(self, limit: int = 8) -> str:
        if not self.facts:
            return "(no facts discovered yet)"
        items = list(self.facts.values())[-limit:]
        return "\n".join(f"- {f.key}: {f.value[:240]}" for f in items)

    # ── History ───────────────────────────────────────────────────────────────

    def record(self, result: ActionResult) -> None:
        self.history.append(result)
        self.observe_capability(result.command, result.exit_code, result.output)
        for fact in result.produced_facts:
            self.facts[fact.key] = fact

    def recent_actions(self, n: int = 3) -> list[ActionResult]:
        return self.history[-n:]

    # ── Prompt projections ────────────────────────────────────────────────────

    def capabilities_for_prompt(self) -> str:
        avail = self.available_tools()
        unavail = self.unavailable_tools()
        lines = []
        if avail:
            lines.append(f"AVAILABLE_TOOLS: {', '.join(sorted(avail))}")
        if unavail:
            lines.append(f"UNAVAILABLE_TOOLS: {', '.join(sorted(unavail))}")
        if not lines:
            return "AVAILABLE_TOOLS: (none probed yet)"
        return "\n".join(lines)

    def environment_for_prompt(self) -> str:
        return self.environment.summary()

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "environment": self.environment.to_dict(),
            "capabilities": {k: v.to_dict() for k, v in self.capabilities.items()},
            "facts": {k: v.to_dict() for k, v in self.facts.items()},
            "world": self.world.to_dict(),
            "history": [r.to_dict() for r in self.history],
        }


# ── Helpers ───────────────────────────────────────────────────────────────────


def _norm_tool(name: str) -> str:
    """Delegates to the world graph's canonicaliser — one owner of "same thing, same name".

    This used to fold case and strip `.exe` but NOT fold dashes, so `capabilities` disagreed
    with the world graph about whether `yt-dlp` and `yt_dlp` were the same tool. Three
    normalisers for one notion of identity is two too many.
    """
    return norm_alias(name)


def _base_command(command: str) -> str:
    """Extract the root command name from a full command string."""
    if not command or "|" in command:
        return ""
    tokens = command.strip().split()
    if not tokens:
        return ""
    token = tokens[0]
    # Skip shell call operators
    if token in ("&", ".", "$") and len(tokens) > 1:
        token = tokens[1]
    token = _norm_tool(token)
    if token in (
        "",
        "if",
        "for",
        "while",
        "echo",
        "$",
        "@",
        "get-content",
        "set-content",
        "new-item",
        "write-output",
        "select-object",
    ):
        return ""
    return token
