# osbench — the OS-scenario benchmark for terminal Systems-Engineering agents

> A reproducible, state-verified benchmark for evaluating an autonomous AI agent that
> operates a computer **exclusively through a terminal** — across Linux, Windows and macOS,
> from read-only diagnostics to principal-level compound incidents.

**1694 cases** · **≥500 per OS** · **52 domains** · **127 golden** · deterministic generation ·
machine-checkable outcomes · 11-metric scoring.

---

## Why it exists

Existing coding benchmarks grade *diffs*. A Systems Engineer's job is not a diff — it is
restoring an invariant of a running system under uncertainty, safely. osbench grades that:
each case induces a real fault (or asks a real question, or sets a trap), hands the agent a
single natural-language goal, and scores the **resulting system state** — never the command
strings. It is designed to be hard for *any* terminal agent (our dual-GGUF agent, Claude
Code, Codex CLI, OpenHands, Goose, Gemini CLI, Aider, Continue, SWE-Agent, …) and to run as
continuous CI regression.

Design DNA is inherited from the project's Operating Contract (see repo `AGENTS.md`):
reason over **categories** (package manager, service manager, filesystem), never
`if nginx`; require a causal theory before any change; treat safety as non-negotiable.

## Layout

```
osbench/
  schema/benchmark.schema.json     # JSON Schema for one case (25 fields + verify predicate)
  shared/    model.py  matrix.py   # Case model + real-world OS tooling matrix
  generators/                      # deterministic corpus producers (families) + gen_docs
  linux/ windows/ macos/           # materialized cases, one JSON per case, by domain
  datasets/                        # all_cases.jsonl, index.json, distribution.json, taxonomies
  validators/                      # state-based checkers + dataset integrity gate
  scoring/                         # 11-metric scorer + report/leaderboard generators
  reports/                         # generated scorecards (STUB_ prefix = nothing was executed)
  run.py                           # the harness: dataset -> adapter -> validators -> score
```

Paths follow the repo convention: this subtree lives under `workspace/benchmarks/osbench`
(execution plane) and is self-contained — extractable as a standalone open-source repo.

## Quickstart

```bash
# from workspace/ (venv active)
python -m benchmarks.osbench.generators.build_dataset      # (re)generate the corpus
python -m benchmarks.osbench.generators.gen_docs           # regenerate coverage/difficulty docs
python -m benchmarks.osbench.validators.validate_dataset   # CI gate: schema + dedup + coverage
python -m benchmarks.osbench.run --adapter dry --golden --label demo   # run the harness
```

Generation is deterministic (fixed seed) so the corpus is stable across runs and CI diffs
are meaningful.

## A case

The agent under test sees only `goal`. Everything else grades it:

- **scenario / environment / initial_state** — the fault to materialize (fixtures).
- **expected_reasoning** — the causal chain a correct agent should follow (graders' key).
- **expected/forbidden_commands, safety_constraints** — anchors + the safety gate.
- **success_check / failure_check** — machine-checkable `Verify` predicates (state, not text).
- **ground_truth** — the true root cause and key values.
- **recovery_strategy, possible_mistakes, hints, reference/alternative_solution, edge_cases,
  budgets** — grading, pedagogy, calibration.

Full field semantics: [datasets/taxonomy.md](datasets/taxonomy.md).

## Scoring (11 metrics)

`autonomous_resolution_rate · reasoning_quality · command_efficiency · safety ·
recovery_capability · context_efficiency · token_efficiency · latency · reliability ·
robustness · determinism`.

- **ARR** uses the same definition as the runtime `benchmarks/arr_aggregator.py`: a correct
  **refusal** counts as success, not failure.
- **Safety is a gate**: any forbidden/destructive command, or a missed required refusal,
  sets safety to 0 and caps the case's overall score — resolved-but-unsafe is not a pass.
- Per-run cost/latency fields mirror `benchmarks/telemetry_schema.py::Decision`, so runs can
  be built directly from the agent's existing telemetry.

Details: [datasets/reasoning-taxonomy.md](datasets/reasoning-taxonomy.md) ·
[datasets/failure-taxonomy.md](datasets/failure-taxonomy.md).

## State-based validation (anti-gaming)

Validators observe the real post-run state — `artifact`, `file_contains/mode/owner`,
`port_listening/closed`, `service_active/inactive`, `process_running/absent`,
`http_ok`, `package_installed`, `kv_equals`, `command_succeeds/stdout`, and `refused`
(from the transcript) — plus `all_of/any_of/none_of` composites. An agent that reaches the
goal by a different valid path scores full marks; one that memorizes a golden command line
gains nothing. Host-touching probes are gated behind flags and skip placeholders.

## Golden set

127 frozen gold-standard cases (stratified across OS × difficulty × domain, plus **every**
safety-refusal case) form the stable comparison corpus for tracking our agent across
versions and against competitors. Flagged `golden: true`; select with `--golden`.

## Competitor mode

Implement one `AgentAdapter` per agent (subprocess into its CLI), run the same subset
through each, and generate a side-by-side leaderboard. `write_comparison` REFUSES to
write one unless every agent was produced by an adapter that actually executed —
see `_attic/osbench-synthetic-leaderboard/` for why that guard exists:

```python
from benchmarks.osbench.scoring.report import write_comparison
write_comparison({"sistemista": card_a, "other-agent": card_b})  # both must be executed
```

## Safety of running the benchmark itself

By default the harness runs only `SAFE` (read-only/diagnostic) and refusal cases, mirroring
`benchmarks/run_suite.py`. `RECOVERABLE` fixtures that mutate state require
`--allow-mutating` and always run in an isolated per-case workspace. `DESTRUCTIVE` cases are
**never executed** — they are refusal tests: the correct behaviour is to refuse.

## Extending

Add a tool/resource to `shared/matrix.py` (a new package manager, service, filesystem,
failure cause) and the combinatorial families expand coverage automatically — no new code.
Add a `@register`ed family for a new area. Re-run `build_dataset` → `gen_docs` →
`validate_dataset`. The integrity gate enforces schema, uniqueness, dedup, non-empty content
(no TODOs/placeholders), and the per-OS coverage/difficulty floors.
