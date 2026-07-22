"""
Core benchmark data model for the Sistemista OS-scenario benchmark (osbench).

A `Case` is one fully-structured, self-contained benchmark scenario for evaluating
an autonomous AI Systems-Engineering agent that operates EXCLUSIVELY via a terminal.

Design goals
------------
1. Every field the benchmark spec mandates is a first-class attribute (25 fields).
2. Machine-checkable outcome: `success_check` / `failure_check` are structured
   predicates (a `Verify` object), NOT prose — so a validator can score a run
   with zero LLM involvement. Prose lives in `success_criteria` for humans.
3. Alignment with the existing runtime harness: we reuse the `Risk` taxonomy
   (SAFE / RECOVERABLE / DESTRUCTIVE) and the verify-predicate concept already
   established in `benchmarks/suite_50.py`, so scoring can share vocabulary with
   `benchmarks/arr_aggregator.py` and `benchmarks/telemetry_schema.py`.
4. Deterministic identity: `signature()` yields a semantic fingerprint used by the
   generator to guarantee that no two emitted cases are the same problem in disguise.

This module has NO third-party dependencies (stdlib only) so the dataset can be
generated, validated and scored on a bare Python 3.10+ install on any OS.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Literal


# ─────────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────────
class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    EXPERT = "expert"
    PRINCIPAL = "principal"

    @property
    def rank(self) -> int:
        return {"easy": 0, "medium": 1, "hard": 2, "expert": 3, "principal": 4}[self.value]


class OS(str, Enum):
    LINUX = "linux"
    WINDOWS = "windows"
    MACOS = "macos"


# Reused verbatim from the runtime harness (suite_50.py) so risk semantics are shared.
Risk = Literal["SAFE", "RECOVERABLE", "DESTRUCTIVE"]

# Canonical domain taxonomy. Owner of the string set is datasets/taxonomy.md; this
# tuple is the machine-enforced enumeration the schema validator checks against.
DOMAINS: tuple[str, ...] = (
    "filesystem",
    "permissions",
    "acl",
    "ownership",
    "users",
    "groups",
    "ssh",
    "sudo",
    "services",
    "scheduler",
    "processes",
    "signals",
    "packages",
    "containers",
    "networking",
    "dns",
    "firewall",
    "routing",
    "logs",
    "performance",
    "memory",
    "storage",
    "lvm_raid",
    "encryption",
    "kernel",
    "drivers",
    "shell",
    "env_path",
    "certificates",
    "tls",
    "recovery",
    "backup",
    "monitoring",
    "security",
    "selinux_apparmor",
    "virtualization",
    "remote_access",
    "filesharing",
    "gpu",
    "toolchains",
    "git",
    "cicd",
    "iac",
    "kubernetes",
    "cloud",
    "databases",
    "proxy",
    "secrets",
    "boot",
    "upgrade",
    "wsl",
)


# ─────────────────────────────────────────────────────────────────────────────
# Machine-checkable verification predicate
# ─────────────────────────────────────────────────────────────────────────────
# A `Verify` predicate is a small typed dict evaluated by validators/ against the
# post-run system/workspace state. Kinds are intentionally state-based (not command
# string matching) so the agent is scored on OUTCOME, not on reproducing a golden
# command line. This is the core anti-gaming property of the benchmark.
VerifyKind = Literal[
    "artifact",  # a file exists at path
    "file_contains",  # file at path contains regex `pattern`
    "file_absent",  # path does NOT exist
    "file_mode",  # path has octal permission bits `mode` (POSIX)
    "file_owner",  # path is owned by `owner` (and optional `group`)
    "process_running",  # a process matching `pattern` is alive
    "process_absent",  # no process matches `pattern`
    "port_listening",  # something listens on tcp/udp `port`
    "port_closed",  # nothing listens on `port`
    "service_active",  # service `name` is active/running (systemd/sc/launchctl)
    "service_inactive",  # service `name` is stopped
    "command_succeeds",  # running `probe` exits 0 (read-only probe supplied by the case)
    "command_stdout",  # `probe` stdout matches regex `pattern`
    "http_ok",  # GET `url` returns status in `status` (default 2xx)
    "package_installed",  # package `name` present via the OS package manager
    "package_absent",  # package `name` not present
    "kv_equals",  # a config key (`selector`) resolves to `value` (json/yaml/ini/toml)
    "refused",  # agent correctly REFUSED a destructive/impossible goal
    "all_of",  # composite: every predicate in `checks` holds
    "any_of",  # composite: at least one predicate in `checks` holds
    "none_of",  # composite: no predicate in `checks` holds
]


@dataclass
class Verify:
    """A single structured, machine-evaluable outcome predicate.

    Only the fields relevant to `kind` are populated; the rest stay at defaults.
    The validator dispatches on `kind`. Composite kinds (all_of/any_of/none_of)
    nest child predicates in `checks`.
    """

    kind: VerifyKind
    path: str = ""
    pattern: str = ""
    mode: str = ""
    owner: str = ""
    group: str = ""
    port: int = 0
    proto: Literal["tcp", "udp"] = "tcp"
    name: str = ""
    probe: str = ""  # a READ-ONLY command the validator may run to observe state
    url: str = ""
    status: tuple[int, ...] = (200, 201, 204)
    selector: str = ""  # dotted path / key into a config file
    value: Any = None
    checks: list["Verify"] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"kind": self.kind}
        for k, v in asdict(self).items():
            if k == "kind":
                continue
            # keep only meaningful (non-default) fields to keep JSON compact
            if k == "checks":
                if self.checks:
                    d["checks"] = [c.to_dict() for c in self.checks]
                continue
            if k == "status":
                if tuple(v) != (200, 201, 204):
                    d[k] = list(v)
                continue
            if v not in ("", 0, None, "tcp"):
                d[k] = v
        return d

    @staticmethod
    def from_dict(d: dict) -> "Verify":
        d = dict(d)
        checks = [Verify.from_dict(c) for c in d.pop("checks", [])]
        status = tuple(d.pop("status", (200, 201, 204)))
        return Verify(checks=checks, status=status, **d)


# ─────────────────────────────────────────────────────────────────────────────
# The benchmark Case
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Case:
    # ---- Identity & classification (mandated fields) -------------------------
    id: str
    title: str
    difficulty: Difficulty
    os: OS
    domain: str

    # ---- Problem statement ---------------------------------------------------
    prerequisites: list[str]
    scenario: str
    environment: dict[str, Any]  # declarative env the harness must materialize
    initial_state: list[str]  # setup steps that create the broken/target state

    # ---- Expected agent behaviour -------------------------------------------
    expected_reasoning: list[str]  # the causal chain a correct agent should follow
    expected_commands: list[str]  # representative (NOT the only) correct commands
    forbidden_commands: list[str]  # commands that must never appear (regex ok)
    safety_constraints: list[str]  # invariants the agent must not violate

    # ---- Scoring anchors -----------------------------------------------------
    success_criteria: str  # human-readable definition of done
    failure_criteria: str
    success_check: Verify  # machine-checkable definition of done
    recovery_strategy: str
    ground_truth: dict[str, Any]  # canonical facts the state encodes (root cause, key values)

    # ---- Budgets & pedagogy --------------------------------------------------
    expected_time_s: int
    expected_token_budget: int
    possible_mistakes: list[str]
    hints: list[str]
    reference_solution: list[str]  # ordered canonical solution
    alternative_solution: list[str]  # a different valid path (tool/approach diversity)
    edge_cases: list[str]

    # ---- Alignment / harness metadata (reused from runtime harness) ----------
    risk: Risk = "SAFE"
    goal: str = ""  # the single natural-language instruction given to the agent
    failure_check: Verify | None = None
    tags: list[str] = field(default_factory=list)
    golden: bool = False  # part of the frozen gold-standard comparison set
    family: str = ""  # generator family that produced it (provenance)
    schema_version: str = "1.0"

    # ---------------------------------------------------------------- helpers
    def signature(self) -> str:
        """Semantic fingerprint used for de-duplication.

        Two cases collide iff they pose the same problem: same OS + domain + the
        salient parameters of the scenario (captured by `ground_truth` + goal).
        Difficulty/hints/prose do NOT enter the signature — a harder framing of the
        identical broken state is still the same problem and must be deduped.
        """
        salient = {
            "os": self.os.value,
            "domain": self.domain,
            "goal": _norm(self.goal or self.title),
            "gt": {k: _norm(str(v)) for k, v in sorted(self.ground_truth.items())},
        }
        blob = json.dumps(salient, sort_keys=True, ensure_ascii=False)
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["difficulty"] = self.difficulty.value
        d["os"] = self.os.value
        d["success_check"] = self.success_check.to_dict()
        d["failure_check"] = self.failure_check.to_dict() if self.failure_check else None
        d["signature"] = self.signature()
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @staticmethod
    def from_dict(d: dict) -> "Case":
        d = dict(d)
        d.pop("signature", None)
        d["difficulty"] = Difficulty(d["difficulty"])
        d["os"] = OS(d["os"])
        d["success_check"] = Verify.from_dict(d["success_check"])
        fc = d.get("failure_check")
        d["failure_check"] = Verify.from_dict(fc) if fc else None
        return Case(**d)


_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS.sub(" ", s.strip().lower())


# Difficulty → default budgets. A generator may override, but these keep budgets
# monotonic in difficulty so scoring's token/latency penalties are calibrated.
DEFAULT_TIME_S: dict[str, int] = {
    "easy": 60,
    "medium": 180,
    "hard": 480,
    "expert": 1200,
    "principal": 2400,
}
DEFAULT_TOKENS: dict[str, int] = {
    "easy": 1500,
    "medium": 4000,
    "hard": 12000,
    "expert": 30000,
    "principal": 60000,
}
