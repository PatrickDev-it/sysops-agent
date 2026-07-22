"""Paired A/B analysis across seeds — the only honest way to read this benchmark.

Why this exists. Two control runs, both with the mechanism DISABLED at runtime, differing only
in whether the plan grammar exposed an unused field, scored 32/48 and 28/48. A four-task swing
from a change that does nothing at runtime. Meanwhile the effect under test was three tasks.

A fixed seed pins the RNG; it does not pin the *sample*. Any edit to a prompt or a grammar
reshuffles which tokens are sampled, which plan is produced, and which tasks pass. So a single
seeded run is one draw, and the difference between two single draws is not an effect size.

This computes, per task, the paired outcome across seeds:

    concordant  the arms agree on this task at every seed  -> carries no information
    discordant  the arms disagree                          -> the only evidence there is

and reports McNemar's exact test on the discordant pairs, plus the run-to-run spread of each
arm. With two seeds and 48 tasks the resolution is coarse; the script prints the smallest
effect the design can distinguish from noise, so nobody quotes a delta the data cannot support.

Usage:
    python -m benchmarks.ab_paired --off cap_off2,cap_off_s43 --on cap_on2,cap_on_s43
"""

from __future__ import annotations

import argparse
import json
import math
import statistics

from src.config import BENCHMARK_DIR as BENCH


def _outcomes(label: str) -> dict[str, bool]:
    rep = json.loads((BENCH / label / "suite_report.json").read_text(encoding="utf-8"))
    return {r["id"]: bool(r["passed"]) for r in rep["results"]}


def _binom_two_sided(b: int, c: int) -> float:
    """McNemar exact: probability of a split at least this extreme under H0 (p = 1/2)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2**n)
    return min(1.0, 2 * tail)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--off", required=True, help="comma-separated control labels, one per seed")
    ap.add_argument("--on", required=True, help="comma-separated treatment labels, same seeds")
    a = ap.parse_args()
    off_labels = [x.strip() for x in a.off.split(",") if x.strip()]
    on_labels = [x.strip() for x in a.on.split(",") if x.strip()]
    if len(off_labels) != len(on_labels):
        raise SystemExit("the arms must be paired seed by seed")

    offs = [_outcomes(x) for x in off_labels]
    ons = [_outcomes(x) for x in on_labels]
    tasks = sorted(set(offs[0]) & set(ons[0]))
    n_seeds = len(offs)

    print(f"seeds: {n_seeds}   tasks: {len(tasks)}\n")
    print(f"{'arm':10} " + " ".join(f"{label:>14}" for label in off_labels + on_labels))
    off_arr = [sum(o[t] for t in tasks) for o in offs]
    on_arr = [sum(o[t] for t in tasks) for o in ons]
    print(f"{'passed':10} " + " ".join(f"{v:>14}" for v in off_arr + on_arr))

    def spread(xs: list[int]) -> str:
        if len(xs) < 2:
            return "n/a (one seed)"
        return f"{min(xs)}-{max(xs)}  (sd {statistics.stdev(xs):.1f})"

    print(f"\nrun-to-run spread, control  : {spread(off_arr)}")
    print(f"run-to-run spread, treatment: {spread(on_arr)}")

    # Pool the seeds: a task counts as passing in an arm if it passed at every seed.
    # Anything less is not a property of the arm; it is a property of the draw.
    b = c = concordant = unstable = 0
    flips = []
    for t in tasks:
        o = [x[t] for x in offs]
        n = [x[t] for x in ons]
        if len(set(o)) > 1 or len(set(n)) > 1:
            unstable += 1
            continue
        o0, n0 = o[0], n[0]
        if o0 == n0:
            concordant += 1
        elif o0 and not n0:
            b += 1
            flips.append((t, "regressed"))
        else:
            c += 1
            flips.append((t, "recovered"))

    print(
        f"\nstable across seeds: {concordant + b + c}/{len(tasks)}   "
        f"unstable (seed-dependent): {unstable}"
    )
    print(f"  concordant (no information): {concordant}")
    print(f"  regressed  (control passes, treatment fails): {b}")
    print(f"  recovered  (control fails, treatment passes): {c}")
    p = _binom_two_sided(b, c)
    print(f"\nMcNemar exact on {b + c} discordant pairs: p = {p:.3f}")
    verdict = (
        "no evidence of an effect"
        if p > 0.05
        else ("treatment HELPS" if c > b else "treatment HURTS")
    )
    print(f"verdict: {verdict}")
    if unstable:
        print(
            f"\nCAUTION: {unstable} tasks changed outcome between seeds within a single arm. "
            f"The design cannot resolve an effect smaller than that."
        )
    for t, kind in sorted(flips):
        print(f"    {t}: {kind}")


if __name__ == "__main__":
    main()
