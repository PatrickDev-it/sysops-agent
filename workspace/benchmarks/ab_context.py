"""
A/B test: current context vs compiled context (M0/F0).

Uses the REAL belief snapshots captured in validation/telemetry/ (68 runs) as fixtures,
so the comparison is grounded in actual states the v1 agent produced.

What this measures NOW (no model needed):
  - context size in tokens (current vs compiled), per run and aggregate → the -40% target's
    leading indicator (context is the dominant term of tokens/task).

What requires the local 4B (run on the target machine, --generate):
  - parse-error rate and latency per decision, by actually calling the supervisor model
    on each arm. The harness wires this but does NOT run it here (needs GPU + models).

Token counting:
  - default: chars/4 heuristic (approximate, labelled as such)
  - --model-tokenizer: exact counts via the supervisor GGUF tokenizer (loads the model)
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from src.config import TELEMETRY_DIR

from .context_compiler import Belief, build_current_context, compile_context, count_tokens


def _load_records() -> list[dict]:
    out = []
    for p in sorted(TELEMETRY_DIR.glob("run_*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return out


def _model_tokenizer():
    """Return an exact tokenizer(str)->int using the supervisor GGUF, or None."""
    try:
        from llama_cpp import Llama
        from src import config

        llm = Llama(
            model_path=str(config.SUPERVISOR_MODEL), n_ctx=512, n_gpu_layers=0, verbose=False
        )
        return lambda s: len(llm.tokenize(s.encode("utf-8", errors="ignore")))
    except Exception as e:
        print(f"[model-tokenizer unavailable: {e}] falling back to heuristic")
        return None


def run_token_ab(budget: int, tokenizer) -> dict:
    recs = _load_records()
    rows = []
    for rec in recs:
        b = Belief.from_telemetry(rec)
        cur = build_current_context(b)
        comp = compile_context(b.goal, b, budget_tokens=budget, tokenizer=tokenizer)
        tc = count_tokens(cur, tokenizer)
        tk = count_tokens(comp, tokenizer)
        rows.append(
            {
                "run_id": rec.get("run_id"),
                "current": tc,
                "compiled": tk,
                "reduction": round(1 - tk / tc, 4) if tc else 0.0,
            }
        )
    cur_tokens = [r["current"] for r in rows]
    cmp_tokens = [r["compiled"] for r in rows]
    agg = {
        "n": len(rows),
        "tokenizer": "model-exact" if tokenizer else "heuristic(chars/4)",
        "budget": budget,
        "current_mean": round(statistics.mean(cur_tokens), 1) if rows else 0,
        "current_median": round(statistics.median(cur_tokens), 1) if rows else 0,
        "compiled_mean": round(statistics.mean(cmp_tokens), 1) if rows else 0,
        "compiled_median": round(statistics.median(cmp_tokens), 1) if rows else 0,
        "mean_reduction": round(statistics.mean([r["reduction"] for r in rows]), 4) if rows else 0,
        "aggregate_reduction": round(1 - sum(cmp_tokens) / sum(cur_tokens), 4)
        if sum(cur_tokens)
        else 0,
    }
    return {"aggregate": agg, "rows": rows}


def to_markdown(agg: dict, target_reduction: float = 0.40) -> str:
    hit = agg["aggregate_reduction"] >= target_reduction
    return "\n".join(
        [
            "| Metrica | Valore |",
            "|---|---|",
            f"| Run (fixtures) | {agg['n']} |",
            f"| Tokenizer | {agg['tokenizer']} |",
            f"| Budget contesto compilato | {agg['budget']} token |",
            f"| Contesto CURRENT (media / mediana) | {agg['current_mean']} / {agg['current_median']} |",
            f"| Contesto COMPILED (media / mediana) | {agg['compiled_mean']} / {agg['compiled_median']} |",
            f"| Riduzione media per-run | {agg['mean_reduction']:.1%} |",
            f"| **Riduzione aggregata (token totali)** | **{agg['aggregate_reduction']:.1%}** |",
            f"| Target -40% token | {'✅ RAGGIUNTO' if hit else '❌ non raggiunto'} (indicatore anticipatore) |",
        ]
    )


def run_generate_ab():
    """User-run path: call the supervisor 4B on both arms, measure parse-error + latency.
    Requires GPU + models. Wired but intentionally not executed in CI/dev."""
    raise SystemExit(
        "--generate richiede i modelli GGUF locali e GPU. Eseguire sulla macchina target:\n"
        "  . .venv/Scripts/Activate.ps1 && cd workspace\n"
        "  python -m benchmarks.ab_context --generate\n"
        "Il path di generazione instrada ctx_current e ctx_compiled a model_router.supervisor_call\n"
        "e registra Decision(parse_ok, latency_ms, tokens) via benchmarks.telemetry_schema."
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=int, default=1200)
    ap.add_argument("--model-tokenizer", action="store_true")
    ap.add_argument("--generate", action="store_true", help="4B parse/latency A/B (needs models)")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    if args.generate:
        run_generate_ab()
        return

    tok = _model_tokenizer() if args.model_tokenizer else None
    res = run_token_ab(args.budget, tok)
    print("# A/B — Context size (current vs compiled)\n")
    print(to_markdown(res["aggregate"]))
    if args.json:
        Path(args.json).write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n[written] {args.json}")


if __name__ == "__main__":
    main()
