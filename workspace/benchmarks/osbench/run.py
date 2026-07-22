"""
osbench harness — run an agent over the benchmark and produce a scorecard.

Flow per case:
  1. materialize an isolated workspace and apply the case's `initial_state` fixture;
  2. hand the case's single natural-language `goal` to an AgentAdapter (the ONLY thing
     the agent sees — never the reasoning/solution, which are graders' keys);
  3. observe the resulting state and evaluate `success_check` with the validators;
  4. record a RunRecord (resolution, safety, tokens, latency, …);
  5. aggregate into a Scorecard and write a report.

Adapters
--------
An AgentAdapter is any object with:
    run(goal: str, workspace: Path, case_meta: dict) -> AdapterResult
Implement one per agent under test (our agent, Claude Code, Codex CLI, OpenHands, …).
`DryRunAdapter` executes nothing — it exercises the harness/validators/scoring wiring
so the pipeline is CI-testable without a live host or model.

SAFETY: fixtures that mutate real state are gated behind `--allow-mutating`; by default
the harness runs only SAFE (read-only/refusal) cases, mirroring benchmarks/run_suite.py.

Usage:
  python -m benchmarks.osbench.run --adapter live --golden --limit 50 --label real
  python -m benchmarks.osbench.run --adapter dry  --golden --limit 50 --label pipeline-check  # STUB
  python -m benchmarks.osbench.run --adapter dry --os linux --difficulty easy,medium
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .scoring.metrics import RunRecord, score_suite
from .scoring.report import write_report
from .shared.model import Case
from .validators.checks import RunContext, current_os, evaluate

ROOT = Path(__file__).resolve().parent
JSONL = ROOT / "datasets" / "all_cases.jsonl"


@dataclass
class AdapterResult:
    transcript: str = ""
    commands: list[str] = field(default_factory=list)
    refused: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    context_tokens_peak: int = 0
    latency_s: float = 0.0
    # artifacts the adapter chose to write are simply left in the workspace and observed


class AgentAdapter(Protocol):
    name: str

    def run(self, goal: str, workspace: Path, case_meta: dict) -> AdapterResult: ...


class DryRunAdapter:
    """Executes nothing. Emits the goal as transcript so `refused` checks can be exercised.

    Real adapters (subprocess into an agent CLI) replace this. Kept deterministic so the
    harness pipeline is testable in CI.

    `executes = False` is load-bearing: every scorecard it produces is written as
    `STUB_scorecard_*` and carries `"is_measurement": false`. Its numbers score a stub
    transcript, never an agent. The three scorecards in `reports/` were all produced this
    way, at 0.53-0.70 overall, while a fabricated leaderboard claimed 86.3% over 127 cases."""

    name = "dry"
    executes = False

    def run(self, goal: str, workspace: Path, case_meta: dict) -> AdapterResult:
        refuse = bool(case_meta.get("must_refuse"))
        transcript = (
            "Mi rifiuto: operazione distruttiva e irreversibile. Propongo un'alternativa sicura."
            if refuse
            else f"[dry-run] would plan for goal: {goal}"
        )
        return AdapterResult(
            transcript=transcript,
            commands=[],
            refused=refuse,
            prompt_tokens=0,
            completion_tokens=0,
            latency_s=0.0,
        )


ADAPTERS: dict[str, type] = {"dry": DryRunAdapter}


def _resolve_adapter(name: str):
    """Instantiate an adapter by name. `live` is imported lazily so that only a real
    run pays the model-load / CUDA cost (and so run.py has no import cycle)."""
    if name == "live":
        from .adapters import LiveOrchestratorAdapter

        a = LiveOrchestratorAdapter()
        # The only adapter that touches the product. Anything else scores a stub.
        a.executes = True
        return a
    return ADAPTERS[name]()


def load_cases() -> list[Case]:
    return [
        Case.from_dict(json.loads(line)) for line in JSONL.open(encoding="utf-8") if line.strip()
    ]


def _forbidden_hits(case: Case, result: AdapterResult) -> int:
    import re

    blob = "\n".join(result.commands) + "\n" + result.transcript
    hits = 0
    for pat in case.forbidden_commands:
        try:
            if re.search(pat, blob):
                hits += 1
        except re.error:
            continue
    return hits


def run_case(
    case: Case, adapter: AgentAdapter, allow_mutating: bool, allow_host_probes: bool
) -> RunRecord:
    ws = Path(tempfile.mkdtemp(prefix=f"osbench_{case.id}_"))
    try:
        # (fixtures that mutate real host state would be applied here when allow_mutating)
        t0 = time.time()
        res = adapter.run(case.goal or case.title, ws, dict(case.ground_truth))
        latency = res.latency_s or (time.time() - t0)

        ctx = RunContext(
            workspace=ws,
            os_name=current_os(),
            transcript=res.transcript,
            executed_commands=res.commands,
            allow_host_probes=allow_host_probes,
        )
        check = evaluate(case.success_check, ctx)
        must_refuse = bool(case.ground_truth.get("must_refuse"))
        resolved = check.ok and not check.skipped if not must_refuse else False

        return RunRecord(
            case_id=case.id,
            resolved=resolved,
            refused=res.refused,
            reasoning_text=res.transcript,
            commands=res.commands,
            forbidden_hits=_forbidden_hits(case, res),
            needed_recovery=False,
            recovered=False,
            prompt_tokens=res.prompt_tokens,
            completion_tokens=res.completion_tokens,
            context_tokens_peak=res.context_tokens_peak,
            latency_s=latency,
            plan_signature=hashlib.sha1("\n".join(res.commands).encode()).hexdigest()[:12],
        )
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def select(cases: list[Case], args) -> list[Case]:
    out = cases
    if args.golden:
        out = [c for c in out if c.golden]
    if args.os:
        wanted = set(args.os.split(","))
        out = [c for c in out if c.os.value in wanted]
    if args.difficulty:
        wanted = set(args.difficulty.split(","))
        out = [c for c in out if c.difficulty.value in wanted]
    if args.domain:
        wanted = set(args.domain.split(","))
        out = [c for c in out if c.domain in wanted]
    if not args.allow_mutating:
        # default: only SAFE + refusal cases (never mutate a real host)
        out = [c for c in out if c.risk == "SAFE" or c.ground_truth.get("must_refuse")]
    if args.limit:
        out = out[: args.limit]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    # No default. `dry` used to be it, so the documented command produced a stub scorecard
    # that read like a measurement. Choosing to not execute must be an explicit act.
    ap.add_argument(
        "--adapter",
        required=True,
        choices=list(ADAPTERS) + ["live"],
        help="'live' measures the agent; 'dry' executes nothing and emits a STUB_ scorecard",
    )
    ap.add_argument("--label", default="run")
    ap.add_argument("--golden", action="store_true")
    ap.add_argument("--os", default="")
    ap.add_argument("--difficulty", default="")
    ap.add_argument("--domain", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--allow-mutating",
        action="store_true",
        help="run RECOVERABLE fixtures that mutate the host (isolated only)",
    )
    ap.add_argument(
        "--allow-host-probes",
        action="store_true",
        help="permit read-only command_* probes against the live host",
    )
    args = ap.parse_args()

    cases = load_cases()
    subset = select(cases, args)
    adapter = _resolve_adapter(args.adapter)
    print(f"Running {len(subset)} cases with adapter '{adapter.name}' (label={args.label})...")

    runs = [run_case(c, adapter, args.allow_mutating, args.allow_host_probes) for c in subset]
    card = score_suite({c.id: c for c in subset}, runs)
    card.adapter = adapter.name
    card.executed = bool(getattr(adapter, "executes", False))
    path = write_report(card, args.label)
    kind = "MEASUREMENT" if card.executed else "STUB (nothing was executed)"
    print(f"Overall: {card.overall:.3f}  n={card.n_cases} cases  [{kind}]")
    print(f"report: {path.relative_to(ROOT.parent.parent)}")


if __name__ == "__main__":
    main()
