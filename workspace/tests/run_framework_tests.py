"""
Multi-framework init test suite.

Runs Sistemista against each framework goal in its own fresh workspace.
Prints a summary table at the end: PASS / FAIL + reason.

Usage (from repo root, inside .venv):
  python -m tests.run_framework_tests
or:
  python tests/run_framework_tests.py
"""

import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
WORKSPACE_BASE = ROOT / "_sandbox"

FRAMEWORKS = [
    ("svelte", "Initialize a SvelteKit project"),
    ("angular", "Initialize an Angular project"),
    ("vite", "Initialize a Vite project"),
    ("bun", "Initialize a Bun project"),
    ("vue", "Initialize a Vue project"),
    ("rust", "Initialize a Rust project with cargo"),
    ("python", "Initialize a Python project"),
]


def _clean_workspace(ws: Path):
    if ws.exists():
        shutil.rmtree(ws, ignore_errors=True)
    ws.mkdir(parents=True, exist_ok=True)


def _has_project(ws: Path, fw: str) -> tuple[bool, str]:
    """Lightweight check matching observer._heuristic_judge logic."""
    checks = {
        "svelte": [ws / "svelte.config.js", ws / "svelte.config.ts"],
        "angular": [ws / "angular.json"],
        "vite": [ws / "vite.config.ts", ws / "vite.config.js"],
        "bun": [ws / "bun.lockb", ws / "bun.lock"],
        "vue": [ws / "src" / "App.vue"],
        "rust": [ws / "Cargo.toml"],
        "python": [ws / "pyproject.toml", ws / "setup.py", ws / "requirements.txt"],
    }
    candidates = checks.get(fw, [])
    for p in candidates:
        if p.exists():
            return True, str(p.relative_to(ws))
    # JS frameworks also need package.json
    if fw in ("svelte", "angular", "vite", "bun", "vue"):
        if not (ws / "package.json").exists():
            return False, "package.json missing"
    return False, f"none of {[str(c.relative_to(ws)) for c in candidates]} found"


def run_one(fw: str, goal: str) -> tuple[bool, str, float]:
    ws = WORKSPACE_BASE / fw
    _clean_workspace(ws)
    cmd = [
        sys.executable,
        "-m",
        "src.main",
        goal,
        "--workspace",
        str(ws),
    ]
    print(f"\n{'=' * 60}")
    print(f"  TEST: {fw.upper()}  |  goal: {goal}")
    print(f"  workspace: {ws}")
    print(f"{'=' * 60}")
    t0 = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            timeout=300,  # 5 min per framework
            text=True,
            capture_output=False,  # let output stream to terminal
        )
        elapsed = time.time() - t0
        ok, reason = _has_project(ws, fw)
        if ok:
            return True, reason, elapsed
        return False, f"exit {result.returncode}: {reason}", elapsed
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        return False, "TIMEOUT after 300s", elapsed
    except Exception as e:
        elapsed = time.time() - t0
        return False, str(e), elapsed


def main():
    results = []
    for fw, goal in FRAMEWORKS:
        ok, reason, elapsed = run_one(fw, goal)
        results.append((fw, ok, reason, elapsed))

    print("\n\n" + "=" * 70)
    print("  RESULTS")
    print("=" * 70)
    for fw, ok, reason, elapsed in results:
        status = "PASS ✓" if ok else "FAIL ✗"
        print(f"  {status:8s}  {fw:<10s}  {elapsed:5.0f}s  {reason}")
    print("=" * 70)
    failed = [fw for fw, ok, _, _ in results if not ok]
    if failed:
        print(f"\n  Failed: {', '.join(failed)}")
        sys.exit(1)
    else:
        print("\n  All frameworks initialized successfully.")


if __name__ == "__main__":
    main()
