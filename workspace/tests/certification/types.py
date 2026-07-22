"""Shared types for the certification checks.

A check does not assert. It returns a CertRecord describing what it broke, what it
expected, what it did, and what it observed — and `test_certification` in each group
turns that record into a pytest verdict. The split exists because the diagnostic value
of these scenarios is in the narrative, not in the boolean: when one fails, the record
tells you which of five setup steps produced the wrong state.

That split is also how this suite once reported green while asserting nothing. Thirty-three
functions named `test_*` RETURNED their verdict; pytest warned about the non-None return and
passed them regardless. The rule that keeps it honest is now structural rather than cultural:
checks are named `check_*` so pytest cannot collect them directly, and the only `test_*`
function in each module is the boundary that asserts. `PytestReturnNotNoneWarning` is an error
in `pyproject.toml`, so a check renamed back into a test fails loudly instead of passing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"  # a genuine precondition is absent (no interpreter, no git) — not a result


@dataclass
class CertRecord:
    test_id: str
    group: str
    environment: dict[str, str]  # os, shell, python_version, …
    broken_state: str  # description of what was broken before
    expected_reasoning: str  # what the agent SHOULD do (not HOW)
    actions_taken: list[str] = field(default_factory=list)
    verification_command: str = ""  # command that proves the goal was reached
    final_state: str = ""
    verdict: Verdict = Verdict.FAIL
    failure_reason: str = ""
    elapsed_s: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def passed(self) -> bool:
        return self.verdict is Verdict.PASS

    def diagnostic(self) -> str:
        """The failure message pytest shows. Owned here so every group renders it identically
        and no call site re-derives the format."""
        lines = [
            f"{self.test_id} [{self.verdict.value}] {self.failure_reason}",
            f"  expected : {self.expected_reasoning}",
            f"  broken   : {self.broken_state}",
            f"  final    : {self.final_state}",
        ]
        if self.verification_command:
            lines.append(f"  verify   : {self.verification_command}")
        lines.append("  actions  :")
        lines.extend(f"      - {a}" for a in self.actions_taken)
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "test_id": self.test_id,
            "group": self.group,
            "environment": self.environment,
            "broken_state": self.broken_state,
            "expected_reasoning": self.expected_reasoning,
            "actions_taken": self.actions_taken,
            "verification_command": self.verification_command,
            "final_state": self.final_state,
            "verdict": self.verdict.value,
            "failure_reason": self.failure_reason,
            "elapsed_s": round(self.elapsed_s, 2),
            "metadata": self.metadata,
        }


class Timer:
    def __init__(self):
        self._start = time.monotonic()

    def elapsed(self) -> float:
        return time.monotonic() - self._start
