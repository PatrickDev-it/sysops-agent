"""Framework scaffolding stress suite — the table stakes.

Scaffolding a classic framework is not what Sistemista is FOR. Its reason to exist is the thing
a human cannot easily dig out: a wheel that will not build, a resolver dead-end, a version
conflict three layers down. But an agent that cannot do the boring thing has not earned the
right to be trusted with the hard one, and every scaffold exercises the whole spine at once —
plan, ground, author, run an interactive wizard, verify.

Each case is scored by the FILESYSTEM, never by the agent's own verdict:

    manifest      a file the ecosystem's own tooling creates, present and non-empty
    at_root       that file sits in the workspace root, not one level down
    entry         at least one source/entry artifact exists
    build         optional: a build/dist directory, when the case asks for one

`verdict` is recorded next to the outcome so a run that reports COMPLETE on an empty tree is
visible as exactly that, rather than counted as a pass.

Usage:
    python -m benchmarks.stress_frameworks --only react,vue --timeout 480
    python -m benchmarks.stress_frameworks              # all of them
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from src.config import ROOT, TELEMETRY_DIR

OUT = ROOT / "validation" / "stress"


@dataclass(frozen=True)
class Case:
    id: str
    goal: str
    manifest: str  # created by the ecosystem's own tooling
    entry_globs: tuple[str, ...] = ()  # any one of these must exist
    needs: tuple[str, ...] = ()  # executables that must be on PATH to attempt the case
    build_dir: str = ""  # optional, checked only when non-empty


CASES: tuple[Case, ...] = (
    Case(
        "react",
        "Inizializza in questo workspace un progetto React con Vite in TypeScript, "
        "in modo non interattivo. Installa le dipendenze.",
        "package.json",
        ("src/main.tsx", "src/main.jsx", "index.html"),
        ("npm",),
    ),
    Case(
        "vue",
        "Inizializza in questo workspace un progetto Vue in modo non interattivo. "
        "Installa le dipendenze.",
        "package.json",
        ("src/main.ts", "src/main.js", "index.html"),
        ("npm",),
    ),
    Case(
        "svelte",
        "Inizializza in questo workspace un progetto Svelte in modo non interattivo. "
        "Installa le dipendenze.",
        "package.json",
        ("src/main.ts", "src/main.js", "index.html", "svelte.config.js"),
        ("npm",),
    ),
    Case(
        "angular",
        "Inizializza in questo workspace un progetto Angular in modo non interattivo, "
        "senza test e senza routing. Installa le dipendenze.",
        "package.json",
        ("angular.json", "src/main.ts"),
        ("npm",),
    ),
    Case(
        "remix",
        "Inizializza in questo workspace un progetto Remix (o React Router framework) "
        "in modo non interattivo. Installa le dipendenze.",
        "package.json",
        ("app/root.tsx", "app/root.jsx", "vite.config.ts"),
        ("npm",),
    ),
    Case(
        "tanstack",
        "Inizializza in questo workspace un progetto TanStack Router/Start in modo "
        "non interattivo. Installa le dipendenze.",
        "package.json",
        ("src/main.tsx", "src/routes", "app/router.tsx"),
        ("npm",),
    ),
    Case(
        "react_puro",
        "Inizializza in questo workspace un progetto React senza framework, con un "
        "bundler, in modo non interattivo. Installa le dipendenze.",
        "package.json",
        ("src/index.jsx", "src/index.tsx", "src/main.jsx", "index.html"),
        ("npm",),
    ),
    Case(
        "nextjs",
        "Inizializza in questo workspace un progetto Next.js in modo non interattivo, "
        "con TypeScript. Installa le dipendenze.",
        "package.json",
        ("app/page.tsx", "pages/index.tsx", "next.config.ts", "next.config.js"),
        ("npm",),
    ),
    Case(
        "node_backend",
        "Inizializza in questo workspace un backend Node.js con un server HTTP "
        "minimo e un package.json valido, in modo non interattivo.",
        "package.json",
        ("index.js", "src/index.js", "server.js", "index.ts"),
        ("npm",),
    ),
    Case(
        "django",
        "Inizializza in questo workspace un progetto Django in un ambiente virtuale, "
        "in modo non interattivo.",
        "manage.py",
        ("manage.py",),
        ("python",),
    ),
    Case(
        "bun_frontend",
        "Inizializza in questo workspace un progetto frontend con Bun in modo non interattivo.",
        "package.json",
        ("index.html", "src/index.ts", "index.ts"),
        ("bun",),
    ),
)


@dataclass
class Outcome:
    id: str
    attempted: bool = False
    passed: bool = False
    reasons: list[str] = field(default_factory=list)
    verdict: str = ""
    wall_s: float = 0.0
    skipped: str = ""


def _score(case: Case, ws: Path) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    manifest = ws / case.manifest
    if not manifest.is_file():
        reasons.append(f"{case.manifest} missing at the workspace root")
    elif manifest.stat().st_size == 0:
        reasons.append(f"{case.manifest} is empty")

    if case.entry_globs and not any((ws / g).exists() for g in case.entry_globs):
        reasons.append(f"no entry artifact (looked for {', '.join(case.entry_globs)})")

    if case.build_dir and not (ws / case.build_dir).is_dir():
        reasons.append(f"{case.build_dir}/ was never produced")

    # A project nested one level down is a failure even when everything exists inside it.
    if reasons:
        nested = [p for p in ws.iterdir() if p.is_dir() and (p / case.manifest).is_file()]
        if nested:
            reasons.append(
                f"project is nested under '{nested[0].name}/' — the workspace IS the root"
            )
    return (not reasons), reasons


def _verdict() -> str:
    tel = TELEMETRY_DIR
    files = sorted(tel.glob("run_*.json")) if tel.exists() else []
    if not files:
        return "?"
    try:
        return json.loads(files[-1].read_text(encoding="utf-8")).get("verdict", "?")
    except Exception:
        return "?"


def _have(tool: str) -> bool:
    return shutil.which(tool) is not None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated case ids")
    ap.add_argument("--timeout", type=int, default=600, help="seconds per case")
    ap.add_argument("--label", default="stress")
    a = ap.parse_args()

    only = {x.strip() for x in a.only.split(",") if x.strip()}
    cases = [c for c in CASES if not only or c.id in only]
    out_dir = OUT / a.label
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[Outcome] = []
    for c in cases:
        o = Outcome(id=c.id)
        missing = [t for t in c.needs if not _have(t)]
        if missing:
            o.skipped = f"missing on this host: {', '.join(missing)}"
            print(f"[{c.id}] SKIP  ({o.skipped})", flush=True)
            results.append(o)
            continue

        ws = out_dir / "workspaces" / c.id
        shutil.rmtree(ws, ignore_errors=True)
        ws.mkdir(parents=True, exist_ok=True)

        cmd = [sys.executable, "-u", "-m", "src.main", c.goal, "--workspace", str(ws)]
        import os as _os

        env = dict(
            _os.environ,
            SISTEMISTA_CONFINE_ROOT=str(ws.resolve()),
            SISTEMISTA_ORACLE="1",
            SISTEMISTA_TRACE_DIR=str(out_dir / "traces"),
        )

        o.attempted = True
        t0 = time.time()
        log = out_dir / f"{c.id}.log"
        try:
            with log.open("wb") as fh:
                subprocess.run(
                    cmd,
                    cwd=str(ROOT),
                    env=env,
                    stdout=fh,
                    stderr=fh,
                    timeout=a.timeout,
                    check=False,
                )
        except subprocess.TimeoutExpired:
            o.reasons.append(f"timed out after {a.timeout}s")
        o.wall_s = round(time.time() - t0, 1)
        o.verdict = _verdict()

        ok, reasons = _score(c, ws)
        o.passed = ok and not o.reasons
        o.reasons += reasons
        status = "PASS" if o.passed else "FAIL"
        detail = "" if o.passed else f" :: {'; '.join(o.reasons)[:110]}"
        print(f"[{c.id}] {status} ({o.verdict}) {o.wall_s}s{detail}", flush=True)
        results.append(o)

    attempted = [r for r in results if r.attempted]
    passed = sum(1 for r in attempted if r.passed)
    report = {
        "label": a.label,
        "attempted": len(attempted),
        "passed": passed,
        "skipped": [r.id for r in results if r.skipped],
        "rate": round(passed / len(attempted), 4) if attempted else 0.0,
        "results": [r.__dict__ for r in results],
    }
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"\nscaffold rate = {passed}/{len(attempted)} attempted "
        f"({len(report['skipped'])} skipped: {', '.join(report['skipped']) or 'none'})"
    )
    print(f"[report] {out_dir / 'report.json'}")


if __name__ == "__main__":
    main()
