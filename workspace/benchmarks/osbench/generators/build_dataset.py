"""
Build the full benchmark corpus.

Runs every registered family, de-duplicates, assigns ids, and materializes:
  osbench/linux|windows|macos/<domain>/<ID>.json   (one file per case, browsable)
  osbench/datasets/all_cases.jsonl                  (single machine-readable stream)
  osbench/datasets/index.json                       (id -> path + key fields)
  osbench/datasets/distribution.json                (counts by os/difficulty/domain/family)

Usage:
  python -m benchmarks.osbench.generators.build_dataset
  python -m benchmarks.osbench.generators.build_dataset --stats-only   # no file writes
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

# importing the family modules triggers their @register side effects
from . import (
    breadth,  # noqa: F401
    families,  # noqa: F401
    families2,  # noqa: F401
    families3,  # noqa: F401
    families4,  # noqa: F401
    families5,  # noqa: F401
)
from .engine import distribution, generate

ROOT = Path(__file__).resolve().parent.parent  # .../osbench
DATASETS = ROOT / "datasets"
OS_DIRS = {"linux": ROOT / "linux", "windows": ROOT / "windows", "macos": ROOT / "macos"}


def write_corpus(cases: list) -> dict:
    DATASETS.mkdir(exist_ok=True)
    # clean per-OS trees (idempotent regeneration)
    for d in OS_DIRS.values():
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)

    index = []
    jsonl = DATASETS / "all_cases.jsonl"
    with jsonl.open("w", encoding="utf-8") as stream:
        for c in cases:
            d = c.to_dict()
            stream.write(json.dumps(d, ensure_ascii=False) + "\n")
            dom_dir = OS_DIRS[c.os.value] / c.domain
            dom_dir.mkdir(parents=True, exist_ok=True)
            fp = dom_dir / f"{c.id}.json"
            fp.write_text(c.to_json(), encoding="utf-8")
            index.append(
                {
                    "id": c.id,
                    "os": c.os.value,
                    "domain": c.domain,
                    "difficulty": c.difficulty.value,
                    "golden": c.golden,
                    "title": c.title,
                    "path": str(fp.relative_to(ROOT)).replace("\\", "/"),
                }
            )
    (DATASETS / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    dist = distribution(cases)
    (DATASETS / "distribution.json").write_text(
        json.dumps(dist, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return dist


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats-only", action="store_true")
    args = ap.parse_args()

    cases = generate()
    dist = distribution(cases)
    if not args.stats_only:
        dist = write_corpus(cases)

    print(f"TOTAL cases: {dist['total']}   golden: {dist['golden']}")
    for os_name in ("linux", "windows", "macos"):
        n = dist["per_os"].get(os_name, 0)
        by_diff = dist["per_os_difficulty"].get(os_name, {})
        by_dom = dist["per_os_domain"].get(os_name, {})
        print(f"\n== {os_name.upper()}  ({n} cases, {len(by_dom)} domains) ==")
        order = ["easy", "medium", "hard", "expert", "principal"]
        print("   difficulty: " + "  ".join(f"{k}={by_diff.get(k, 0)}" for k in order))


if __name__ == "__main__":
    main()
