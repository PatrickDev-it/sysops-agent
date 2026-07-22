"""Aggregate the per-run event traces into the statistics a decision can be made from.

`suite_report.json` says WHETHER a task passed. The traces say WHY: which model was asked,
how often, how long it took, whether the prefix cache hit, whether the runtime overrode or
refused the model. This turns "the agent is slow" into "the oracle answers 3 times per task
at 20 t/s because its prefix cache never hits".

Usage:
    python -m benchmarks.trace_stats <label> [<label> ...]      # one block per arm
    python -m benchmarks.trace_stats oracle_on oracle_off       # A/B, with deltas
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict

from src.config import BENCHMARK_DIR as BENCH_DIR


def _load(label: str) -> tuple[dict, dict[str, list[dict]]]:
    d = BENCH_DIR / label
    report = (
        json.loads((d / "suite_report.json").read_text(encoding="utf-8"))
        if (d / "suite_report.json").exists()
        else {"results": []}
    )
    traces: dict[str, list[dict]] = {}
    tdir = d / "traces"
    if tdir.exists():
        for f in sorted(tdir.glob("*.calls.jsonl")):
            traces[f.name.split(".")[0]] = [
                json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()
            ]
    return report, traces


def _mean(xs: list[float]) -> float:
    return round(statistics.fmean(xs), 2) if xs else 0.0


def summarize(label: str) -> dict:
    report, traces = _load(label)
    results = {r["id"]: r for r in report.get("results", [])}

    by_role: dict[str, list[dict]] = defaultdict(list)
    by_template: dict[str, list[dict]] = defaultdict(list)
    blocks: list[dict] = []
    overrides: list[dict] = []
    gates: Counter = Counter()
    unverifiable = 0
    truncations = 0
    overflows = 0
    per_task: list[dict] = []

    for tid, events in traces.items():
        llm = [e for e in events if e["kind"] == "llm" and not e.get("context_overflow")]
        ex = [e for e in events if e["kind"] == "exec"]
        overflows += sum(1 for e in events if e.get("context_overflow"))
        truncations += sum(1 for e in events if e["kind"] == "truncation")
        unverifiable += sum(1 for e in events if e["kind"] == "unverifiable_step")
        for e in events:
            if e["kind"] == "coder_gate":
                gates[e["gate"] or "accepted"] += 1
        for e in llm:
            by_role[e["role"]].append(e)
            by_template[e["template"]].append(e)
        blocks += [e for e in ex if e.get("blocked")]
        overrides += [e for e in events if e["kind"] == "override"]
        r = results.get(tid, {})
        per_task.append(
            {
                "id": tid,
                "passed": r.get("passed"),
                "wall_s": r.get("wall_s"),
                "llm_calls": len(llm),
                "exec": len(ex),
                "blocked": sum(1 for e in ex if e.get("blocked")),
                "failed_exec": sum(
                    1 for e in ex if not e.get("blocked") and e.get("exit_code", 0) != 0
                ),
                "llm_ms": round(sum(e.get("latency_ms", 0) for e in llm)),
            }
        )

    def role_stats(evs: list[dict]) -> dict:
        # llama-server reports `prompt_n` = tokens actually PREFILLED and `cache_n` =
        # tokens reused from the slot's KV. The full prompt is their sum; dividing by
        # prompt_n alone yields ratios above 100%.
        reused = sum(e.get("cache_n", 0) for e in evs)
        prefilled = sum(e.get("prompt_n", 0) for e in evs)
        return {
            "calls": len(evs),
            "tok_prefilled": prefilled,
            "tok_reused": reused,
            "tok_out": sum(e.get("predicted_n", 0) for e in evs),
            "cache_hit_pct": round(100 * reused / max(1, reused + prefilled), 1),
            "decode_tps": _mean([e["decode_tps"] for e in evs if e.get("decode_tps")]),
            "latency_ms": _mean([e["latency_ms"] for e in evs if e.get("latency_ms")]),
            "total_s": round(sum(e.get("latency_ms", 0) for e in evs) / 1000, 1),
        }

    n = len(per_task) or 1
    return {
        "label": label,
        "tasks": len(per_task),
        "arr": report.get("arr"),
        "passed": report.get("passed"),
        "wall_s_mean": _mean([t["wall_s"] for t in per_task if t["wall_s"]]),
        "llm_calls_mean": round(sum(t["llm_calls"] for t in per_task) / n, 2),
        "exec_mean": round(sum(t["exec"] for t in per_task) / n, 2),
        "failed_exec_mean": round(sum(t["failed_exec"] for t in per_task) / n, 2),
        "confinement_blocks": len(blocks),
        "runtime_overrides": len(overrides),
        "context_overflows": overflows,
        "truncations": truncations,
        "unverifiable_steps": unverifiable,
        "coder_gates": dict(gates.most_common()),
        "coder_accept_pct": round(100 * gates.get("accepted", 0) / max(1, sum(gates.values())), 1),
        "by_role": {r: role_stats(e) for r, e in sorted(by_role.items())},
        "by_template": {t: role_stats(e) for t, e in sorted(by_template.items())},
        "block_reasons": sorted({b.get("reason", "?") for b in blocks}),
        "per_task": sorted(per_task, key=lambda t: t["id"]),
    }


def render(s: dict) -> str:
    L = [
        f"\n{'=' * 78}",
        f"ARM: {s['label']}   tasks={s['tasks']}  ARR={s['arr']}  ({s['passed']} passed)",
        "=" * 78,
    ]
    L.append(
        f"wall/task {s['wall_s_mean']}s | llm calls/task {s['llm_calls_mean']} | "
        f"exec/task {s['exec_mean']} | failed exec/task {s['failed_exec_mean']}"
    )
    L.append(
        f"confinement blocks {s['confinement_blocks']} | runtime overrides "
        f"{s['runtime_overrides']} | context overflows {s['context_overflows']} | "
        f"truncations {s['truncations']} | unverifiable steps {s['unverifiable_steps']}"
    )
    if s["block_reasons"]:
        for r in s["block_reasons"]:
            L.append(f"    blocked: {r}")
    if s["coder_gates"]:
        L.append(
            f"\ncoder proposals: {sum(s['coder_gates'].values())}  accepted "
            f"{s['coder_accept_pct']}%   (deterministic gates, no model)"
        )
        for gate, n in s["coder_gates"].items():
            L.append(f"    {'✔ accepted' if gate == 'accepted' else '✘ ' + gate:34} {n}")

    L.append(
        f"\n{'role':12} {'calls':>6} {'prefill':>8} {'reused':>8} {'out':>7} {'cache%':>7} "
        f"{'t/s':>7} {'ms/call':>8} {'tot_s':>7}"
    )
    L.append("-" * 78)
    for r, v in s["by_role"].items():
        L.append(
            f"{r:12} {v['calls']:>6} {v['tok_prefilled']:>8} {v['tok_reused']:>8} "
            f"{v['tok_out']:>7} {v['cache_hit_pct']:>7} {v['decode_tps']:>7} "
            f"{v['latency_ms']:>8} {v['total_s']:>7}"
        )

    L.append(f"\n{'template':30} {'calls':>6} {'cache%':>7} {'t/s':>7} {'ms/call':>8} {'tot_s':>7}")
    L.append("-" * 78)
    for t, v in s["by_template"].items():
        L.append(
            f"{t:30} {v['calls']:>6} {v['cache_hit_pct']:>7} {v['decode_tps']:>7} "
            f"{v['latency_ms']:>8} {v['total_s']:>7}"
        )
    return "\n".join(L)


def main(labels: list[str]) -> None:
    summaries = [summarize(x) for x in labels]
    for s in summaries:
        print(render(s))
        (BENCH_DIR / s["label"] / "trace_stats.json").write_text(
            json.dumps(s, indent=2), encoding="utf-8"
        )

    if len(summaries) == 2:
        a, b = summaries
        print(f"\n{'=' * 78}\nA/B  {a['label']}  vs  {b['label']}\n{'=' * 78}")
        for k in (
            "arr",
            "wall_s_mean",
            "llm_calls_mean",
            "exec_mean",
            "failed_exec_mean",
            "confinement_blocks",
        ):
            va, vb = a.get(k) or 0, b.get(k) or 0
            d = round(vb - va, 3)
            print(f"{k:22} {va:>10}  →{vb:>10}   Δ {d:+}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1:])
