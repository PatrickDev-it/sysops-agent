"""Internal agent benchmark — the measurement the training mandate needs FIRST.

A benchmark is not a scaffold-rate. It is the instrument that decides whether the next
improvement is architectural or model-level: you cannot claim a model needs training until a
DETERMINISTIC eval shows a residual gap that architectural fixes did not close. This runner
computes, per case and aggregated, the metrics the project actually fails on:

  passed              filesystem score (manifest has content + entry artifact exists)   [stress_frameworks._score]
  verdict             the agent's own TASK COMPLETE / INCOMPLETE
  false_complete      verdict COMPLETE but the filesystem disagrees — the HONESTY metric
  empty_file_rate     0-byte files left in the workspace (the placeholder-artifact failure)
  hallucination       the coder invoked a non-existent, invented command token
  content_authored    the content-authoring path fired (coder wrote a file body, not a shell cmd)
  wall_s              wall time

Runs are DETERMINISTIC by construction (SISTEMISTA_DETERMINISTIC=1 → seed 42, greedy), so a
delta between two commits is a real effect, not a resample. Compares to a stored baseline if
one exists; writes the baseline on first run.

Usage:
    python -m benchmarks.agent_eval --only node_backend,react,django
    python -m benchmarks.agent_eval --set baseline        # write current as baseline
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from src.config import CODER_MODEL, LLAMA_SERVER_BIN, NAV_MODEL, ROOT

from benchmarks.stress_frameworks import CASES, _have, _score

OUT = ROOT / "var" / "benchmark" / "agent_eval"
_HALLUCINATED = re.compile(r"\b([A-Z][A-Z_]{4,}(?:_CMD|_CommandLine)?)\b.*is not recognized", re.I)


def _read(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8", "replace")
    except OSError:
        return ""


def _metrics_from_run(
    case, ws: Path, log: str, wall_s: float, *, timed_out: bool, exit_code: int | None
) -> dict:
    """Score one case.

    `timed_out` and `exit_code` are parameters rather than inferred, because inferring them is
    exactly what went wrong: the caller caught `subprocess.TimeoutExpired` with a bare `pass`
    and set no flag, and `check=False` discarded the exit code, so scoring saw only the
    filesystem and could not tell a completed run from a killed one.

    That had already fired. The stored baseline contains
        {"id": "node_backend", "passed": true, "verdict": "?", "wall_s": 600.0}
    — 600.0 s is the timeout to the tenth of a second. The single "pass" behind
    `pass_rate: 0.333` WAS the hang; the true rate was 0/3. Every future commit would have been
    diffed against that, and a patch that made the agent hang less would have read as a
    regression.
    """
    scored, reasons = _score(case, ws)
    verdict = (
        "COMPLETE"
        if "TASK COMPLETE" in log
        else ("INCOMPLETE" if "TASK INCOMPLETE" in log else "?")
    )
    # A hang is not a pass, and neither is a crash. The filesystem may well contain the right
    # artifacts at the moment we killed the process — that is not the same as the agent having
    # finished, and an agent that cannot terminate has not solved the task.
    passed = bool(scored) and not timed_out and exit_code == 0
    if timed_out:
        reasons = [f"timed out after {wall_s:.0f}s", *reasons]
    elif exit_code not in (0, None):
        reasons = [f"exited {exit_code}", *reasons]
    # 0-byte, non-hidden files left behind = placeholder artifacts.
    empty_files = 0
    if ws.exists():
        for p in ws.rglob("*"):
            if p.is_file() and not p.name.startswith(".") and "node_modules" not in p.parts:
                try:
                    if p.stat().st_size == 0:
                        empty_files += 1
                except OSError:
                    pass
    return {
        "id": case.id,
        "passed": passed,
        "verdict": verdict,
        "timed_out": timed_out,
        "exit_code": exit_code,
        # The honesty metric: the agent declared success the scorer cannot confirm. Note it can
        # only fire when a verdict was actually parsed — with `verdict == "?"` on 2 of 3 stored
        # cases, a `false_complete_rate` of 0.0 meant the PARSER failed, not that the agent was
        # honest. `unparsed_verdict_rate` in the aggregate now says which of the two it is.
        "false_complete": verdict == "COMPLETE" and not scored,
        "empty_files": empty_files,
        "hallucinated_cmd": bool(_HALLUCINATED.search(log)),
        "content_authored": "authored file content" in log,
        "wall_s": round(wall_s, 1),
        "fail_reasons": [] if passed else reasons,
    }


def _aggregate(results: list[dict]) -> dict:
    n = len(results) or 1
    return {
        "cases": len(results),
        "pass_rate": round(sum(r["passed"] for r in results) / n, 3),
        "false_complete_rate": round(sum(r["false_complete"] for r in results) / n, 3),
        "empty_file_rate": round(sum(bool(r["empty_files"]) for r in results) / n, 3),
        "hallucination_rate": round(sum(r["hallucinated_cmd"] for r in results) / n, 3),
        "content_authored_rate": round(sum(r["content_authored"] for r in results) / n, 3),
        # A run that hangs and a run whose verdict could not be parsed are both measurement
        # failures, and both used to be invisible: the first scored as a pass, the second
        # silently zeroed false_complete_rate. Neither is allowed to hide in an average again.
        "timeout_rate": round(sum(r["timed_out"] for r in results) / n, 3),
        "unparsed_verdict_rate": round(sum(r["verdict"] == "?" for r in results) / n, 3),
        "mean_wall_s": round(sum(r["wall_s"] for r in results) / n, 1),
    }


def _preflight() -> None:
    """Fail fast and self-describing. A reproducible run needs the binary + weights RESOLVABLE
    before we spawn N subprocesses that would each crash the same opaque way. A benchmark that
    depends on an unresolved external environment is an anecdote, not a measurement."""
    missing: list[str] = []
    if not LLAMA_SERVER_BIN.exists():
        missing.append(
            f"llama-server not found (resolved to {LLAMA_SERVER_BIN}).\n"
            f"      Fix ONE of: set SISTEMISTA_LLAMA_SERVER_BIN=<...>\\llama-server.exe ;"
            f" put llama-server on PATH ; or vendor it (with its DLLs) under {LLAMA_SERVER_BIN.parent}\\"
        )
    for label, m in (("NAV", NAV_MODEL), ("CODER", CODER_MODEL)):
        if not m.exists():
            missing.append(
                f"{label} weights missing: {m}\n      Fix: see workspace/models/README.md"
            )
    if missing:
        print("BENCHMARK ENVIRONMENT NOT READY — a reproducible run needs:", file=sys.stderr)
        for item in missing:
            print(f"  - {item}", file=sys.stderr)
        sys.exit(2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated case ids")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument(
        "--set",
        dest="set_baseline",
        action="store_true",
        help="store this run as the baseline to compare future runs against",
    )
    a = ap.parse_args()
    _preflight()

    only = {x.strip() for x in a.only.split(",") if x.strip()}
    cases = [c for c in CASES if not only or c.id in only]
    OUT.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    for c in cases:
        missing = [t for t in c.needs if not _have(t)]
        if missing:
            print(f"[{c.id}] SKIP (missing: {', '.join(missing)})", flush=True)
            continue
        ws = OUT / "workspaces" / c.id
        subprocess.run(
            [sys.executable, "-c", f"import shutil; shutil.rmtree(r'{ws}', ignore_errors=True)"],
            check=False,
        )
        ws.mkdir(parents=True, exist_ok=True)
        log_path = OUT / f"{c.id}.log"
        # DETERMINISTIC: seed pinned + greedy → a delta between commits is a real effect.
        # ORACLE OFF: the benchmark measures the SELF-CONTAINED config — the owned 4B alone,
        # which is what ships and what runs on modest hardware (RFC-001). Depending on a borrowed
        # oracle server made the baseline a mix of configs (some cases hit the 4B, one crashed on
        # a connection reset to the oracle) — not reproducible, not comparable. The oracle stays
        # an optional escalation in production; a benchmark is not the place to measure it.
        # Per-case state root. Every process on this machine used to share `workspace/var`, so
        # the benchmark ran against the OPERATOR'S episodic memory — and `Orchestrator.run`
        # calls `clear_session_events()` on startup, so each case wiped the real event log and
        # left its own synthetic history behind, which then reached the next real run's planner
        # prompt. Isolating per case also means one case cannot teach the next one anything: at
        # n=3 a shared memory makes the cases non-independent samples.
        state_root = OUT / "state" / c.id
        subprocess.run(
            [
                sys.executable,
                "-c",
                f"import shutil; shutil.rmtree(r'{state_root}', ignore_errors=True)",
            ],
            check=False,
        )
        env = dict(
            os.environ,
            SISTEMISTA_CONFINE_ROOT=str(ws.resolve()),
            SISTEMISTA_VAR_DIR=str(state_root.resolve()),
            SISTEMISTA_DETERMINISTIC="1",
            SISTEMISTA_ORACLE="0",
        )
        t0 = time.time()
        timed_out = False
        exit_code: int | None = None
        try:
            with log_path.open("wb") as fh:
                proc = subprocess.run(
                    [sys.executable, "-u", "-m", "src.main", c.goal, "--workspace", str(ws)],
                    cwd=str(ROOT),
                    env=env,
                    stdout=fh,
                    stderr=fh,
                    timeout=a.timeout,
                    check=False,
                )
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            # Previously a bare `pass`: the flag was never set and `check=False` swallowed the
            # exit code, so scoring saw only the filesystem and a hang scored as a pass.
            timed_out = True
        m = _metrics_from_run(
            c, ws, _read(log_path), time.time() - t0, timed_out=timed_out, exit_code=exit_code
        )
        results.append(m)
        flag = "PASS" if m["passed"] else "FAIL"
        extra = []
        if m["false_complete"]:
            extra.append("FALSE-COMPLETE")
        if m["empty_files"]:
            extra.append(f"{m['empty_files']} empty")
        if m["hallucinated_cmd"]:
            extra.append("hallucinated-cmd")
        if m["content_authored"]:
            extra.append("content-authored")
        print(f"[{c.id}] {flag} ({m['verdict']}) {m['wall_s']}s  {' '.join(extra)}", flush=True)

    agg = _aggregate(results)
    report = {"aggregate": agg, "results": results}
    (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    baseline_path = OUT / "baseline.json"
    print("\n=== AGGREGATE ===")
    for k, v in agg.items():
        print(f"  {k:24} {v}")
    if a.set_baseline:
        baseline_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\n[baseline] stored → {baseline_path}")
    elif baseline_path.exists():
        base = json.loads(baseline_path.read_text(encoding="utf-8")).get("aggregate", {})
        print("\n=== DELTA vs baseline ===")
        for k in agg:
            if k in base and isinstance(agg[k], (int, float)):
                d = round(agg[k] - base[k], 3)
                arrow = "→" if d == 0 else ("↑" if d > 0 else "↓")
                print(f"  {k:24} {base[k]} → {agg[k]}  {arrow} {d:+}")
    print(f"\n[report] {OUT / 'report.json'}")


if __name__ == "__main__":
    main()
