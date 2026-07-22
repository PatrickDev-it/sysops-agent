"""
Baseline benchmark harness (M0/F0).

Runs the v1 agent over the 50-task sysops suite in isolated workspaces, evaluates
each task's structured verify predicate (no LLM), and aggregates the baseline metrics.

SAFETY / EXECUTION BOUNDARY:
  - `--dry-run`         : validates the plan and predicates, runs NO agent. (safe anywhere)
  - live run           : loads the local GGUF models and EXECUTES real commands.
                         Requires GPU + models present. Run this on the target machine.
  - `--safe-only`      : (default) only read-only/diagnostic tasks.
  - `--allow-mutating` : also run RECOVERABLE tasks (T48/T49) in isolated workspaces.
                         The DESTRUCTIVE task (T50) is ALWAYS included as a refusal test
                         (we assert it is REFUSED, we never execute it).

Output: validation/benchmark/<label>/ with per-task telemetry + suite_report.json + .md
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from src.config import BENCHMARK_DIR as BENCH_DIR
from src.config import TELEMETRY_DIR
from src.tools.predicates import read_text

from .suite_50 import TASKS, Task


def current_os() -> str:
    p = sys.platform
    if p.startswith("win"):
        return "windows"
    if p == "darwin":
        return "macos"
    return "linux"


def select(osname: str, safe_only: bool, allow_mutating: bool, ids: list[str]) -> list[Task]:
    out = []
    for t in TASKS:
        if ids and t.id not in ids:
            continue
        if osname not in t.os:
            continue
        if t.verify.get("kind") == "refused":
            out.append(t)  # always keep the refusal test
            continue
        if not t.safe and not allow_mutating:
            continue
        if t.safe or allow_mutating:
            out.append(t)
    return out


def evaluate_verify(task: Task, workspace: Path, verdict: str) -> tuple[bool, str]:
    """Deterministic post-condition check (no LLM)."""
    v = task.verify
    kind = v.get("kind")
    if kind == "refused":
        ok = verdict == "REFUSED"
        return ok, "REFUSED as required" if ok else f"expected REFUSED, got {verdict}"
    if kind == "artifact":
        p = workspace / v["path"]
        ok = p.exists() and p.stat().st_size > 0
        return ok, f"{v['path']} present & non-empty" if ok else f"{v['path']} missing/empty"
    if kind == "file_contains":
        p = workspace / v["path"]
        if not p.exists():
            return False, f"{v['path']} missing"
        # Artifacts are written by the agent through the host shell; PowerShell 5.1 emits
        # UTF-16LE with a BOM. Decode them the way the runtime does, or a correct file
        # reads as UTF-16 bytes`OS` and a passing task is scored as a failure.
        txt = read_text(p)
        ok = v["text"].lower() in txt.lower()
        return ok, f"contains '{v['text']}'" if ok else f"missing '{v['text']}'"
    return False, f"unknown verify kind {kind}"


def _latest_telemetry_verdict() -> str:
    files = sorted(TELEMETRY_DIR.glob("run_*.json"))
    if not files:
        return "?"
    try:
        return json.loads(files[-1].read_text(encoding="utf-8")).get("verdict", "?")
    except Exception:
        return "?"


def task_memory_dir(label: str, task_id: str) -> Path:
    """Where THIS task's episodic memory lives. One directory per task, never shared.

    The suite scores 48 tasks as independent trials. They were not independent: every task
    read `memory.get_recent_events()` into the planner prompt, and that memory is one
    process-wide store which accumulates across tasks AND survives across runs. Measured on
    two runs of identical code: `safety.jinja` and `prompt_enhancer.jinja` — which do not
    receive history — had byte-identical prompts on 95 of 95 calls, while the planner's FIRST
    call differed in 47 of 47 tasks. The leftover events were the difference, and everything
    downstream diverged from there.

    So the suite was measuring a 48-step dependent sequence seeded by whatever the previous
    run left behind. That is what made a pure repeat move 5 tasks.
    """
    return BENCH_DIR / label / "memory" / task_id


def run_live(tasks: list[Task], label: str) -> dict:
    import os

    from src import config, memory, trace
    from src.orchestrator import Orchestrator  # lazy: only when actually running

    out_dir = BENCH_DIR / label
    out_dir.mkdir(parents=True, exist_ok=True)
    trace_dir = out_dir / "traces"
    results = []
    for t in tasks:
        ws = out_dir / "workspaces" / t.id
        if ws.exists():
            shutil.rmtree(ws, ignore_errors=True)
        ws.mkdir(parents=True, exist_ok=True)

        # Independent trial: fresh memory per task. `config.MEMORY_DIR` is resolved at call
        # time by `memory._memory_dir()`, so rebinding it here is what the agent sees.
        mem = task_memory_dir(label, t.id)
        if mem.exists():
            shutil.rmtree(mem, ignore_errors=True)
        mem.mkdir(parents=True, exist_ok=True)
        config.MEMORY_DIR = mem
        memory.init_db()

        # Confinement root = this task's workspace. Reads outside are allowed; writes are
        # not. See src/tools/confinement.py — a filter, not a jail.
        os.environ["SISTEMISTA_CONFINE_ROOT"] = str(ws.resolve())
        trace.begin(t.id, trace_dir)

        t0 = time.time()
        verdict = "ERROR"
        err = ""
        try:
            Orchestrator(workspace=str(ws)).run(t.goal)
            verdict = _latest_telemetry_verdict()
        except Exception as e:  # keep the suite going
            err = f"{type(e).__name__}: {e}"
        elapsed = round(time.time() - t0, 2)
        trace.end()
        ok, reason = evaluate_verify(t, ws, verdict)
        results.append(
            {
                "id": t.id,
                "category": t.category,
                "goal": t.goal[:80],
                "verdict": verdict,
                "passed": ok,
                "reason": reason,
                "wall_s": elapsed,
                "error": err,
            }
        )
        print(f"[{t.id}] {'PASS' if ok else 'FAIL'} ({verdict}) {reason}  {elapsed}s", flush=True)

    passed = sum(1 for r in results if r["passed"])
    report = {
        "label": label,
        "os": current_os(),
        "n_tasks": len(tasks),
        "passed": passed,
        "arr": round(passed / len(tasks), 4) if tasks else 0.0,
        "results": results,
    }
    (out_dir / "suite_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


def dry_run(tasks: list[Task]) -> dict:
    print(f"# DRY RUN — {len(tasks)} task selezionati (nessun agente eseguito)\n")
    for t in tasks:
        flag = "safe" if t.safe else f"MUTATING/{t.risk}"
        print(
            f"  [{t.id}] {t.category:14s} {flag:16s} verify={t.verify.get('kind'):14s} :: {t.goal[:70]}"
        )
    cats = sorted({t.category for t in tasks})
    return {"n_selected": len(tasks), "categories": cats}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="validate & list; no agent")
    ap.add_argument("--safe-only", action="store_true", default=True)
    ap.add_argument("--allow-mutating", action="store_true", help="also run RECOVERABLE tasks")
    ap.add_argument("--all-os", action="store_true", help="ignore OS filter")
    ap.add_argument("--ids", default="", help="comma-separated task ids")
    ap.add_argument("--label", default=f"baseline_{int(time.time())}")
    args = ap.parse_args()

    osname = "any" if args.all_os else current_os()
    ids = [x.strip() for x in args.ids.split(",") if x.strip()]
    tasks = (
        TASKS
        if osname == "any" and not ids
        else select(
            osname if osname != "any" else current_os(),
            safe_only=args.safe_only,
            allow_mutating=args.allow_mutating,
            ids=ids,
        )
    )
    if osname == "any":
        tasks = [
            t
            for t in TASKS
            if (not ids or t.id in ids)
            and (t.safe or args.allow_mutating or t.verify.get("kind") == "refused")
        ]

    print(f"OS={current_os()}  selected={len(tasks)}  mutating_allowed={args.allow_mutating}\n")
    if args.dry_run:
        dry_run(tasks)
        return
    print("LIVE RUN — carica i modelli GGUF ed esegue comandi reali.\n")
    report = run_live(tasks, args.label)
    print(f"\nARR suite = {report['arr']:.1%}  ({report['passed']}/{report['n_tasks']})")
    print(f"[report] {BENCH_DIR / args.label / 'suite_report.json'}")


if __name__ == "__main__":
    main()
