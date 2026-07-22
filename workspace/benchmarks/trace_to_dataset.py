"""Turn agent run logs into a reward-labelled dataset — and surface the next bottleneck.

Two jobs, one parser:

  1. DATASET FOUNDATION. Every authoring step in a run is an example with a VERIFIABLE,
     environment-computed reward (the only kind the RL mandate allows): did the file end up
     with content, did the predicate pass, did the command exit 0. Emitted as JSONL, one
     record per step, categorised. (Full SFT prompt→completion pairs need the runtime to log
     the coder's raw output; that is the next step, and only if a residual MODEL gap is ever
     measured — right now the dominant failure was architectural, not model capacity.)

  2. FAILURE ANALYSIS. The same records, aggregated per category, tell you WHERE the agent
     fails and HOW (empty file, hallucinated command, wrong tool) — which is how you find the
     NEXT architectural hypothesis to test before ever reaching for training.

Reward is not subjective: it is read off the run's own verdicts (`✓ Step complete`,
`⚠ not achieved`, artifact checks), which are themselves gated by the deterministic predicates.

Usage:
    python -m benchmarks.trace_to_dataset                     # all logs under var/benchmark
    python -m benchmarks.trace_to_dataset --logs validation/stress/det1
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from src.config import ROOT

OUT = ROOT / "var" / "benchmark" / "dataset"

# Category from the step objective + tool — the buckets the training mandate lists.
_CATEGORY_RULES: tuple[tuple[str, re.Pattern], ...] = (
    (
        "project_scaffolding",
        re.compile(
            r"\b(init|scaffold|create.*project|new project|vite|next|angular|django|remix)\b", re.I
        ),
    ),
    (
        "code_authoring",
        re.compile(
            r"\b(server|component|module|write.*file|create.*file|\.js|\.ts|\.py|\.jsx|\.tsx)\b",
            re.I,
        ),
    ),
    (
        "package_management",
        re.compile(r"\b(install|npm|pnpm|yarn|pip|package\.json|dependenc)\b", re.I),
    ),
    ("filesystem", re.compile(r"\b(directory|folder|path|mkdir|move|copy|rename)\b", re.I)),
    (
        "discovery",
        re.compile(r"\b(discover|check|find|which|version|available|web_search)\b", re.I),
    ),
    ("verification", re.compile(r"\b(verify|confirm|validate|ensure)\b", re.I)),
    ("recovery", re.compile(r"\b(fix|correct|repair|retry|recover)\b", re.I)),
)
_HALLUCINATED = re.compile(r"\b[A-Z][A-Z_]{4,}\b.*is not recognized", re.I)
_STEP = re.compile(r"^\s*►\s*(.+)$")
_TOOL = re.compile(r"^\s*tool:\s*(.+)$")


def _categorise(objective: str, tool: str) -> str:
    blob = f"{objective} {tool}"
    for name, rx in _CATEGORY_RULES:
        if rx.search(blob):
            return name
    return "other"


def _decode(p: Path) -> list[str]:
    try:
        return p.read_bytes().decode("utf-8", "replace").splitlines()
    except OSError:
        return []


def _steps_from_log(lines: list[str], source: str) -> list[dict]:
    """One record per ► step block: objective, authored tool, verifiable outcome + reward."""
    out: list[dict] = []
    cur: dict | None = None

    def close(rec):
        if rec is None:
            return
        # reward: environment-verifiable, read off the run's own gated verdicts.
        if rec["outcome"] == "success":
            rec["reward"] = 1.0
        elif rec["hallucinated"]:
            rec["reward"] = -1.0
        elif rec["empty_file"]:
            rec["reward"] = -0.7
        else:
            rec["reward"] = -0.5
        rec["category"] = _categorise(rec["objective"], rec["tool"])
        out.append(rec)

    for ln in lines:
        m = _STEP.match(ln)
        if m:
            close(cur)
            cur = {
                "source": source,
                "objective": m.group(1).strip()[:200],
                "tool": "",
                "outcome": "unknown",
                "empty_file": False,
                "hallucinated": False,
                "content_authored": False,
            }
            continue
        if cur is None:
            continue
        mt = _TOOL.match(ln)
        if mt and not cur["tool"]:
            cur["tool"] = mt.group(1).strip()[:200]
        if "authored file content" in ln:
            cur["content_authored"] = True
        if "✓ Step complete" in ln or "Step complete" in ln:
            cur["outcome"] = "success"
        if "not achieved" in ln or "artifact check failed" in ln:
            cur["outcome"] = "failure"
        if "file is empty" in ln or "are all empty" in ln:
            cur["empty_file"] = True
        if _HALLUCINATED.search(ln):
            cur["hallucinated"] = True
    close(cur)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--logs", default="", help="a specific run dir (default: all known run dirs)")
    a = ap.parse_args()

    if a.logs:
        roots = [ROOT / a.logs]
    else:
        roots = [ROOT / "var" / "benchmark" / "agent_eval", ROOT / "validation" / "stress"]

    log_files: list[Path] = []
    for r in roots:
        if r.exists():
            log_files += [p for p in r.rglob("*.log") if "workspaces" not in p.parts]

    records: list[dict] = []
    seen: set = set()
    for lf in log_files:
        for rec in _steps_from_log(_decode(lf), lf.stem):
            key = (rec["category"], rec["objective"][:80], rec["tool"][:80], rec["outcome"])
            if key in seen:
                continue
            seen.add(key)
            records.append(rec)

    OUT.mkdir(parents=True, exist_ok=True)
    ds = OUT / "steps.jsonl"
    with ds.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")

    # Failure analysis: where and how the agent fails, per category.
    cats: dict[str, dict] = {}
    for r in records:
        c = cats.setdefault(
            r["category"], {"n": 0, "ok": 0, "empty": 0, "halluc": 0, "authored": 0}
        )
        c["n"] += 1
        c["ok"] += r["outcome"] == "success"
        c["empty"] += r["empty_file"]
        c["halluc"] += r["hallucinated"]
        c["authored"] += r["content_authored"]

    print(f"{len(records)} deduped step records from {len(log_files)} logs → {ds}\n")
    print(f"{'category':22} {'n':>4} {'ok%':>5} {'empty':>6} {'halluc':>7} {'authored':>9}")
    for cat, c in sorted(cats.items(), key=lambda kv: -kv[1]["n"]):
        okp = round(100 * c["ok"] / c["n"]) if c["n"] else 0
        print(f"{cat:22} {c['n']:>4} {okp:>4}% {c['empty']:>6} {c['halluc']:>7} {c['authored']:>9}")
    print(f"\n[dataset] {ds}")


if __name__ == "__main__":
    main()
