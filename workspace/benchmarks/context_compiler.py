"""
Context Compiler — minimal prototype (M0/F0).

Validates the v2 thesis (brain/architecture-next/context-engineering.md) against the
CURRENT belief system, without building the Knowledge Graph or the scheduler.

Two builders operate on the SAME belief snapshot (a live SystemState OR a telemetry
record), so they can be A/B-compared:

  build_current_context(belief)      → replicates the v1 assembly shape (supervisor.plan):
        full workspace/env dump + ALL recent events + memory + ocke + reasoning.
        Grows with history → this is what triggers the 4B parse-error (Issue #8).

  compile_context(goal, belief, budget) → the prototype compiler:
        SCOPE → RETRIEVE → RANK → BUDGET → COMPRESS → RENDER.
        Selects ONLY goal-relevant facts/capabilities, ranked, packed under a hard
        token budget, rendered as compact typed rows. Does NOT grow with history.

Token counting: pass a real tokenizer (e.g. llama_cpp `model.tokenize`) for exact
counts; otherwise a chars/4 heuristic is used and labelled approximate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


# ── tokenization ──────────────────────────────────────────────────────────────
def count_tokens(text: str, tokenizer: Callable[[str], int] | None = None) -> int:
    if tokenizer is not None:
        try:
            return tokenizer(text)
        except Exception:
            pass
    # heuristic fallback (approximate) — real numbers come from the model tokenizer
    return max(1, round(len(text) / 4))


# ── belief adapter (works on live SystemState OR a telemetry dict) ────────────
@dataclass
class Belief:
    goal: str
    environment: dict  # os_name, shell, cwd, home, user, path_sep
    facts: dict  # key -> {value, source, ...}
    capabilities: dict  # name -> {available, path, version, ...}
    history: list  # list of action dicts (command, exit_code, ...)

    @staticmethod
    def from_telemetry(rec: dict) -> "Belief":
        return Belief(
            goal=rec.get("goal", ""),
            environment=rec.get("environment", {}) or {},
            facts=rec.get("facts", {}) or {},
            capabilities=rec.get("capabilities", {}) or {},
            history=rec.get("history", []) or [],
        )

    @staticmethod
    def from_sysstate(ss, goal: str) -> "Belief":
        # live SystemState: .facts (key->Fact), .capabilities (name->Capability), .env
        def _facts():
            out = {}
            for k, f in getattr(ss, "facts", {}).items():
                out[k] = {"value": getattr(f, "value", ""), "source": getattr(f, "source", "")}
            return out

        def _caps():
            out = {}
            for n, c in getattr(ss, "capabilities", {}).items():
                out[n] = {
                    "available": getattr(c, "available", None),
                    "path": getattr(c, "path", ""),
                    "version": getattr(c, "version", ""),
                }
            return out

        env = getattr(ss, "environment", None) or {}
        if hasattr(env, "__dict__"):
            env = env.__dict__
        return Belief(
            goal=goal,
            environment=env,
            facts=_facts(),
            capabilities=_caps(),
            history=list(getattr(ss, "history", []) or []),
        )


_WORD = re.compile(r"[a-zA-Z0-9_./-]{3,}")


def _keywords(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text)}


# ── ARM A: current (v1-shape) context ────────────────────────────────────────
def build_current_context(b: Belief) -> str:
    """Approximates the v1 supervisor.plan() context shape and, crucially, its GROWTH:
    every fact, every capability, and the FULL action history are dumped."""
    parts = [f"GOAL: {b.goal}", ""]
    env = b.environment
    parts.append("ENVIRONMENT:")
    for k, v in env.items():
        parts.append(f"  {k}: {v}")
    parts.append("")
    parts.append("CAPABILITIES (all):")
    for name, c in b.capabilities.items():
        parts.append(
            f"  {name}: available={c.get('available')} path={c.get('path', '')} "
            f"version={c.get('version', '')} note={c.get('note', '')}"
        )
    parts.append("")
    parts.append("FACTS (all):")
    for k, f in b.facts.items():
        parts.append(f"  {k} = {f.get('value', '')}  (source={f.get('source', '')})")
    parts.append("")
    parts.append("EVENT HISTORY (full):")
    for h in b.history:
        if isinstance(h, dict):
            parts.append(f"  $ {str(h.get('command', ''))}")
            out = str(h.get("stdout", ""))
            if out:
                parts.append(f"    -> {out[:400]}")
            err = str(h.get("stderr", ""))
            if err:
                parts.append(f"    !! {err[:200]}")
            parts.append(f"    exit={h.get('exit_code')}")
    return "\n".join(parts)


# ── ARM B: compiled context ──────────────────────────────────────────────────
def compile_context(
    goal: str, b: Belief, budget_tokens: int = 1200, tokenizer: Callable[[str], int] | None = None
) -> str:
    """SCOPE → RETRIEVE → RANK → BUDGET → COMPRESS → RENDER."""
    gk = _keywords(goal)

    # RANK facts by relevance = keyword overlap with goal (+ small env/capability priority)
    def _score(key: str, val: str) -> float:
        kk = _keywords(f"{key} {val}")
        overlap = len(gk & kk)
        return overlap + (0.2 if key in ("os_name", "os_version", "shell", "home", "cwd") else 0)

    # env: keep only the always-relevant minimal set (compact)
    env = b.environment
    env_row = (
        f"os={env.get('os_name', '?')} v={env.get('os_version', '?')} "
        f"shell={env.get('shell', '?')} cwd={env.get('cwd', '?')} "
        f"home={env.get('home', '?')} sep={env.get('path_sep', '')}"
    )

    # capabilities: only those whose name intersects the goal, plus unavailable ones
    # relevant to the goal (knowing what's MISSING matters for planning).
    cap_rows = []
    for name, c in b.capabilities.items():
        nk = _keywords(name)
        if gk & nk or c.get("available") is False:
            state = "OK" if c.get("available") else "MISSING"
            extra = c.get("version") or c.get("path") or ""
            cap_rows.append(
                (
                    len(gk & nk) + (0.5 if not c.get("available") else 0),
                    f"{name}={state} {extra}".strip(),
                )
            )
    cap_rows.sort(key=lambda x: -x[0])

    # facts: rank, keep top relevant
    fact_scored = []
    for k, f in b.facts.items():
        if k in (
            "os_name",
            "os_version",
            "shell",
            "home",
            "user",
            "path_sep",
            "workspace_snapshot",
        ):
            continue  # env already compacted; snapshot excluded (that's the bloat)
        val = str(f.get("value", ""))
        s = _score(k, val)
        if s > 0:
            fact_scored.append((s, f"{k}={val[:120]}"))
    fact_scored.sort(key=lambda x: -x[0])

    # last failure only (not full history) — recovery needs the error, not the log
    last_err = ""
    for h in reversed(b.history):
        if isinstance(h, dict) and (
            h.get("exit_code") not in (0, None) or h.get("success") is False
        ):
            last_err = f"$ {str(h.get('command', ''))[:80]} -> exit={h.get('exit_code')} :: {str(h.get('stderr', ''))[:120]}"
            break

    # RENDER + BUDGET pack
    out = [f"GOAL: {goal}", f"ENV: {env_row}"]
    if cap_rows:
        out.append("CAP: " + " | ".join(r for _, r in cap_rows[:8]))
    if last_err:
        out.append("LAST_ERROR: " + last_err)
    out.append("FACTS:")
    base = "\n".join(out)
    used = count_tokens(base, tokenizer)
    for _, row in fact_scored:
        line = f"  {row}"
        t = count_tokens(line, tokenizer)
        if used + t > budget_tokens:
            out.append(f"  … (+{len(fact_scored)} facts elided under budget)")
            break
        out.append(line)
        used += t
    return "\n".join(out)


if __name__ == "__main__":
    demo = Belief(
        goal="verifica se la porta 8080 è occupata e da quale processo",
        environment={
            "os_name": "Windows",
            "os_version": "10.0.19045",
            "shell": "powershell",
            "cwd": "C:/tmp",
            "home": "C:/Users/x",
            "path_sep": ";",
        },
        facts={
            f"discovery::step{i}": {"value": f"irrelevant fact number {i}" * 3, "source": "probe"}
            for i in range(30)
        }
        | {"port::8080": {"value": "LISTEN pid 1234 node", "source": "probe"}},
        capabilities={
            "netstat": {"available": True},
            "ss": {"available": False},
            "docker": {"available": False},
        },
        history=[
            {"command": "netstat -ano", "exit_code": 0, "stdout": "x" * 2000},
            {"command": "badcmd", "exit_code": 1, "stderr": "not recognized"},
        ],
    )
    cur = build_current_context(demo)
    comp = compile_context(demo.goal, demo, budget_tokens=400)
    print(f"current  tokens≈{count_tokens(cur)}")
    print(f"compiled tokens≈{count_tokens(comp)}")
    print("----- compiled -----")
    print(comp)
