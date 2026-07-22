"""
Reasoning system — six in-RAM layers, one instance per run.

Layers (in execution order):
  WorkingMemory    short-term context: constraints, failures, blocked actions   TTL=run
  BeliefSystem     confidence-scored propositions about the world               TTL=run
  SemanticMemory   extracted typed facts (not raw logs)                         TTL=run + SQLite
  InferenceEngine  forward-chain: step result → what becomes impossible         TTL=run
  DeductionEngine  fact + belief → new derived conclusions                      TTL=run
  AttentionManager token-budget ranked context for supervisor prompt            per-call
  ExecutionPolicy  pre-execute gate: should this command run at all?            per-step

Public API (consumed via sysstate.reasoning):

    pre_execute_check(command, step_id, step_type) → (allow: bool, reason: str)
    post_step_update(step_id, command, success, error_class, output, step_type) → list[str]
    get_prompt_context() → str
    record_failed_assumption(assumption, evidence, error_class, invalid_until)
    add_semantic_fact(key, value, confidence, source)
    observe_belief(key: BeliefKey, holds: bool, kind: EvidenceKind, detail: str)
    query_belief(key: BeliefKey) → Optional[Belief]

Design invariants:
  - A belief is identified by a canonical world subject + a typed predicate, never a string
  - Belief state is DERIVED from the strongest evidence; no caller asserts a confidence
  - Stronger evidence wins, and equal-strength evidence is superseded by the newer observation
  - PROVEN beliefs drive execution; LIKELY beliefs drive planning; REFUTED blocks retry
  - Working memory never exceeds TOKEN_BUDGET chars in prompt projection
  - Semantic facts replace raw logs: "tool_scope:pip=venv", not "pip install output..."
  - Every inference rule concludes what is IMPOSSIBLE, not just what happened
"""

from __future__ import annotations

import hashlib
import itertools
import re as _re_global
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Callable, Optional

from .error_classifier import ErrorClass
from .world import norm_alias

if TYPE_CHECKING:
    pass


# ── Belief confidence levels ──────────────────────────────────────────────────


class Predicate(str, Enum):
    """What can be believed about a thing. A closed vocabulary, so a typo is a NameError.

    Belief keys used to be free-form f-strings. Two consequences: the writer and the reader
    could disagree about a spelling (they did — see BeliefKey), and nothing constrained the
    predicate either, so a belief about `:instaled` would simply never be read by anything.
    """

    EXISTS = "exists"
    AVAILABLE_GLOBALLY = "available_globally"
    INSTALLED = "installed"
    SCOPE_IS_VENV = "scope_is_venv"
    VERSION_KNOWN = "version_known"


@dataclass(frozen=True)
class BeliefKey:
    """The identity of a belief: a canonical world subject plus a typed predicate.

    Frozen and constructed only through `of()`, which canonicalises the subject through
    `world.norm_alias` — the same function the world graph uses for node identity. A belief
    can no longer be about a string; it is about the thing the graph would call that string.

    This is what makes the identity split unrepresentable rather than merely fixed. Previously
    `f"{tool}:exists"` was written at seven call sites, one of which lower-cased and folded
    dashes while another did not, so `pip install yt-dlp` recorded success under `yt_dlp` while
    the execution veto read `yt-dlp` and stayed REFUTED forever.
    """

    subject: str
    predicate: Predicate

    @classmethod
    def of(cls, subject: str, predicate: Predicate) -> "BeliefKey":
        return cls(norm_alias(subject), predicate)

    def __str__(self) -> str:
        return f"{self.subject}:{self.predicate.value}"


class EvidenceKind(int, Enum):
    """How a belief came to be held, ORDERED by how much it should be trusted.

    Truth is derived from this, not asserted by the caller. The old model took a float `score`
    from whoever happened to be calling, which meant a regex sweeping arbitrary stdout could
    mint a belief at 1.0 — indistinguishable from a direct probe — and, because PROVEN was
    sticky and `refute()` could not overturn it, that fabricated belief was immortal for the
    run.

    With evidence ranked, "PROVEN is unfalsifiable" is replaced by "stronger evidence wins",
    which is decidable, testable, and does not need a special counter-verification channel.

    MUTATION is not simply "the strongest observation". It is a different KIND of statement,
    and the distinction is the whole domain of this agent. `which yt-dlp` reporting nothing at
    t0 and `pip install yt-dlp` succeeding at t1 are BOTH true: they describe different worlds.
    Ranking them against each other is a category error — which is what a purely strength-ordered
    model does, and why a stale probe kept vetoing execution after the install that fixed it.
    An action that changes the world invalidates every observation of the world before it.
    """

    OUTPUT_HEURISTIC = 10  # a pattern matched somewhere in a command's output
    EXIT_CODE = 20  # the command that would use it succeeded or failed
    PACKAGE_MANAGER = 30  # a package manager reported the state directly
    PROBE_DIRECT = 40  # locate / which / a filesystem check on the thing itself
    MUTATION = 50  # an ACTION that changed the world (see below)


@dataclass(frozen=True)
class Evidence:
    kind: EvidenceKind
    detail: str
    seq: int = 0  # observation order within the run — see below
    ts: float = field(default_factory=time.time)

    def __str__(self) -> str:
        return f"{self.kind.name}: {self.detail}"


class BeliefState(str, Enum):
    UNKNOWN = "unknown"  # no evidence either way
    POSSIBLE = "possible"  # weak support, no contradiction
    LIKELY = "likely"  # solid support, no contradiction
    PROVEN = "proven"  # direct evidence that it holds
    REFUTED = "refuted"  # evidence that it does not hold, and nothing stronger against it

    @classmethod
    def from_evidence(cls, support: "Evidence | None", against: "Evidence | None") -> "BeliefState":
        """The single rule: the strongest evidence decides, and ties go to the newer one.

        No stickiness, no override channel, no special case for who is allowed to contradict
        whom. A direct probe beats a package-manager report beats an exit code beats a regex,
        and a later observation of equal strength supersedes an earlier one — which is exactly
        how a tool that was absent and has now been installed becomes present.
        """
        if support is None and against is None:
            return cls.UNKNOWN
        # Ordered by SEQUENCE, not by timestamp. `time.time()` has ~15 ms resolution on
        # Windows, so two observations in the same tick carry identical timestamps and
        # "which came later" becomes a coin flip — the exact case that matters here, because
        # a failed probe and the install that fixes it can land in the same millisecond.
        if against is not None and (
            support is None
            or against.kind > support.kind
            or (against.kind == support.kind and against.seq > support.seq)
        ):
            return cls.REFUTED
        assert support is not None
        if support.kind >= EvidenceKind.PACKAGE_MANAGER:
            return cls.PROVEN
        if support.kind == EvidenceKind.EXIT_CODE:
            return cls.LIKELY
        return cls.POSSIBLE


# ── Belief identity — one canonicaliser, shared with the world graph ─────────
# Belief keys used to be built by seven call sites as bare f-strings, with NO normalization,
# while `world.norm_alias` folded dashes to underscores (pip reports `yt-dlp` as `yt_dlp`).
# Inside a SINGLE function, `_extract_facts_from_success` wrote both spellings:
#
#     :722  pkg_from_cmd = match.group(1).lower().replace("-", "_")   -> "yt_dlp"
#     :725  assert_belief(f"{pkg_from_cmd}:exists", 1.0,
#                         evidence="pip install succeeded - clearing any prior REFUTED")
#     :931  tool = _real_tool(command)                                -> "yt-dlp"
#     :933  if beliefs.is_refuted(f"{tool}:exists"):                  -> reads the OTHER key
#
# So the agent's primary workflow deadlocked: DISCOVERY fails -> `yt-dlp:exists` REFUTED ->
# recovery runs `pip install yt-dlp` -> it SUCCEEDS -> `yt_dlp:exists` is set PROVEN ->
# `yt-dlp:exists` is still REFUTED -> every subsequent MODIFY step is vetoed and the plan
# halts. The comment at line 726 described a clearing that the code could not perform, and
# `test_world.py` asserted on the writer's spelling rather than the reader's, so it passed.
#
# A belief is about a THING, and this tree already has one canonical name for a thing.
def _bkey(subject: str, predicate: str) -> BeliefKey:
    """Shorthand used throughout this module. The predicate string is resolved against the
    Predicate enum, so a typo is a ValueError here rather than a belief nobody ever reads."""
    return BeliefKey.of(subject, Predicate(predicate))


@dataclass
class Belief:
    key: BeliefKey
    state: BeliefState
    support: Optional[Evidence] = None  # strongest evidence FOR
    against: Optional[Evidence] = None  # strongest evidence AGAINST
    history: list[str] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)

    @property
    def proposition(self) -> str:
        return str(self.key)

    @property
    def evidence(self) -> list[str]:
        return list(self.history)

    def summary(self) -> str:
        held = self.support or self.against
        return f"[{self.state.value.upper():8}] {self.key} ({held})"


# ── Semantic fact ─────────────────────────────────────────────────────────────


@dataclass
class SemanticFact:
    key: str  # e.g. "tool_scope:yt-dlp", "tool_path:python", "tool_version:git"
    value: str  # e.g. "venv", "C:/Python312/python.exe", "2.43.0"
    confidence: float = 1.0
    source: str = ""
    ts: float = field(default_factory=time.time)


# ── Deduction schema ──────────────────────────────────────────────────────────


@dataclass
class Deduction:
    id: str
    premises: list[str]  # fact keys or belief propositions that triggered this
    conclusion: str
    confidence: float
    invalidates: list[str]  # action tokens to block in WorkingMemory
    enables: list[str]  # action tokens this deduction unlocks


# ── Failed assumption ─────────────────────────────────────────────────────────


@dataclass
class FailedAssumption:
    assumption: str  # what was assumed true
    evidence: str  # what was observed that contradicted it
    error_class: str  # ErrorClass value
    invalid_until: str  # condition that would lift this constraint
    ts: float = field(default_factory=time.time)


# ═════════════════════════════════════════════════════════════════════════════
# LAYER 1 — WORKING MEMORY
# ═════════════════════════════════════════════════════════════════════════════


class WorkingMemory:
    """
    Short-term reasoning context for one run.
    Strict capacity limits. Projected to prompt within TOKEN_BUDGET.
    """

    TOKEN_BUDGET = 3200  # characters (~800 tokens at 4 char/tok)
    MAX_FAILURES = 24
    MAX_SUCCESSES = 24
    MAX_CONSTRAINTS = 12
    MAX_BLOCKED = 32
    MAX_QUESTIONS = 6

    def __init__(self, objective: str):
        self.objective = objective
        self.current_step: int = 0
        self.active_constraints: list[str] = []
        # Each failure: {step_id, command, reason, error_class, attempt}
        self.known_failures: list[dict] = []
        self.known_successes: list[str] = []
        self.open_questions: list[str] = []
        # action_token → reason_string
        self.blocked_actions: dict[str, str] = {}

    # ── Mutation API ──────────────────────────────────────────────────────────

    def record_failure(
        self, step_id: str, command: str, reason: str, error_class: str, attempt: int = 0
    ) -> None:
        entry = {
            "step_id": step_id,
            "command": command[:100],
            "reason": reason[:120],
            "error_class": error_class,
            "attempt": attempt,
        }
        self.known_failures.append(entry)
        if len(self.known_failures) > self.MAX_FAILURES:
            self.known_failures = self.known_failures[-self.MAX_FAILURES :]

    def record_success(self, step_id: str) -> None:
        if step_id not in self.known_successes:
            self.known_successes.append(step_id)
        if len(self.known_successes) > self.MAX_SUCCESSES:
            self.known_successes = self.known_successes[-self.MAX_SUCCESSES :]

    def block_action(self, action_token: str, reason: str) -> None:
        self.blocked_actions[action_token] = reason
        if len(self.blocked_actions) > self.MAX_BLOCKED:
            # Evict oldest (dict preserves insertion order in Python 3.7+)
            oldest = next(iter(self.blocked_actions))
            del self.blocked_actions[oldest]

    def add_constraint(self, constraint: str) -> None:
        if constraint not in self.active_constraints:
            self.active_constraints.append(constraint)
        if len(self.active_constraints) > self.MAX_CONSTRAINTS:
            self.active_constraints = self.active_constraints[-self.MAX_CONSTRAINTS :]

    def is_blocked(self, action_token: str) -> tuple[bool, str]:
        reason = self.blocked_actions.get(action_token, "")
        return bool(reason), reason

    def last_failure_error_class(self) -> Optional[str]:
        return self.known_failures[-1]["error_class"] if self.known_failures else None

    def commands_tried(self) -> list[str]:
        return [f["command"] for f in self.known_failures]

    # ── Prompt projection ─────────────────────────────────────────────────────

    def to_prompt(self) -> str:
        lines = [
            f"OBJECTIVE: {self.objective[:120]}",
            f"REASONING_STEP: {self.current_step}",
        ]
        if self.active_constraints:
            lines.append("ACTIVE_CONSTRAINTS:")
            for c in self.active_constraints[-5:]:
                lines.append(f"  ⊢ {c}")
        if self.known_failures:
            lines.append("FAILURES_THIS_RUN:")
            for f in self.known_failures[-4:]:
                lines.append(
                    f"  ✗ step={f['step_id']} cmd={f['command'][:50]} err={f['error_class']}"
                )
        if self.blocked_actions:
            lines.append("BLOCKED_ACTIONS:")
            for tok, reason in list(self.blocked_actions.items())[-5:]:
                lines.append(f"  ⊘ {tok}: {reason[:60]}")
        text = "\n".join(lines)
        if len(text) > self.TOKEN_BUDGET:
            text = text[: self.TOKEN_BUDGET] + "\n…(truncated)"
        return text


# ═════════════════════════════════════════════════════════════════════════════
# LAYER 2 — BELIEF SYSTEM
# ═════════════════════════════════════════════════════════════════════════════


class BeliefSystem:
    """
    Confidence-scored world model. Invariants:
      - REFUTED is sticky (requires explicit score=1.0 override from a verified event)
      - PROVEN is sticky unless a contradicting observation refutes it
      - Only PROVEN beliefs may drive execution decisions
    """

    def __init__(self, world=None):
        self._beliefs: dict[BeliefKey, Belief] = {}
        self._seq = itertools.count()
        # The WorldGraph, when one exists. Every belief subject is registered there, so a
        # belief cannot be held about something the world model has never heard of: the two
        # layers share one population of things, not two that happen to use the same strings.
        self._world = world

    def subjects(self) -> set[str]:
        return {k.subject for k in self._beliefs}

    def observe(self, key: BeliefKey, *, holds: bool, kind: EvidenceKind, detail: str) -> Belief:
        """Record one observation. The state is DERIVED; no caller sets it.

        Replaces `assert_belief(proposition, score, evidence)`, where the caller chose a float
        and the system then applied stickiness rules to defend itself against callers choosing
        badly. Here a caller can only say WHAT it saw and HOW it saw it, and the ordering in
        `EvidenceKind` decides what that means. Weaker evidence never overwrites stronger; the
        observation is still recorded in `history`, so the disagreement is auditable.
        """
        ev = Evidence(kind=kind, detail=detail[:160], seq=next(self._seq))
        if self._world is not None:
            # Bind the subject to the world graph. `note_subject` is idempotent and creates
            # nothing but an identity, so a belief about a tool the agent has not located yet
            # is still expressible — it just cannot be about a name the world does not carry.
            self._world.note_subject(key.subject)
        existing = self._beliefs.get(key)
        support = existing.support if existing else None
        against = existing.against if existing else None

        if kind is EvidenceKind.MUTATION:
            # The world changed. Every observation taken before this one describes a state
            # that no longer exists, so it is discarded rather than competed with.
            support, against = (ev, None) if holds else (None, ev)
        elif holds:
            if support is None or kind >= support.kind:
                support = ev
        else:
            if against is None or kind >= against.kind:
                against = ev

        history = (existing.history if existing else []) + [f"{'+' if holds else '-'} {ev}"]
        belief = Belief(
            key=key,
            state=BeliefState.from_evidence(support, against),
            support=support,
            against=against,
            history=history[-8:],
            last_updated=time.time(),
        )
        self._beliefs[key] = belief
        return belief

    def get(self, key: BeliefKey) -> Optional[Belief]:
        return self._beliefs.get(key)

    def is_proven(self, key: BeliefKey) -> bool:
        b = self._beliefs.get(key)
        return b is not None and b.state == BeliefState.PROVEN

    def is_refuted(self, key: BeliefKey) -> bool:
        b = self._beliefs.get(key)
        return b is not None and b.state == BeliefState.REFUTED

    def all_beliefs(self) -> list[Belief]:
        return list(self._beliefs.values())

    def to_prompt(self, max_items: int = 10) -> str:
        all_b = sorted(
            self._beliefs.values(),
            key=lambda b: (
                b.state == BeliefState.REFUTED,
                b.state == BeliefState.PROVEN,
                b.last_updated,
            ),
            reverse=True,
        )[:max_items]
        if not all_b:
            return ""
        lines = ["WORLD_MODEL:"]
        for b in all_b:
            lines.append(f"  {b.summary()}")
        return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════
# LAYER 4 — INFERENCE RULES  (layer 3 = SemanticMemory, stored inline)
# ═════════════════════════════════════════════════════════════════════════════


def _cmd_hash(command: str) -> str:
    return hashlib.md5(command.encode()).hexdigest()[:8]


_SHELL_KEYWORDS = frozenset(
    {
        "if",
        "else",
        "for",
        "foreach",
        "while",
        "do",
        "switch",
        "try",
        "catch",
        "function",
        "return",
        "begin",
        "end",
        "process",
        "param",
        "&&",
        "||",
        ";",
        "&",
        "|",
    }
)

# Shell built-ins that navigate/modify session state but are never installable tools.
# When these appear first in a compound command (e.g. "cd $env:TEMP; yt-dlp --version"),
# they must be stripped so the real tool is extracted from the rest of the command.
_SHELL_BUILTINS = frozenset({"cd", "set", "pushd", "popd", "export", "source", "."})


def _real_tool(command: str) -> str:
    """Extract the actual tool/executable name from a compound command.

    Strips:
      - Leading $env:VAR=VALUE; prefix assignments (PowerShell)
      - Leading shell built-in prefixes like "cd <path>;" so that
        "cd $env:TEMP; yt-dlp --version" correctly returns "yt-dlp"

    Returns "unknown" for shell keywords/control-flow words that are not tools.
    """
    c = _re_global.sub(
        r"\$env:[A-Z_][A-Z0-9_]*\s*=\s*\S+\s*;?\s*", "", command, flags=_re_global.IGNORECASE
    ).strip()
    # Strip leading "builtin <arg>;" segments repeatedly until we reach the real tool
    for _ in range(5):  # guard against infinite loop on malformed input
        first = c.split()[0].rstrip(";") if c.strip() else ""
        if first.lower() not in _SHELL_BUILTINS:
            break
        # Drop everything up to and including the first ";" separator
        if ";" in c:
            c = c.split(";", 1)[1].strip()
        else:
            break
    first = c.split()[0] if c.strip() else "unknown"
    return "unknown" if first.lower() in _SHELL_KEYWORDS | _SHELL_BUILTINS else first


def _rule_syntax_blocks_unchanged_retry(
    wm: WorkingMemory, beliefs: BeliefSystem, facts: dict[str, SemanticFact]
) -> Optional[Deduction]:
    """COMMAND_SYNTAX error → block exact retry of same command."""
    for f in reversed(wm.known_failures):
        if f["error_class"] == "COMMAND_SYNTAX":
            cmd = f["command"]
            h = _cmd_hash(cmd)
            token = f"retry_exact:{h}"
            if token not in wm.blocked_actions:
                return Deduction(
                    id=f"syntax_no_retry:{h}",
                    premises=[f"failure:COMMAND_SYNTAX:{cmd[:40]}"],
                    conclusion=f"Command syntax is invalid — unchanged retry is forbidden: {cmd[:60]}",
                    confidence=1.0,
                    invalidates=[token],
                    enables=["correct_flags", "use_alternative_command"],
                )
    return None


def _rule_invalid_exe_blocks_write(
    wm: WorkingMemory, beliefs: BeliefSystem, facts: dict[str, SemanticFact]
) -> Optional[Deduction]:
    """INVALID_EXECUTABLE error → block write_file to that path, require delete first."""
    for f in reversed(wm.known_failures):
        if f["error_class"] == "INVALID_EXECUTABLE":
            cmd = f["command"]
            # Heuristic: first token of command is the corrupt binary path
            path_token = cmd.strip().split()[0] if cmd.strip() else "unknown"
            token = f"write_file:{path_token}"
            if token not in wm.blocked_actions:
                return Deduction(
                    id=f"corrupt_exe:{_cmd_hash(path_token)}",
                    premises=[f"failure:INVALID_EXECUTABLE:{path_token}"],
                    conclusion=(
                        f"{path_token} is corrupt — write_file is FORBIDDEN. "
                        "Delete first, then reinstall."
                    ),
                    confidence=1.0,
                    invalidates=[token, f"overwrite:{path_token}"],
                    enables=[f"delete:{path_token}", f"reinstall:{path_token}"],
                )
    return None


def _rule_discovery_fail_blocks_dependents(
    wm: WorkingMemory, beliefs: BeliefSystem, facts: dict[str, SemanticFact]
) -> Optional[Deduction]:
    """REFUTED tool:exists belief → block run/verify of that tool."""
    for b in beliefs.all_beliefs():
        if b.state == BeliefState.REFUTED and b.proposition.endswith(":exists"):
            tool = b.proposition[: -len(":exists")]
            token = f"run:{tool}"
            if token not in wm.blocked_actions:
                return Deduction(
                    id=f"missing_tool_blocks:{tool}",
                    premises=[b.proposition],
                    conclusion=f"{tool} is confirmed absent — run/verify steps are blocked until installed",
                    confidence=0.99,
                    invalidates=[f"run:{tool}", f"verify:{tool}", f"execute_with:{tool}"],
                    enables=[f"install:{tool}", f"discover_alternative:{tool}"],
                )
    return None


def _rule_scope_mismatch_requires_global(
    wm: WorkingMemory, beliefs: BeliefSystem, facts: dict[str, SemanticFact]
) -> Optional[Deduction]:
    """tool_scope=venv + goal requires global → must install globally."""
    for key, fact in facts.items():
        if key.startswith("tool_scope:") and fact.value == "venv":
            tool = key[len("tool_scope:") :]
            venv_prop = _bkey(tool, "scope_is_venv")
            if beliefs.is_proven(venv_prop):
                token = f"verify_global:{tool}"
                if token not in wm.blocked_actions:
                    return Deduction(
                        id=f"scope_blocks_global_verify:{tool}",
                        premises=[key, str(venv_prop)],
                        conclusion=(
                            f"{tool} is installed in venv scope — "
                            "global verify will fail, global install required"
                        ),
                        confidence=0.95,
                        invalidates=[token, f"run_global:{tool}"],
                        enables=[f"install_globally:{tool}"],
                    )
    return None


def _rule_install_fail_blocks_verify(
    wm: WorkingMemory, beliefs: BeliefSystem, facts: dict[str, SemanticFact]
) -> Optional[Deduction]:
    """PACKAGE_NOT_FOUND or NETWORK_ERROR → block verify_install for same target."""
    for f in reversed(wm.known_failures):
        if f["error_class"] in ("PACKAGE_NOT_FOUND", "NETWORK_ERROR"):
            # Extract package name heuristic: last non-flag word in command
            words = [w for w in f["command"].split() if not w.startswith("-")]
            target = words[-1] if words else "unknown"
            token = f"verify_install:{target}"
            if token not in wm.blocked_actions:
                return Deduction(
                    id=f"install_fail_blocks:{_cmd_hash(target)}",
                    premises=[f"failure:{f['error_class']}:{target}"],
                    conclusion=f"Install of {target} failed — verification premature until install succeeds",
                    confidence=0.90,
                    invalidates=[token],
                    enables=[f"retry_install:{target}", f"search_alternative:{target}"],
                )
    return None


def _rule_env_scope_mismatch_adds_constraint(
    wm: WorkingMemory, beliefs: BeliefSystem, facts: dict[str, SemanticFact]
) -> Optional[Deduction]:
    """ENV_SCOPE_MISMATCH → refute tool:available_globally, add global-install constraint."""
    for f in reversed(wm.known_failures):
        if f["error_class"] == "ENV_SCOPE_MISMATCH":
            cmd = f["command"]
            tool = cmd.strip().split()[0] if cmd.strip() else "unknown"
            prop = _bkey(tool, "available_globally")
            if not beliefs.is_refuted(prop):
                return Deduction(
                    id=f"scope_mismatch:{_cmd_hash(tool)}",
                    premises=[f"failure:ENV_SCOPE_MISMATCH:{tool}"],
                    conclusion=f"{tool} is not available globally — must install to system PATH",
                    confidence=0.92,
                    invalidates=[f"run_in_venv:{tool}"],
                    enables=[f"install_globally:{tool}", f"add_to_PATH:{tool}"],
                )
    return None


_DEDUCTION_RULES: list[Callable] = [
    _rule_syntax_blocks_unchanged_retry,
    _rule_invalid_exe_blocks_write,
    _rule_discovery_fail_blocks_dependents,
    _rule_scope_mismatch_requires_global,
    _rule_install_fail_blocks_verify,
    _rule_env_scope_mismatch_adds_constraint,
]


# ═════════════════════════════════════════════════════════════════════════════
# LAYER 4b — DEDUCTION ENGINE
# ═════════════════════════════════════════════════════════════════════════════


class DeductionEngine:
    """
    Applies all inference rules to the current working memory + beliefs + facts.
    New deductions are applied to working memory immediately.
    Dedup by id — each rule fires at most once per unique conclusion.
    """

    def __init__(self):
        self._applied_ids: set[str] = set()

    def derive(
        self,
        wm: WorkingMemory,
        beliefs: BeliefSystem,
        facts: dict[str, SemanticFact],
    ) -> list[Deduction]:
        new: list[Deduction] = []
        for rule_fn in _DEDUCTION_RULES:
            try:
                d = rule_fn(wm, beliefs, facts)
            except Exception:
                continue
            if d is None or d.id in self._applied_ids:
                continue
            self._applied_ids.add(d.id)
            for token in d.invalidates:
                wm.block_action(token, f"⟹ {d.conclusion[:80]}")
            new.append(d)
        return new


# ═════════════════════════════════════════════════════════════════════════════
# LAYER 5 — INFERENCE ENGINE  (post-step forward-chaining)
# ═════════════════════════════════════════════════════════════════════════════


class InferenceEngine:
    """
    Forward-chaining from step outcomes to world-model updates.
    Responsible for extracting semantic facts from raw output and
    updating the belief system based on what was observed.
    """

    def process_step_result(
        self,
        step_id: str,
        command: str,
        success: bool,
        error_class,  # ErrorClass | None
        output: str,
        step_type: str,
        wm: WorkingMemory,
        beliefs: BeliefSystem,
        facts: dict[str, SemanticFact],
        world=None,
    ) -> list[str]:
        """
        Returns a list of human-readable conclusions derived this step.
        Side-effects: updates wm, beliefs, facts, world graph.
        """
        conclusions: list[str] = []

        if success:
            wm.record_success(step_id)
            self._extract_facts_from_success(
                command, output, step_type, facts, beliefs, world=world
            )
        else:
            ec_value = error_class.value if error_class is not None else "UNKNOWN"
            wm.record_failure(
                step_id=step_id,
                command=command,
                reason=output[:120] if output else ec_value,
                error_class=ec_value,
            )

            c = self._infer_from_failure(
                command, output, error_class, step_type, wm, beliefs, facts
            )
            conclusions.extend(c)

        return conclusions

    def _infer_from_failure(
        self, command, output, error_class, step_type, wm, beliefs, facts
    ) -> list[str]:
        conclusions = []
        ec = error_class

        if ec == ErrorClass.COMMAND_SYNTAX:
            h = _cmd_hash(command)
            wm.block_action(f"retry_exact:{h}", "COMMAND_SYNTAX — must correct flags before retry")
            conclusions.append(f"IMPOSSIBLE: retry unchanged [{command[:50]}]")

        elif ec == ErrorClass.FILE_NOT_FOUND:
            # Distinguish a missing command from a command whose target path is absent.
            _out_lower = (output or "").lower()
            _is_tool_missing = (
                "is not recognized as the name of" in _out_lower
                or "command not found" in _out_lower
            )
            if _is_tool_missing:
                tool = _real_tool(command)
                # PowerShell Verb-Noun commands are built-ins, never installable tools.
                import re as _re_ps

                _is_ps_cmdlet = bool(_re_ps.match(r"^[A-Z][a-z]+-[A-Z][a-z]", tool))
                if not _is_ps_cmdlet:
                    beliefs.observe(
                        _bkey(tool, "available_globally"),
                        holds=False,
                        kind=EvidenceKind.EXIT_CODE,
                        detail=f"FILE_NOT_FOUND: {output[:80]}",
                    )
                    wm.add_constraint(
                        f"{tool} did not resolve by bare name — install it, or "
                        "invoke it via its ecosystem's local runner/qualified path"
                    )
                    conclusions.append(
                        f"REFUTED: {tool}:available_globally (not on PATH by bare name)"
                    )

        elif ec == ErrorClass.INVALID_EXECUTABLE:
            path_token = _real_tool(command)
            wm.block_action(
                f"write_file:{path_token}",
                "INVALID_EXECUTABLE — write_file forbidden; delete + reinstall only",
            )
            wm.add_constraint(f"delete {path_token} before reinstall")
            conclusions.append(f"IMPOSSIBLE: write_file to corrupt executable {path_token}")

        elif ec == ErrorClass.ENV_SCOPE_MISMATCH:
            # Use _real_tool to strip $env:VAR=value; prefixes before extraction
            tool = _real_tool(command)
            beliefs.observe(
                _bkey(tool, "available_globally"),
                holds=False,
                kind=EvidenceKind.EXIT_CODE,
                detail=f"ENV_SCOPE_MISMATCH: {output[:80]}",
            )
            wm.add_constraint(f"install {tool} to system PATH (global scope required)")
            conclusions.append(f"CONSTRAINT: {tool} must be globally installed")

        elif ec == ErrorClass.NETWORK_ERROR:
            wm.add_constraint("network unreachable — offline cache or mirror required")
            conclusions.append("CONSTRAINT: network unavailable")

        elif ec == ErrorClass.PERMISSION_DENIED:
            wm.add_constraint(f"permission denied for: {command[:60]}")
            conclusions.append("CONSTRAINT: elevate privileges or change path")

        if step_type == "DISCOVERY":
            # A DISCOVERY step refutes tool existence ONLY on a genuine
            # tool-absent signal (single owner: error_classifier). Empty or
            # filtered output (`Get-NetRoute | Where …`, `netstat | findstr DNS`)
            # is INCONCLUSIVE — the previous blanket refutation on any failure
            # falsely marked real tools absent and the policy guard then blocked
            # their reuse (measured: full-safe30-p013, 9 empty-refutes + 5 blocks).
            from .error_classifier import is_missing_tool_signal

            if is_missing_tool_signal(output, command):
                # fileops "locate|<tool>" form: the discovery TARGET is the pipe
                # argument, not the fileops verb.
                tool_candidate = _real_tool(command)
                if "|" in tool_candidate:
                    segs = [s.strip() for s in tool_candidate.split("|") if s.strip()]
                    tool_candidate = segs[-1].split()[0] if segs else "unknown"
                if tool_candidate and tool_candidate != "unknown":
                    # No "only refute if not already PROVEN" guard here any more. That was a
                    # second copy of the precedence rule, written when stickiness lived in the
                    # BeliefSystem; evidence ordering now decides, in one place. Record the
                    # observation and report what it actually produced — the previous version
                    # appended "REFUTED: ..." unconditionally, including on the path where the
                    # refutation had been refused, so the audit log asserted a transition the
                    # belief system had declined to make.
                    b = beliefs.observe(
                        _bkey(tool_candidate, "exists"),
                        holds=False,
                        kind=EvidenceKind.PROBE_DIRECT,
                        detail=f"DISCOVERY missing-tool signal: {output[:80]}",
                    )
                    conclusions.append(f"{b.state.value.upper()}: {b.key}")

        return conclusions

    def _extract_facts_from_success(
        self,
        command: str,
        output: str,
        step_type: str,
        facts: dict[str, SemanticFact],
        beliefs: BeliefSystem,
        world=None,
    ) -> None:
        """
        Parse successful step output into typed semantic propositions.
        Never stores raw logs — only extracts typed facts. The regexes here are
        the observation boundary (bytes → typed); downstream reasoning consumes
        the world graph and beliefs, never this raw text again.
        """
        import re as _re

        out_lower = (output or "").lower()

        # locate() output: "toolname -> /full/path"
        m = _re.search(r"([\w][\w.\-]+)\s+->\s+(\S+)", output or "")
        if m:
            tool, path = m.group(1).strip(), m.group(2).strip()
            # Normalize: strip trailing "\" or "/"
            path = path.rstrip("/\\")
            facts[f"tool_path:{tool}"] = SemanticFact(
                key=f"tool_path:{tool}", value=path, confidence=1.0, source=command[:80]
            )
            beliefs.observe(
                _bkey(tool, "exists"),
                holds=True,
                kind=EvidenceKind.PROBE_DIRECT,
                detail=f"located at {path}",
            )
            if world is not None:
                world.observe_executable(tool, path, provenance=command[:80])
            # If found on PATH (not deep in venv), mark as globally available
            venv_signals = (".venv", "venv", "site-packages")
            if not any(s in path.lower() for s in venv_signals):
                beliefs.observe(
                    _bkey(tool, "available_globally"),
                    holds=True,
                    kind=EvidenceKind.EXIT_CODE,
                    detail=f"path has no venv markers: {path}",
                )

        # pip install output — handles both "Successfully installed" and "Requirement already satisfied"
        _is_pip_install = "install" in command.lower() and (
            "successfully installed" in out_lower or "requirement already satisfied" in out_lower
        )
        if _is_pip_install:
            # Extract package name from command: pip install [flags] <pkg>
            pkg_cmd_match = _re.search(
                r"(?:pip|python\s+-m\s+pip)\s+install\s+(?:--[\w-]+\s+)*([A-Za-z0-9_.\-]+)",
                command,
                _re.IGNORECASE,
            )
            if pkg_cmd_match:
                pkg_from_cmd = pkg_cmd_match.group(1).lower().replace("-", "_")
                beliefs.observe(
                    _bkey(pkg_from_cmd, "installed"),
                    holds=True,
                    kind=EvidenceKind.MUTATION,
                    detail="pip install succeeded (cmd)",
                )
                beliefs.observe(
                    _bkey(pkg_from_cmd, "exists"),
                    holds=True,
                    kind=EvidenceKind.MUTATION,
                    detail="pip install succeeded — clearing any prior REFUTED",
                )
                if world is not None:
                    # PACKAGE node + PROVIDES edge to its executable: this edge
                    # is what makes a later uninstall cascade the tool to MISSING.
                    world.observe_package(pkg_from_cmd, provenance=command[:80])

        if "install" in command.lower() and "successfully installed" in out_lower:
            # Determine scope: check both the command AND the output for venv markers.
            # pip install inside an active venv prints paths like .venv\Scripts\yt-dlp.
            # Checking only the command string misses cases where the system pip
            # is invoked from a venv-activated session and installs into the venv.
            _venv_sigs = (".venv", "/venv/", "\\venv\\", "site-packages")
            scope = (
                "venv"
                if (
                    any(s in command for s in _venv_sigs)
                    or any(s in (output or "") for s in _venv_sigs)
                )
                else "global"
            )
            # Extract package names from "Successfully installed X-1.0 Y-2.0"
            pkg_block = _re.search(r"successfully installed\s+(.+)", out_lower)
            if pkg_block:
                raw_pkgs = pkg_block.group(1).strip()
                for raw_pkg in raw_pkgs.split():
                    pkg_name = _re.sub(r"-[\d.]+$", "", raw_pkg)  # strip version suffix
                    if pkg_name and len(pkg_name) > 1:
                        facts[f"tool_scope:{pkg_name}"] = SemanticFact(
                            key=f"tool_scope:{pkg_name}",
                            value=scope,
                            confidence=0.95,
                            source=command[:80],
                        )
                        facts[f"package_installed:{pkg_name}"] = SemanticFact(
                            key=f"package_installed:{pkg_name}",
                            value=scope,
                            confidence=0.95,
                            source=command[:80],
                        )
                        beliefs.observe(
                            _bkey(pkg_name, "installed"),
                            holds=True,
                            kind=EvidenceKind.MUTATION,
                            detail=f"pip install output: {scope}",
                        )
                        if world is not None:
                            world.observe_package(pkg_name, scope=scope, provenance=command[:80])
                        if scope == "venv":
                            beliefs.observe(
                                _bkey(pkg_name, "scope_is_venv"),
                                holds=True,
                                kind=EvidenceKind.PACKAGE_MANAGER,
                                detail="installed via venv pip",
                            )
                        elif scope == "global":
                            # score=1.0 → PROVEN so subsequent `where` empty-output cannot refute it
                            beliefs.observe(
                                _bkey(pkg_name, "available_globally"),
                                holds=True,
                                kind=EvidenceKind.MUTATION,
                                detail="installed via system pip (global scope)",
                            )
                        break  # one package per install command for safety

        # Version detection from VERIFY steps
        if step_type == "VERIFY":
            m = _re.search(r"([\w][\w.\-]+)\s+(\d+\.\d+[\d.]*)", output or "")
            if m:
                tool_v, version = m.group(1).strip(), m.group(2).strip()
                facts[f"tool_version:{tool_v}"] = SemanticFact(
                    key=f"tool_version:{tool_v}", value=version, confidence=1.0, source=command[:80]
                )
                beliefs.observe(
                    _bkey(tool_v, "version_known"),
                    holds=True,
                    kind=EvidenceKind.OUTPUT_HEURISTIC,
                    detail=f"version={version}",
                )
                beliefs.observe(
                    _bkey(tool_v, "exists"),
                    holds=True,
                    kind=EvidenceKind.OUTPUT_HEURISTIC,
                    detail=f"version command succeeded: {command[:50]}",
                )

        # Genuine tool-absent signal inside a "successful" (exit 0) output →
        # refute existence. Single owner: error_classifier.is_missing_tool_signal
        # (a "cannot find path" file error no longer wrongly refutes the tool).
        from .error_classifier import is_missing_tool_signal

        if is_missing_tool_signal(output, command):
            tool_candidate = command.strip().split()[0] if command.strip() else ""
            if tool_candidate and tool_candidate not in ("where", "which", "get-command"):
                # Same evidence-scope correction as the FILE_NOT_FOUND branch above:
                # a bare-name miss proves only :available_globally is false, not
                # :exists — a project-local copy may still be genuinely present.
                beliefs.observe(
                    _bkey(tool_candidate, "available_globally"),
                    holds=False,
                    kind=EvidenceKind.EXIT_CODE,
                    detail=f"missing-tool signal in output: {output[:80]}",
                )
                facts[f"tool_missing:{tool_candidate}"] = SemanticFact(
                    key=f"tool_missing:{tool_candidate}",
                    value="true",
                    confidence=1.0,
                    source=command[:80],
                )


# ═════════════════════════════════════════════════════════════════════════════
# LAYER 7 — ATTENTION MANAGER
# ═════════════════════════════════════════════════════════════════════════════


class AttentionManager:
    """
    Ranks all memory content by criticality and assembles a prompt-ready
    context string within TOTAL_CHAR_BUDGET characters.

    Priority tiers:
      0 CRITICAL  — blocked actions, constraints, REFUTED beliefs  (always included)
      1 IMPORTANT — recent failures, PROVEN beliefs                (included if budget allows)
      2 USEFUL    — semantic facts, LIKELY beliefs                 (included if budget allows)
      3 ARCHIVE   — old events, unrelated facts                    (always omitted)
    """

    TOTAL_CHAR_BUDGET = 3600  # ~900 tokens

    def build_context(
        self,
        wm: WorkingMemory,
        beliefs: BeliefSystem,
        facts: dict[str, SemanticFact],
        recent_failures: list[dict],
    ) -> str:
        sections: list[tuple[int, str]] = []

        # P0 CRITICAL: working memory (constraints + blocked)
        sections.append((0, wm.to_prompt()))

        # P0 CRITICAL: refuted beliefs
        refuted = [b for b in beliefs.all_beliefs() if b.state == BeliefState.REFUTED]
        if refuted:
            lines = ["PROVEN_FALSE:"]
            lines += [f"  ✗ {b.proposition}" for b in refuted[:6]]
            sections.append((0, "\n".join(lines)))

        # P1 IMPORTANT: proven beliefs
        proven = [b for b in beliefs.all_beliefs() if b.state == BeliefState.PROVEN]
        if proven:
            lines = ["PROVEN_TRUE:"]
            lines += [f"  ✓ {b.proposition}" for b in proven[:6]]
            sections.append((1, "\n".join(lines)))

        # P1 IMPORTANT: episodic recent failures (from persistent memory)
        if recent_failures:
            lines = ["EPISODIC_FAILURES:"]
            for failure in recent_failures[-3:]:
                lines.append(
                    f"  - {failure.get('command', '?')[:50]} → {failure.get('outcome', '?')[:40]}"
                )
            sections.append((1, "\n".join(lines)))

        # P2 USEFUL: semantic facts (typed propositions only)
        typed_facts = [
            f
            for f in facts.values()
            if any(
                f.key.startswith(p)
                for p in ("tool_path:", "tool_scope:", "tool_version:", "package_installed:")
            )
        ]
        if typed_facts:
            lines = ["KNOWN_FACTS:"]
            for fact in sorted(typed_facts, key=lambda x: x.ts, reverse=True)[:8]:
                lines.append(f"  {fact.key}={fact.value} (conf={fact.confidence:.1f})")
            sections.append((2, "\n".join(lines)))

        # Assemble within budget (higher priority first)
        char_budget = self.TOTAL_CHAR_BUDGET
        result_parts: list[str] = []
        for priority, text in sorted(sections, key=lambda x: x[0]):
            if len(text) <= char_budget:
                result_parts.append(text)
                char_budget -= len(text)
            elif char_budget > 120:
                result_parts.append(text[: char_budget - 3] + "…")
                char_budget = 0
                break

        return "\n\n".join(result_parts)


# ═════════════════════════════════════════════════════════════════════════════
# LAYER 8 — EXECUTION POLICY GUARD
# ═════════════════════════════════════════════════════════════════════════════


class ExecutionPolicyGuard:
    """
    Pre-execution gate. Asks the five sysadmin questions before any command runs:
      1. Is the result already PROVEN?
      2. Was this exact command already tried (and failed)?
      3. Is a prerequisite known to be absent?
      4. Is this action explicitly blocked?
      5. Would this overwrite a known executable?
    """

    def check(
        self,
        command: str,
        step_id: str,
        step_type: str,
        wm: WorkingMemory,
        beliefs: BeliefSystem,
        facts: dict[str, SemanticFact],
        world=None,
    ) -> tuple[bool, str]:
        """Returns (allow, reason). allow=False → abort this step."""

        # 1. Already proven? (skip redundant VERIFY steps)
        if step_type == "VERIFY":
            tool = _real_tool(command)
            if (
                tool
                and beliefs.is_proven(_bkey(tool, "exists"))
                and beliefs.is_proven(_bkey(tool, "version_known"))
            ):
                return (
                    False,
                    f"SKIP: {tool} is PROVEN to exist with known version — verify is redundant",
                )

        # 2. Exact command already tried and blocked?
        h = _cmd_hash(command)
        blocked, reason = wm.is_blocked(f"retry_exact:{h}")
        if blocked:
            return False, f"BLOCKED: exact retry forbidden — {reason}"

        # 3. Explicit step_id block?
        blocked, reason = wm.is_blocked(step_id)
        if blocked:
            return False, f"BLOCKED: step {step_id} — {reason}"

        # 4. Tool known absent?
        # DISCOVERY and RECOVER must always be allowed — they are the mechanisms
        # that re-establish truth after a false refutation.
        # VERIFY must also be allowed: "where yt-dlp" or "yt-dlp --version" after
        # PATH update is exactly how we confirm presence — blocking it creates a
        # dead-lock where we cannot recover from a false REFUTED state.
        # Only block steps that INVOKE the tool for its primary purpose (MODIFY/default).
        tool = _real_tool(command)
        if tool and step_type not in ("DISCOVERY", "RECOVER", "VERIFY"):
            if beliefs.is_refuted(_bkey(tool, "exists")):
                return False, (
                    f"BLOCKED: {tool} is REFUTED (confirmed absent) — "
                    "install first before attempting to run"
                )

        # 5. Unbounded recursive filesystem scan over a shallow path?
        # Get-ChildItem/find -Recurse over paths with < 3 components (e.g. C:\Users\ExampleUser)
        # will scan millions of files and time out. Require the caller to add -Depth or
        # target a specific subdirectory instead.
        import re as _re

        if _re.search(r"-Recurse\b", command, _re.IGNORECASE) or _re.search(
            r"\bfind\b.*-r", command
        ):
            # Extract the -Path argument or first path-like token
            path_m = _re.search(r'-Path\s+["\']?([A-Za-z]:[^"\';\s]*)', command, _re.IGNORECASE)
            if not path_m:
                path_m = _re.search(r'([A-Za-z]:\\[^"\';\s]*)', command)
            if path_m:
                scan_path = path_m.group(1).rstrip("'\"")
                # Count path components (depth from drive root)
                depth = len(
                    [p for p in scan_path.replace("\\", "/").split("/") if p and p != scan_path[:2]]
                )
                if depth < 3 and "-Depth" not in command:
                    return False, (
                        f"BLOCKED: unbounded recursive scan over shallow path '{scan_path}' "
                        f"(depth={depth} < 3) — add -Depth 3 or target a specific subdirectory"
                    )

        # 6. Write_file to a known executable path or explicitly blocked path?
        import re as _re

        write_match = _re.search(r"write_file\|([^|]+)", command, _re.IGNORECASE)
        if not write_match:
            write_match = _re.search(r'Set-Content\s+["\']?(\S+)', command, _re.IGNORECASE)
        if write_match:
            target_path = write_match.group(1).strip().strip("'\"")
            # Check explicit block (set by INVALID_EXECUTABLE inference rule)
            blocked, reason = wm.is_blocked(f"write_file:{target_path}")
            if blocked:
                return False, f"BLOCKED: write_file to {target_path} — {reason}"
            # Invariant 3, single source: the world graph decides whether this
            # path is a tracked executable (replaces the old tool_path fact scan
            # — same truth previously duplicated in assert_safe_overwrite).
            if world is not None:
                wreason = world.write_block_reason(target_path)
                if wreason:
                    return False, f"BLOCKED: {wreason}"

        return True, ""


# ═════════════════════════════════════════════════════════════════════════════
# TOP-LEVEL CONTEXT  (attached to SystemState)
# ═════════════════════════════════════════════════════════════════════════════


class ReasoningContext:
    """
    Integrates all reasoning layers. One instance per run, attached to SystemState.

    Usage in orchestrator:
        sysstate.init_reasoning(goal)          # once, after SystemState created
        sysstate.reasoning.pre_execute_check(command, step_id, step_type)
        sysstate.reasoning.post_step_update(step_id, command, success, error_class, output, step_type)
        sysstate.reasoning.get_prompt_context()  # injected into supervisor prompt
    """

    def __init__(self, objective: str, run_id: str, world=None):
        self.run_id = run_id
        self.objective = objective
        # WorldGraph (world.py) — single identity store shared with SystemState.
        # Optional so the reasoning layers stay independently testable.
        self.world = world
        self.working_memory = WorkingMemory(objective)
        self.beliefs = BeliefSystem(world=world)
        self.semantic_facts: dict[str, SemanticFact] = {}
        self._inference = InferenceEngine()
        self._deduction = DeductionEngine()
        self._attention = AttentionManager()
        self._policy = ExecutionPolicyGuard()
        self._failed_assumptions: list[FailedAssumption] = []

    # ── Public API ────────────────────────────────────────────────────────────

    def pre_execute_check(self, command: str, step_id: str, step_type: str) -> tuple[bool, str]:
        """Call before every step attempt. Returns (allow, reason)."""
        return self._policy.check(
            command=command,
            step_id=step_id,
            step_type=step_type,
            wm=self.working_memory,
            beliefs=self.beliefs,
            facts=self.semantic_facts,
            world=self.world,
        )

    def post_step_update(
        self,
        step_id: str,
        command: str,
        success: bool,
        error_class,  # ErrorClass | None
        output: str,
        step_type: str,
    ) -> list[str]:
        """
        Call after every step attempt.
        Returns list of human-readable inference conclusions.
        """
        # Inference engine updates beliefs + facts + working memory
        conclusions = self._inference.process_step_result(
            step_id=step_id,
            command=command,
            success=success,
            error_class=error_class,
            output=output,
            step_type=step_type,
            wm=self.working_memory,
            beliefs=self.beliefs,
            facts=self.semantic_facts,
            world=self.world,
        )
        # Deduction engine derives new constraints from updated state
        new_deductions = self._deduction.derive(
            wm=self.working_memory,
            beliefs=self.beliefs,
            facts=self.semantic_facts,
        )
        for d in new_deductions:
            conclusions.append(f"⟹ {d.conclusion}")
        self.working_memory.current_step += 1
        return conclusions

    def get_prompt_context(self) -> str:
        """Build ranked reasoning context for supervisor prompt injection."""
        try:
            from . import memory as _mem

            recent = [e for e in _mem.get_recent_events(n=12) if e.get("exit_code", 0) != 0]
        except Exception:
            recent = []
        return self._attention.build_context(
            wm=self.working_memory,
            beliefs=self.beliefs,
            facts=self.semantic_facts,
            recent_failures=recent,
        )

    def observe_belief(
        self, key: BeliefKey, *, holds: bool, kind: EvidenceKind, detail: str
    ) -> None:
        self.beliefs.observe(key, holds=holds, kind=kind, detail=detail)

    def query_belief(self, key: BeliefKey) -> Optional[Belief]:
        return self.beliefs.get(key)

    def add_semantic_fact(
        self, key: str, value: str, confidence: float = 1.0, source: str = ""
    ) -> None:
        self.semantic_facts[key] = SemanticFact(
            key=key, value=value, confidence=confidence, source=source
        )
        try:
            from . import memory as _mem

            _mem.save_semantic_fact(
                run_id=self.run_id,
                key=key,
                value=value,
                confidence=confidence,
                goal=self.objective,
            )
        except Exception:
            pass

    def record_failed_assumption(
        self,
        assumption: str,
        evidence: str,
        error_class: str,
        invalid_until: str,
    ) -> None:
        fa = FailedAssumption(
            assumption=assumption,
            evidence=evidence,
            error_class=error_class,
            invalid_until=invalid_until,
        )
        self._failed_assumptions.append(fa)
        self.working_memory.add_constraint(f"NOT: {assumption} (until: {invalid_until})")
        try:
            from . import memory as _mem

            _mem.save_failed_assumption(
                run_id=self.run_id,
                assumption=assumption,
                evidence=evidence,
                error_class=error_class,
                invalid_until=invalid_until,
                goal=self.objective,
            )
        except Exception:
            pass

    def get_failed_assumptions(self) -> list[FailedAssumption]:
        return list(self._failed_assumptions)

    def debug_dump(self) -> dict:
        """Return a serializable snapshot for telemetry/debugging."""
        return {
            "run_id": self.run_id,
            "step": self.working_memory.current_step,
            "beliefs": {
                str(key): {
                    "state": belief.state.value,
                    "support": belief.support.kind.name if belief.support else None,
                    "against": belief.against.kind.name if belief.against else None,
                }
                for key, belief in self.beliefs._beliefs.items()
            },
            "semantic_facts": {
                k: {"value": f.value, "confidence": f.confidence}
                for k, f in self.semantic_facts.items()
            },
            "blocked_actions": dict(self.working_memory.blocked_actions),
            "constraints": list(self.working_memory.active_constraints),
            "failed_assumptions": [
                {"assumption": fa.assumption, "invalid_until": fa.invalid_until}
                for fa in self._failed_assumptions
            ],
        }
