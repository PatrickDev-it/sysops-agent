# Difficulty distribution

_Generated from `datasets/distribution.json`. Do not hand-edit._

Per-OS minimum floors: easy ≥ 25, medium ≥ 50, hard ≥ 150, expert ≥ 200, principal ≥ 75.

| OS | easy | medium | hard | expert | principal | Total | Meets floors |
|---|---:|---:|---:|---:|---:|---:|:--:|
| linux | 25 | 64 | 173 | 234 | 101 | 597 | ✅ |
| windows | 25 | 50 | 168 | 237 | 103 | 583 | ✅ |
| macos | 25 | 51 | 151 | 201 | 86 | 514 | ✅ |

## Rationale

The distribution is an **inverted pyramid** weighted toward `hard`/`expert`: a
benchmark for a *Systems Engineer* must concentrate mass where real on-call
difficulty lives — multi-signal diagnosis and compound faults — not on trivial
one-liners. `easy` cases exist to anchor the low end (read-only diagnostics);
`principal` cases are compound, cross-domain incidents requiring judgement under
constraint. Budgets (time, tokens) scale monotonically with difficulty so the
efficiency metrics are calibrated per tier.
