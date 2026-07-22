"""
ARR Aggregator (M0/F0).

Reads the per-run telemetry JSON records under validation/telemetry/ and derives
the quantitative baseline metrics needed to empirically test the v2 architecture
thesis BEFORE committing to it (see brain/architecture-next/telemetry.md).

Metrics computed from EXISTING telemetry:
  - ARR (Autonomous Resolution Rate): COMPLETE / (COMPLETE + INCOMPLETE)
      * REFUSED is reported separately: refusing a destructive goal is a CORRECT outcome,
        so it must not be counted as a failure.
  - ARR by distinct goal (dedup: last verdict per goal string, by timestamp)
  - steps/task     : len(history) mean/median
  - latency/task   : sum(action.duration) mean/median  [seconds]
  - action error rate: fraction of history actions with success==False or exit_code!=0
  - parse-error signal: proxy scan of `note`/history for supervisor parse-error markers

Metrics NOT available from current telemetry (require the unified v2 schema — see
telemetry_schema.py — and fresh instrumented runs):
  - tokens/task
  - true per-decision parse-error rate
  - per-decision latency (model call vs deterministic)

Usage:
  python -m benchmarks.arr_aggregator                 # prints markdown summary
  python -m benchmarks.arr_aggregator --json out.json # also writes machine-readable metrics
"""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.config import TELEMETRY_DIR

# Markers that indicate the supervisor produced unparseable JSON (Issue #8 / parse-error).
_PARSE_ERROR_MARKERS = (
    "parse error",
    "parse_error",
    "malformed",
    "json decode",
    "jsondecode",
    "invalid json",
    "thinking block",
    "leaked",
)


@dataclass
class RunMetrics:
    run_id: str
    goal: str
    verdict: str
    ts: str
    n_steps: int
    latency_s: float
    n_actions: int
    n_action_errors: int
    parse_error_signal: bool
    os_name: str = ""


@dataclass
class Baseline:
    n_runs: int = 0
    verdicts: dict = field(default_factory=dict)
    arr_all: float = 0.0  # COMPLETE / (COMPLETE+INCOMPLETE)
    arr_by_goal: float = 0.0  # dedup by goal, last verdict
    n_distinct_goals: int = 0
    steps_mean: float = 0.0
    steps_median: float = 0.0
    latency_mean_s: float = 0.0
    latency_median_s: float = 0.0
    action_error_rate: float = 0.0
    parse_error_run_rate: float = 0.0  # PROXY (note/history scan), not the true per-decision rate
    tokens_per_task: str = "N/A — not captured pre-v2 schema (see telemetry_schema.py)"
    parse_error_true_rate: str = "N/A — requires instrumented runs (v2 schema)"


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _parse_error_signal(rec: dict) -> bool:
    blob = (rec.get("note", "") or "").lower()
    for h in rec.get("history", []) or []:
        if isinstance(h, dict):
            blob += " " + str(h.get("stderr", "")).lower()
    return any(m in blob for m in _PARSE_ERROR_MARKERS)


def extract(rec: dict, path: Path) -> RunMetrics:
    hist = rec.get("history", []) or []
    n_actions = len(hist)
    latency = 0.0
    n_err = 0
    for h in hist:
        if not isinstance(h, dict):
            continue
        try:
            latency += float(h.get("duration", 0) or 0)
        except (TypeError, ValueError):
            pass
        if h.get("success") is False or (h.get("exit_code") not in (0, None)):
            n_err += 1
    env = rec.get("environment", {}) or {}
    return RunMetrics(
        run_id=rec.get("run_id", path.stem),
        goal=(rec.get("goal", "") or "").strip(),
        verdict=(rec.get("verdict", "?") or "?").upper(),
        ts=rec.get("ts", ""),
        n_steps=n_actions,  # one history entry per executed action/step
        latency_s=round(latency, 3),
        n_actions=n_actions,
        n_action_errors=n_err,
        parse_error_signal=_parse_error_signal(rec),
        os_name=env.get("os_name", ""),
    )


def aggregate(runs: list[RunMetrics]) -> Baseline:
    b = Baseline()
    b.n_runs = len(runs)
    if not runs:
        return b

    verdicts: dict[str, int] = {}
    for r in runs:
        verdicts[r.verdict] = verdicts.get(r.verdict, 0) + 1
    b.verdicts = verdicts

    complete = verdicts.get("COMPLETE", 0)
    incomplete = verdicts.get("INCOMPLETE", 0)
    denom = complete + incomplete
    b.arr_all = round(complete / denom, 4) if denom else 0.0

    # ARR by distinct goal: last verdict per goal (by ts string, ISO-sortable)
    latest: dict[str, RunMetrics] = {}
    for r in sorted(runs, key=lambda x: x.ts):
        if r.goal:
            latest[r.goal] = r
    goal_runs = list(latest.values())
    b.n_distinct_goals = len(goal_runs)
    gc = sum(1 for r in goal_runs if r.verdict == "COMPLETE")
    gi = sum(1 for r in goal_runs if r.verdict == "INCOMPLETE")
    b.arr_by_goal = round(gc / (gc + gi), 4) if (gc + gi) else 0.0

    steps = [r.n_steps for r in runs]
    lat = [r.latency_s for r in runs]
    b.steps_mean = round(statistics.mean(steps), 2)
    b.steps_median = round(statistics.median(steps), 2)
    b.latency_mean_s = round(statistics.mean(lat), 2)
    b.latency_median_s = round(statistics.median(lat), 2)

    tot_actions = sum(r.n_actions for r in runs)
    tot_errors = sum(r.n_action_errors for r in runs)
    b.action_error_rate = round(tot_errors / tot_actions, 4) if tot_actions else 0.0
    b.parse_error_run_rate = round(sum(1 for r in runs if r.parse_error_signal) / len(runs), 4)
    return b


def to_markdown(b: Baseline) -> str:
    v = b.verdicts
    lines = [
        "| Metrica | Valore | Note |",
        "|---|---|---|",
        f"| Run analizzati | {b.n_runs} | file telemetry validi |",
        f"| Verdetti | COMPLETE={v.get('COMPLETE', 0)} · INCOMPLETE={v.get('INCOMPLETE', 0)} · REFUSED={v.get('REFUSED', 0)} | REFUSED = esito corretto su goal distruttivo |",
        f"| **ARR (tutti i run)** | **{b.arr_all:.1%}** | COMPLETE/(COMPLETE+INCOMPLETE) |",
        f"| **ARR (per goal distinto)** | **{b.arr_by_goal:.1%}** | {b.n_distinct_goals} goal distinti, ultimo verdetto |",
        f"| Steps/task (media / mediana) | {b.steps_mean} / {b.steps_median} | azioni per run |",
        f"| **Latency/task (media / mediana)** | **{b.latency_mean_s}s / {b.latency_median_s}s** | somma durate azioni |",
        f"| Action error rate | {b.action_error_rate:.1%} | azioni con exit≠0 o success=False |",
        f"| Parse-error rate (proxy) | {b.parse_error_run_rate:.1%} | scan note/stderr — non la vera per-decisione |",
        f"| Tokens/task | {b.tokens_per_task} | |",
        f"| Parse-error (vero, per-decisione) | {b.parse_error_true_rate} | |",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(TELEMETRY_DIR))
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    tdir = Path(args.dir)
    runs: list[RunMetrics] = []
    for p in sorted(tdir.glob("run_*.json")):
        rec = _load(p)
        if rec is None:
            continue
        runs.append(extract(rec, p))

    b = aggregate(runs)
    print("# Baseline v1 — ARR Aggregator\n")
    print(to_markdown(b))

    if args.json:
        out = {"baseline": asdict(b), "runs": [asdict(r) for r in runs]}
        Path(args.json).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n[written] {args.json}")


if __name__ == "__main__":
    main()
