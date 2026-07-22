"""
Report generation: turn a `Scorecard` (or several, for a competitor comparison) into
a Markdown + JSON report under reports/.

Two entry points:
  - write_report(scorecard, label)        : single-agent scorecard
  - write_comparison(scorecards_by_agent) : side-by-side leaderboard across agents

INTEGRITY RULE, enforced here and not merely documented:
a scorecard produced by an adapter that executes nothing is a STUB, and must be legible as
one at a glance — in its filename, its title, and its JSON. A leaderboard may only be built
from scorecards that were actually executed.

This exists because it once did not. `reports/leaderboard.json` compared four agents; three
of them (`claude-code`, `codex-cli`, `openhands`) appear in no `.py` file in this repository
and were never run. Seven of eleven metrics were identical to sixteen significant digits,
and `claude-code.overall` was exactly `sistemista.overall + 0.01`. The file is preserved as
evidence in `_attic/osbench-synthetic-leaderboard/`, with the arithmetic.

A metric that asserts a capability without checking it is worse than an absent metric: a
reviewer reads it and stops looking. That is the same corollary this tree already wrote about
dead code that claims a guarantee — applied one line down, to the numbers.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .metrics import METRIC_NAMES, Scorecard

REPORTS = Path(__file__).resolve().parent.parent / "reports"


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def _bar(x: float, width: int = 20) -> str:
    n = round(x * width)
    return "█" * n + "·" * (width - n)


_STUB_BANNER = (
    "> **THIS IS NOT A MEASUREMENT.** It was produced by the `{adapter}` adapter, which "
    "executes nothing. Every number below scores a stub transcript, not an agent. Run with "
    "`--adapter live` to measure the agent."
)


def write_report(card: Scorecard, label: str) -> Path:
    REPORTS.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stub = not card.executed
    title = f"# osbench scorecard — {label}" + ("  [STUB — NOT A MEASUREMENT]" if stub else "")
    lines = [
        title,
        f"_generated {ts} · {card.n_cases} cases · {card.n_runs} runs · "
        f"adapter `{card.adapter}` · executed: {card.executed}_",
        "",
    ]
    if stub:
        lines += [_STUB_BANNER.format(adapter=card.adapter), ""]
    lines += [
        f"## Overall: **{_pct(card.overall)}**"
        + ("  _(of a stub, not of the agent)_" if stub else f"  _(n={card.n_cases} cases)_"),
        "",
        "## Metrics",
        "",
        "| Metric | Score | |",
        "|---|---:|:--|",
    ]
    for m in METRIC_NAMES:
        v = card.metrics.get(m, 0.0)
        lines.append(f"| {m.replace('_', ' ')} | {_pct(v)} | `{_bar(v)}` |")

    lines += [
        "",
        "## By difficulty",
        "",
        "| Difficulty | ARR | Safety | Reasoning | Overall-ish |",
        "|---|---:|---:|---:|---:|",
    ]
    for diff in ("easy", "medium", "hard", "expert", "principal"):
        d = card.by_difficulty.get(diff)
        if not d:
            continue
        lines.append(
            f"| {diff} | {_pct(d['autonomous_resolution_rate'])} | {_pct(d['safety'])} "
            f"| {_pct(d['reasoning_quality'])} | {_pct(_row_overall(d))} |"
        )

    lines += ["", "## By OS", "", "| OS | ARR | Safety | Recovery |", "|---|---:|---:|---:|"]
    for os_name in ("linux", "windows", "macos"):
        d = card.by_os.get(os_name)
        if not d:
            continue
        lines.append(
            f"| {os_name} | {_pct(d['autonomous_resolution_rate'])} | {_pct(d['safety'])} "
            f"| {_pct(d['recovery_capability'])} |"
        )

    lines += ["", "## Weakest domains (by ARR)", "", "| Domain | ARR | Safety |", "|---|---:|---:|"]
    ranked = sorted(
        card.by_domain.items(), key=lambda kv: kv[1].get("autonomous_resolution_rate", 0)
    )
    for dom, d in ranked[:15]:
        lines.append(f"| {dom} | {_pct(d['autonomous_resolution_rate'])} | {_pct(d['safety'])} |")

    md = REPORTS / f"scorecard_{_slug(label)}.md"
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    js = REPORTS / f"scorecard_{_slug(label)}.json"
    js.write_text(
        json.dumps(
            {
                "label": label,
                "generated": ts,
                "overall": card.overall,
                "n_cases": card.n_cases,
                "n_runs": card.n_runs,
                "metrics": card.metrics,
                "by_difficulty": card.by_difficulty,
                "by_os": card.by_os,
                "by_domain": card.by_domain,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return md


class FabricatedComparison(RuntimeError):
    """Raised when a leaderboard would be built from scorecards nobody produced by running."""


def write_comparison(cards: dict[str, Scorecard]) -> Path:
    # The guard that was missing. A comparison across agents is the single most quotable
    # artifact this harness emits, and it was the one with no provenance check at all.
    stubs = sorted(a for a, c in cards.items() if not c.executed)
    if stubs:
        raise FabricatedComparison(
            f"refusing to write a leaderboard: {stubs} were not executed "
            f"(adapters: {[cards[a].adapter for a in stubs]}). A comparison built from stubs "
            f"is a fabrication, not a benchmark. Run each agent with an executing adapter."
        )
    if len(cards) < 2:
        raise FabricatedComparison("a leaderboard needs at least two executed agents")

    REPORTS.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    agents = list(cards.keys())
    n_cases = {c.n_cases for c in cards.values()}
    if len(n_cases) != 1:
        raise FabricatedComparison(f"agents scored on different case counts: {sorted(n_cases)}")
    lines = [
        "# osbench leaderboard — competitor comparison",
        f"_generated {ts} · n={n_cases.pop()} cases · adapters: "
        + ", ".join(f"{a}=`{cards[a].adapter}`" for a in agents)
        + "_",
        "",
        "## Overall",
        "",
        "| Agent | Overall | ARR | Safety | Reasoning | Recovery | Reliability |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    ranked = sorted(agents, key=lambda a: cards[a].overall, reverse=True)
    for a in ranked:
        m = cards[a].metrics
        lines.append(
            f"| {a} | **{_pct(cards[a].overall)}** | {_pct(m['autonomous_resolution_rate'])} "
            f"| {_pct(m['safety'])} | {_pct(m['reasoning_quality'])} "
            f"| {_pct(m['recovery_capability'])} | {_pct(m['reliability'])} |"
        )

    lines += [
        "",
        "## Full metric matrix",
        "",
        "| Metric | " + " | ".join(ranked) + " |",
        "|---|" + "---:|" * len(ranked),
    ]
    for metric in METRIC_NAMES:
        row = [f"{_pct(cards[a].metrics.get(metric, 0))}" for a in ranked]
        lines.append(f"| {metric.replace('_', ' ')} | " + " | ".join(row) + " |")

    md = REPORTS / "leaderboard.md"
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (REPORTS / "leaderboard.json").write_text(
        json.dumps(
            {
                "generated": ts,
                "agents": {
                    a: {"overall": cards[a].overall, "metrics": cards[a].metrics} for a in ranked
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return md


def _row_overall(d: dict) -> float:
    from .metrics import DEFAULT_WEIGHTS

    return sum(DEFAULT_WEIGHTS[m] * d.get(m, 0.0) for m in METRIC_NAMES)


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s.lower()).strip("_")
