"""
Generator engine: turns parametric `family` functions into a de-duplicated,
schema-valid, difficulty-balanced corpus of `Case` objects.

Contract for a family
----------------------
A family is a zero-argument generator function decorated with `@register(name,
os_list)`. It `yield`s `Case` objects, one per point in its parameter space. It
does NOT assign the final `id` (the engine numbers cases per OS+domain), and it
does NOT worry about global de-duplication (the engine drops signature collisions).

Why families instead of a flat list
------------------------------------
The benchmark must cover a *category* of systems, not a database of tools (see the
project Operating Contract). A family reasons over an axis of the parameter matrix
(services x failure-causes, package-managers x conflict-modes, …). Adding a new tool
to `shared/matrix.py` therefore expands coverage automatically, with no new code —
the same property we require of the agent under test.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from typing import Callable, Iterator

from ..shared.model import (
    DEFAULT_TIME_S,
    DEFAULT_TOKENS,
    OS,
    Case,
    Difficulty,
    Verify,
)

FamilyFn = Callable[[], Iterator[Case]]

# name -> (fn, os_list). Registration order is preserved for deterministic ids.
FAMILIES: dict[str, tuple[FamilyFn, list[str]]] = {}


def register(name: str, os_list: list[str]):
    def deco(fn: FamilyFn) -> FamilyFn:
        if name in FAMILIES:
            raise ValueError(f"duplicate family name: {name}")
        FAMILIES[name] = (fn, os_list)
        fn._family_name = name  # type: ignore[attr-defined]
        return fn

    return deco


# ─────────────────────────────────────────────────────────────────────────────
# Case builder — fills the boilerplate so families focus on the DISTINGUISHING
# content. Everything passed is required to be real; the only auto-filled fields
# are id (engine), budgets (difficulty-derived unless overridden) and schema bits.
# ─────────────────────────────────────────────────────────────────────────────
def build_case(
    *,
    os: str,
    domain: str,
    difficulty: str,
    title: str,
    goal: str,
    scenario: str,
    environment: dict,
    initial_state: list[str],
    expected_reasoning: list[str],
    expected_commands: list[str],
    forbidden_commands: list[str],
    safety_constraints: list[str],
    success_criteria: str,
    failure_criteria: str,
    success_check: Verify,
    recovery_strategy: str,
    ground_truth: dict,
    possible_mistakes: list[str],
    hints: list[str],
    reference_solution: list[str],
    alternative_solution: list[str],
    edge_cases: list[str],
    prerequisites: list[str] | None = None,
    risk: str = "SAFE",
    failure_check: Verify | None = None,
    tags: list[str] | None = None,
    golden: bool = False,
    family: str = "",
    time_s: int | None = None,
    token_budget: int | None = None,
) -> Case:
    diff = Difficulty(difficulty)
    return Case(
        id="",  # assigned by engine
        title=title,
        difficulty=diff,
        os=OS(os),
        domain=domain,
        prerequisites=prerequisites or [],
        scenario=scenario,
        environment=environment,
        initial_state=initial_state,
        expected_reasoning=expected_reasoning,
        expected_commands=expected_commands,
        forbidden_commands=forbidden_commands,
        safety_constraints=safety_constraints,
        success_criteria=success_criteria,
        failure_criteria=failure_criteria,
        success_check=success_check,
        recovery_strategy=recovery_strategy,
        ground_truth=ground_truth,
        expected_time_s=time_s if time_s is not None else DEFAULT_TIME_S[difficulty],
        expected_token_budget=token_budget
        if token_budget is not None
        else DEFAULT_TOKENS[difficulty],
        possible_mistakes=possible_mistakes,
        hints=hints,
        reference_solution=reference_solution,
        alternative_solution=alternative_solution,
        edge_cases=edge_cases,
        risk=risk,  # type: ignore[arg-type]
        goal=goal,
        failure_check=failure_check,
        tags=tags or [],
        golden=golden,
        family=family,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Generation pipeline
# ─────────────────────────────────────────────────────────────────────────────
_OS_PREFIX = {"linux": "LNX", "windows": "WIN", "macos": "MAC"}


def generate() -> list[Case]:
    """Run every registered family, dedupe by semantic signature, assign ids.

    Determinism: families iterate fixed matrices, so output is stable across runs
    (important for CI regression diffs). A fixed RNG seed covers the few places a
    family samples.
    """
    random.seed(1729)
    seen: set[str] = set()
    out: list[Case] = []
    for name, (fn, _os_list) in FAMILIES.items():
        for case in fn():
            case.family = case.family or name
            sig = case.signature()
            if sig in seen:
                continue
            seen.add(sig)
            out.append(case)

    # id assignment: {OSPREFIX}-{DOMAIN}-{00001}, numbered per (os, domain).
    counters: dict[tuple[str, str], int] = defaultdict(int)
    # stable order: os, domain, difficulty rank, title
    out.sort(key=lambda c: (c.os.value, c.domain, c.difficulty.rank, c.title))
    for c in out:
        key = (c.os.value, c.domain)
        counters[key] += 1
        dom = c.domain.upper().replace("-", "_")
        c.id = f"{_OS_PREFIX[c.os.value]}-{dom}-{counters[key]:05d}"
    mark_golden(out)
    return out


# Per-OS golden quota by difficulty. The golden set is the FROZEN comparison
# corpus: a stratified, deterministic sample across OS x difficulty x domain, plus
# every safety-refusal case (correctly refusing is the single most important
# behaviour to never regress). Total ≈ 3*(2+4+10+16+8) + refusals ≈ 120+.
_GOLDEN_QUOTA = {"easy": 2, "medium": 4, "hard": 10, "expert": 16, "principal": 8}


def mark_golden(cases: list[Case]) -> None:
    # 1) all safety refusals are golden (already flagged by the family, but enforce here)
    for c in cases:
        if c.family == "refusal_safety":
            c.golden = True
    # 2) stratified sample per (os, difficulty), spread across domains, deterministic
    by_od: dict[tuple[str, str], list[Case]] = defaultdict(list)
    for c in cases:
        by_od[(c.os.value, c.difficulty.value)].append(c)
    for (os_name, diff), group in by_od.items():
        quota = _GOLDEN_QUOTA.get(diff, 0)
        if quota <= 0 or not group:
            continue
        # order by domain then id for stability; stride to spread across domains
        group.sort(key=lambda c: (c.domain, c.id))
        picks = min(quota, len(group))
        step = max(1, len(group) // picks)
        for i in range(picks):
            group[(i * step) % len(group)].golden = True


def distribution(cases: list[Case]) -> dict:
    per_os = Counter(c.os.value for c in cases)
    per_os_diff: dict[str, Counter] = defaultdict(Counter)
    per_os_domain: dict[str, Counter] = defaultdict(Counter)
    per_family = Counter(c.family for c in cases)
    for c in cases:
        per_os_diff[c.os.value][c.difficulty.value] += 1
        per_os_domain[c.os.value][c.domain] += 1
    return {
        "total": len(cases),
        "per_os": dict(per_os),
        "per_os_difficulty": {k: dict(v) for k, v in per_os_diff.items()},
        "per_os_domain": {k: dict(v) for k, v in per_os_domain.items()},
        "per_family": dict(per_family),
        "golden": sum(1 for c in cases if c.golden),
    }
