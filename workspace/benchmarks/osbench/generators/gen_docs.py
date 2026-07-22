"""
Generate the data-derived dataset docs from the materialized corpus:
  datasets/coverage-matrix.md       (domain x OS x difficulty counts)
  datasets/difficulty-distribution.md

Run AFTER build_dataset. Keeps these docs honest — they are computed from
distribution.json, never hand-edited (so they can't drift from the data).
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASETS = ROOT / "datasets"
DIFF_ORDER = ["easy", "medium", "hard", "expert", "principal"]
MIN_DIFF = {"easy": 25, "medium": 50, "hard": 150, "expert": 200, "principal": 75}


def _load():
    dist = json.loads((DATASETS / "distribution.json").read_text(encoding="utf-8"))
    index = json.loads((DATASETS / "index.json").read_text(encoding="utf-8"))
    return dist, index


def coverage_matrix(dist, index) -> str:
    # domain -> os -> difficulty -> count
    grid: dict = {}
    for row in index:
        grid.setdefault(row["domain"], {}).setdefault(row["os"], {}).setdefault(
            row["difficulty"], 0
        )
        grid[row["domain"]][row["os"]][row["difficulty"]] += 1

    lines = [
        "# Coverage matrix",
        "",
        "_Generated from `datasets/distribution.json` + `index.json`. Do not hand-edit._",
        f"\nTotal cases: **{dist['total']}** · golden: **{dist['golden']}**",
        "",
        "Counts of benchmark cases per **domain × OS** (all difficulty tiers combined).",
        "",
        "| Domain | Linux | Windows | macOS | Total |",
        "|---|---:|---:|---:|---:|",
    ]
    for domain in sorted(grid):
        row = grid[domain]
        linux_total = sum(row.get("linux", {}).values())
        w = sum(row.get("windows", {}).values())
        m = sum(row.get("macos", {}).values())
        lines.append(f"| {domain} | {linux_total} | {w} | {m} | {linux_total + w + m} |")
    tot = dist["per_os"]
    lines.append(
        f"| **TOTAL** | **{tot.get('linux', 0)}** | **{tot.get('windows', 0)}** "
        f"| **{tot.get('macos', 0)}** | **{dist['total']}** |"
    )

    lines += [
        "",
        "## Domain × difficulty (all OS)",
        "",
        "| Domain | " + " | ".join(DIFF_ORDER) + " |",
        "|---|" + "---:|" * len(DIFF_ORDER),
    ]
    dom_diff: dict = {}
    for row in index:
        dom_diff.setdefault(row["domain"], {}).setdefault(row["difficulty"], 0)
        dom_diff[row["domain"]][row["difficulty"]] += 1
    for domain in sorted(dom_diff):
        counts = dom_diff[domain]
        lines.append(
            f"| {domain} | " + " | ".join(str(counts.get(d, 0)) for d in DIFF_ORDER) + " |"
        )
    return "\n".join(lines) + "\n"


def difficulty_distribution(dist) -> str:
    lines = [
        "# Difficulty distribution",
        "",
        "_Generated from `datasets/distribution.json`. Do not hand-edit._",
        "",
        "Per-OS minimum floors: " + ", ".join(f"{k} ≥ {v}" for k, v in MIN_DIFF.items()) + ".",
        "",
        "| OS | " + " | ".join(DIFF_ORDER) + " | Total | Meets floors |",
        "|---|" + "---:|" * (len(DIFF_ORDER) + 1) + ":--:|",
    ]
    for os_name in ("linux", "windows", "macos"):
        d = dist["per_os_difficulty"].get(os_name, {})
        total = dist["per_os"].get(os_name, 0)
        ok = all(d.get(k, 0) >= v for k, v in MIN_DIFF.items()) and total >= 500
        cells = " | ".join(str(d.get(k, 0)) for k in DIFF_ORDER)
        lines.append(f"| {os_name} | {cells} | {total} | {'✅' if ok else '❌'} |")

    lines += [
        "",
        "## Rationale",
        "",
        "The distribution is an **inverted pyramid** weighted toward `hard`/`expert`: a",
        "benchmark for a *Systems Engineer* must concentrate mass where real on-call",
        "difficulty lives — multi-signal diagnosis and compound faults — not on trivial",
        "one-liners. `easy` cases exist to anchor the low end (read-only diagnostics);",
        "`principal` cases are compound, cross-domain incidents requiring judgement under",
        "constraint. Budgets (time, tokens) scale monotonically with difficulty so the",
        "efficiency metrics are calibrated per tier.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    dist, index = _load()
    (DATASETS / "coverage-matrix.md").write_text(coverage_matrix(dist, index), encoding="utf-8")
    (DATASETS / "difficulty-distribution.md").write_text(
        difficulty_distribution(dist), encoding="utf-8"
    )
    print("wrote datasets/coverage-matrix.md and datasets/difficulty-distribution.md")


if __name__ == "__main__":
    main()
