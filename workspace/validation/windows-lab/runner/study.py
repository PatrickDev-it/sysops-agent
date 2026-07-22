"""Windows Validation Lab — the study runner (RFC-0005 vertical slice).

Runs osbench Windows cases ONE AT A TIME against the real dual-GGUF agent on GPU,
observes without helping, and for every case records the raw material needed to do
root-cause analysis on the agent's behaviour:

  - what the agent DID (verdict, executed commands, per-action stdout/stderr/exit),
  - whether it reached the goal (osbench state-based success_check — outcome, not text),
  - how it deviated from the case's expected_reasoning / expected_commands,
  - the failure ErrorClass(es), DERIVED from src.error_classifier (RFC-0005 §4 — the
    failure taxonomy has a single owner; we do not maintain a parallel Windows list),
  - first-time-fix / needed-recovery signals feeding FTFR and RAF (RFC-0005 §2).

Safety mirrors osbench/run.py: SAFE + refusal cases run by default; RECOVERABLE fixtures
that mutate state require --allow-mutating and run in an isolated per-case workspace;
DESTRUCTIVE cases are never executed — they are refusal tests.

Run (from workspace/, venv active):
    python validation/windows-lab/runner/study.py --limit 1            # smoke: 1 case
    python validation/windows-lab/runner/study.py                      # all Windows SAFE+refusal
    python validation/windows-lab/runner/study.py --difficulty easy --limit 20
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[3]        # workspace/
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from benchmarks.osbench.run import load_cases, AdapterResult          # noqa: E402
from benchmarks.osbench.adapters import LiveOrchestratorAdapter        # noqa: E402
from benchmarks.osbench.validators.checks import evaluate, RunContext, current_os  # noqa: E402
from src.error_classifier import classify, ErrorClass                  # noqa: E402

LAB = WORKSPACE / "validation" / "windows-lab"
FAILURE_DB = LAB / "failure-db"
REPORTS = LAB / "reports"


def _select(cases, args):
    out = [c for c in cases if c.os.value == "windows"]
    if args.golden:
        out = [c for c in out if c.golden]
    if args.difficulty:
        want = set(args.difficulty.split(","))
        out = [c for c in out if c.difficulty.value in want]
    if args.domain:
        want = set(args.domain.split(","))
        out = [c for c in out if c.domain in want]
    if not args.allow_mutating:
        # default: only SAFE + refusal cases — never mutate the real host
        out = [c for c in out if c.risk == "SAFE" or c.ground_truth.get("must_refuse")]
    out.sort(key=lambda c: (c.difficulty.rank, c.domain, c.id))
    if args.limit:
        out = out[: args.limit]
    return out


def _forbidden_hits(case, result: AdapterResult) -> list[str]:
    import re
    blob = "\n".join(result.commands) + "\n" + result.transcript
    hits = []
    for pat in case.forbidden_commands:
        try:
            if re.search(pat, blob, re.IGNORECASE):
                hits.append(pat)
        except re.error:
            continue
    return hits


def _error_classes(history: list[dict]) -> list[dict]:
    """Classify every failed action's output via the runtime error_classifier.
    This is the failure taxonomy — derived, one owner (RFC-0005 §4)."""
    out = []
    for h in history:
        if h.get("success"):
            continue
        output = "\n".join(x for x in (h.get("stdout", ""), h.get("stderr", "")) if x)
        cls = classify(output, h.get("exit_code", 1) or 1, h.get("command", ""))
        out.append({"command": h.get("command", ""), "exit_code": h.get("exit_code"),
                    "error_class": cls.value, "signal": output[-300:]})
    return out


def study_case(case, adapter: LiveOrchestratorAdapter, allow_host_probes: bool) -> dict:
    ws = Path(tempfile.mkdtemp(prefix=f"winlab_{case.id}_"))
    must_refuse = bool(case.ground_truth.get("must_refuse"))
    t0 = time.time()
    try:
        res = adapter.run(case.goal or case.title, ws, dict(case.ground_truth))
        rec = adapter.last_record or {}
        history = rec.get("history", []) or []

        ctx = RunContext(workspace=ws, os_name=current_os(), transcript=res.transcript,
                         executed_commands=res.commands, allow_host_probes=allow_host_probes)
        check = evaluate(case.success_check, ctx)

        resolved = (res.refused if must_refuse
                    else (check.ok and not check.skipped))
        forbidden = _forbidden_hits(case, res)
        errors = _error_classes(history)
        n_failed = sum(1 for h in history if not h.get("success"))
        needed_recovery = n_failed > 0
        first_time_fix = bool(resolved and not needed_recovery and not forbidden
                              and not adapter.last_error)

        # a "deviation" = anything a maintainer must study: not resolved, unsafe,
        # a crash, a required refusal that didn't happen, or resolved-but-messy.
        deviation = (not resolved) or bool(forbidden) or bool(adapter.last_error) \
            or (must_refuse and not res.refused) or needed_recovery

        return {
            "case": {
                "id": case.id, "title": case.title, "domain": case.domain,
                "difficulty": case.difficulty.value, "risk": case.risk,
                "golden": case.golden, "goal": case.goal or case.title,
                "must_refuse": must_refuse,
            },
            "expected": {
                "reasoning": case.expected_reasoning,
                "commands": case.expected_commands,
                "forbidden": case.forbidden_commands,
                "possible_mistakes": case.possible_mistakes,
                "success_criteria": case.success_criteria,
                "recovery_strategy": case.recovery_strategy,
                "ground_truth": case.ground_truth,
                "reference_solution": case.reference_solution,
            },
            "observed": {
                "verdict": rec.get("verdict", ""),
                "refused": res.refused,
                "resolved": resolved,
                "success_check": {"ok": check.ok, "skipped": check.skipped,
                                  "kind": check.kind, "detail": check.detail},
                "executed_commands": res.commands,
                "n_actions": len(history),
                "n_failed_actions": n_failed,
                "error_classes": errors,
                "forbidden_hits": forbidden,
                "crash": adapter.last_error,
                "wall_s": round(time.time() - t0, 1),
                "run_id": rec.get("run_id", ""),
                "note": rec.get("note", ""),
            },
            "metrics": {
                "first_time_fix": first_time_fix,
                "needed_recovery": needed_recovery,
                "resolved": resolved,
            },
            "deviation": deviation,
            # filled by the maintainer (Claude) during root-cause analysis:
            "study": {"root_cause": "", "secondary_causes": [], "components": [],
                      "confidence": None, "candidate_solutions": []},
        }
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--difficulty", default="")
    ap.add_argument("--domain", default="")
    ap.add_argument("--golden", action="store_true")
    ap.add_argument("--allow-mutating", action="store_true")
    ap.add_argument("--allow-host-probes", action="store_true", default=True,
                    help="permit read-only command_* probes against the live host")
    ap.add_argument("--label", default=time.strftime("%Y%m%d-%H%M%S"))
    args = ap.parse_args()

    FAILURE_DB.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)

    cases = _select(load_cases(), args)
    adapter = LiveOrchestratorAdapter()
    print(f"[windows-lab] {len(cases)} Windows cases  (mutating={args.allow_mutating})  "
          f"label={args.label}\n", flush=True)

    records = []
    index_path = REPORTS / f"study-{args.label}.jsonl"
    with index_path.open("w", encoding="utf-8") as idx:
        for i, case in enumerate(cases, 1):
            print(f"[{i}/{len(cases)}] {case.id}  {case.domain}/{case.difficulty.value}  "
                  f":: {(case.goal or case.title)[:70]}", flush=True)
            rec = study_case(case, adapter, args.allow_host_probes)
            records.append(rec)
            idx.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            idx.flush()
            o, m = rec["observed"], rec["metrics"]
            tag = "FTF" if m["first_time_fix"] else ("OK" if m["resolved"] else "DEVIATION")
            ec = ",".join(sorted({e["error_class"] for e in o["error_classes"]})) or "-"
            print(f"      -> {tag}  verdict={o['verdict']}  resolved={m['resolved']}  "
                  f"recovery={m['needed_recovery']}  err={ec}  {o['wall_s']}s", flush=True)
            if rec["deviation"]:
                (FAILURE_DB / f"{case.id}.json").write_text(
                    json.dumps(rec, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    _write_summary(records, args.label)


def _write_summary(records: list[dict], label: str) -> None:
    n = len(records) or 1
    resolved = sum(1 for r in records if r["metrics"]["resolved"])
    ftf = sum(1 for r in records if r["metrics"]["first_time_fix"])
    first_try = sum(1 for r in records
                    if r["metrics"]["resolved"] and not r["metrics"]["needed_recovery"])
    devs = [r for r in records if r["deviation"]]
    # failure taxonomy histogram, indexed by ErrorClass (derived)
    hist: dict[str, int] = {}
    for r in records:
        for e in r["observed"]["error_classes"]:
            hist[e["error_class"]] = hist.get(e["error_class"], 0) + 1
    p_first = first_try / n
    p_final = resolved / n
    raf = (p_final / p_first) if p_first > 0 else None

    summary = {
        "label": label, "n_cases": len(records),
        "resolved": resolved, "arr": round(p_final, 4),
        "ftfr": round(ftf / n, 4),               # First-Time Fix Rate (RFC-0005 §2)
        "raf": round(raf, 3) if raf else None,   # Recovery Amplification Factor
        "deviations": len(devs),
        "failure_taxonomy": dict(sorted(hist.items(), key=lambda kv: -kv[1])),
        "deviation_ids": [r["case"]["id"] for r in devs],
    }
    (REPORTS / f"summary-{label}.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n" + "=" * 60)
    print(f"ARR={summary['arr']:.1%}  FTFR={summary['ftfr']:.1%}  "
          f"RAF={summary['raf']}  deviations={summary['deviations']}/{len(records)}")
    print(f"failure taxonomy: {summary['failure_taxonomy']}")
    print(f"[summary] {REPORTS / f'summary-{label}.json'}")
    print(f"[failures] {FAILURE_DB}")


if __name__ == "__main__":
    main()
