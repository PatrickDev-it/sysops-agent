"""
GoalRiskClassifier — pre-planning safety layer (FASE 7).

Classifies a goal as SAFE / RECOVERABLE / DESTRUCTIVE before any planning.
DESTRUCTIVE goals never reach the planner.

Two-layer design:
  1. A deterministic guard catches unambiguous whole-system destruction
     (rm -rf /, format c:, "wipe the machine") without an LLM call — fast and
     reliable even if the model is unavailable.
  2. An LLM classifier reasons about scope and reversibility for the rest.

Defaults to SAFE on any error: a false block stalls a legitimate task, and the
deterministic layer already covers the catastrophic cases.
"""

from __future__ import annotations

import re

from .. import model_router

SAFE = "SAFE"
RECOVERABLE = "RECOVERABLE"
DESTRUCTIVE = "DESTRUCTIVE"


# Deterministic catastrophic patterns — whole-system, irreversible, explicit.
# These are scope signals, not a framework/tool blacklist.
_CATASTROPHIC = [
    # `-rf?` matched only -r and -rf. `rm -fr /` — the same command with the flags in the
    # other order — walked straight past, as did every other spelling of the flag cluster.
    re.compile(r"\brm\s+-[a-zA-Z]*[rR][a-zA-Z]*\s+(/|~|\$HOME|/\*)\s*$"),
    re.compile(r"\brm\s+-[a-zA-Z]*[rR][a-zA-Z]*\s+(/|~|\$HOME)\s"),
    re.compile(r"\bformat\s+[a-z]:", re.I),
    re.compile(r"\bmkfs\b", re.I),
    re.compile(r"\bdd\s+if=.*of=/dev/([sh]d|nvme|disk)", re.I),
    re.compile(r":\(\)\s*\{.*\};:", re.S),  # fork bomb
    re.compile(r"\bdel\s+/[a-z]\s+[a-z]:\\?\s*$", re.I),
    # PowerShell equivalents of the above. The list named only POSIX forms, on a product
    # whose primary target is Windows.
    re.compile(r"\bRemove-Item\b[^|;]*-Recurse\b[^|;]*\b[a-z]:\\?\s*(\||;|$)", re.I),
    re.compile(r"\b(diskpart|Clear-Disk|Initialize-Disk|Format-Volume)\b", re.I),
    re.compile(r"\bvssadmin\s+delete\s+shadows\b", re.I),
    re.compile(r"\bcipher\s+/w\b", re.I),
    re.compile(r"\bbcdedit\b|\bbootrec\b", re.I),
    re.compile(r"\bchmod\s+-R\s+777\s+/\s*$", re.I),
]

# Phrase-level whole-system destruction in natural language.
_WHOLE_SYSTEM = re.compile(
    r"(delete|wipe|erase|destroy|format|nuke)\s+(everything|all\s+files|"
    r"the\s+(whole|entire)\s+(system|machine|disk|drive|computer))",
    re.I,
)
_REINSTALL_SYSTEM = re.compile(
    r"reinstall\s+(the\s+)?(whole\s+|entire\s+)?(system|os|operating\s+system|machine)",
    re.I,
)


def _deterministic(goal: str) -> str | None:
    """Return DESTRUCTIVE if a catastrophic pattern is present, else None."""
    for pat in _CATASTROPHIC:
        if pat.search(goal):
            return DESTRUCTIVE
    if _WHOLE_SYSTEM.search(goal) or _REINSTALL_SYSTEM.search(goal):
        return DESTRUCTIVE
    return None


def classify(goal: str) -> tuple[str, str]:
    """
    Returns (risk, reason). risk ∈ {SAFE, RECOVERABLE, DESTRUCTIVE}.
    """
    det = _deterministic(goal)
    if det == DESTRUCTIVE:
        return DESTRUCTIVE, "matched a whole-system irreversible destruction pattern"

    try:
        result = model_router.safety_call({"goal": goal})
        risk = str(result.get("risk", "")).upper().strip()
        if risk not in (SAFE, RECOVERABLE, DESTRUCTIVE):
            # An unrecognised value is an unclassified goal, not a safe one. Coercing it to
            # SAFE meant a malformed decode silently opened the gate.
            return RECOVERABLE, f"classifier returned an unrecognised risk {risk!r}"
        reason = str(result.get("reason", ""))
        return risk, reason
    except Exception as exc:
        # FAIL CLOSED. This used to `return SAFE`, three lines below a comment in
        # model_router.safety_call stating that a classifier which cannot answer must not
        # silently open the gate. The failure mode it produced is the worst possible one: the
        # NAV server being unreachable is exactly when the system is degraded, and that was
        # precisely when the DESTRUCTIVE gate switched itself off and a whole-system-destruction
        # goal proceeded to planning.
        #
        # RECOVERABLE rather than DESTRUCTIVE: an unreachable classifier is not evidence that
        # the goal is destructive, and refusing every goal whenever a model server hiccups
        # would make the agent unusable. RECOVERABLE is the "proceed, loudly, without the
        # benefit of the doubt" state — and unlike SAFE it is visible in the record.
        return RECOVERABLE, f"safety classifier unavailable — proceeding unclassified ({exc})"
