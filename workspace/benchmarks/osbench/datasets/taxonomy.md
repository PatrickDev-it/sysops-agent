# osbench taxonomy

The organizing principle of osbench mirrors the project's Operating Contract: an agent
is scored as a **maintainer of a model of the system**, not a fixer of error strings.
Every case is classified along orthogonal axes so coverage is auditable and gaming is hard.

## Axes

### 1. Operating System
`linux` · `windows` · `macos`. Cross-OS cases are emitted per platform with the correct
tooling dialect (systemd/sc/launchd, `ss`/`Get-NetTCPConnection`/`lsof`). OS is part of a
case's semantic signature, so the "same" problem on two OSes is two distinct cases.

### 2. Domain (52 canonical domains)
Owned by `shared/model.py::DOMAINS`. Domains are **categories of system behaviour**, never
tool databases: `packages` (not `apt`), `services` (not `nginx`), `firewall` (not `ufw`).
This is the anti-`if framework` rule from the project contract applied to the benchmark.

Groups: filesystem/storage (filesystem, storage, lvm_raid, encryption, acl, ownership,
permissions), identity (users, groups, sudo, ssh), lifecycle (services, scheduler,
processes, signals, boot, upgrade), software (packages, toolchains, containers,
kubernetes, git, cicd, iac), network (networking, dns, routing, firewall, remote_access,
filesharing, proxy), platform (kernel, drivers, gpu, virtualization, wsl, env_path, shell),
data services (databases, caching, secrets), trust (certificates, tls, security,
selinux_apparmor), operations (logs, monitoring, performance, memory, backup, recovery,
cloud).

### 3. Difficulty (5 tiers)
`easy` → `medium` → `hard` → `expert` → `principal`. Difficulty is intrinsic to how much
**causal inference** a case demands, not to command length:
- **easy** — a single read-only observation (diagnostics). No state change is correct.
- **medium** — one deliberate, persistent change with a clear end-state.
- **hard** — single root cause behind a misleading symptom; requires OBSERVE→HYPOTHESIZE.
- **expert** — subtle or multi-signal cause (MAC denials, resource caps, ABI/PMTU), or a
  compound fault; the naive fix masks the cause.
- **principal** — compound, cross-domain incident under constraint (RPO/RTO, split-brain,
  security containment, capacity). Judgement, ordering, and guardrails are graded, not just
  the fix.

### 4. Risk (reused from the runtime harness)
`SAFE` (read-only/diagnostic) · `RECOVERABLE` (mutates isolated state, reversible) ·
`DESTRUCTIVE` (refusal tests — the agent must NOT execute). The harness runs only SAFE +
refusal cases by default; RECOVERABLE fixtures require `--allow-mutating` and an isolated
workspace.

### 5. Provenance (`family`)
Which generator family produced the case. Combinatorial families sweep the parameter
matrix (`service × failure-cause`, `pkg-mgr × conflict`, `runtime × dep-failure`);
compound families pair co-occurring causes; task families cover breadth. Provenance makes
coverage reproducible: adding a tool to `shared/matrix.py` expands the corpus with no new
code — the same generalization we require of the agent.

## The 25 fields of a case
`id, title, difficulty, os, domain, prerequisites, scenario, environment, initial_state,
expected_reasoning, expected_commands, forbidden_commands, safety_constraints,
success_criteria, failure_criteria, recovery_strategy, ground_truth, expected_time_s,
expected_token_budget, possible_mistakes, hints, reference_solution, alternative_solution,
edge_cases` — plus machine-checkable `success_check`/`failure_check` predicates and
alignment metadata (`risk`, `goal`, `golden`, `family`, `tags`).

The agent under test sees ONLY `goal`. Everything else is a grader's key.

## Cross-references
- Failure modes → [failure-taxonomy.md](failure-taxonomy.md)
- Command/action classes → [command-taxonomy.md](command-taxonomy.md)
- Reasoning patterns graded → [reasoning-taxonomy.md](reasoning-taxonomy.md)
- Terminal/PTY interaction surface → [terminal-taxonomy.md](terminal-taxonomy.md)
- Counts → [coverage-matrix.md](coverage-matrix.md) · [difficulty-distribution.md](difficulty-distribution.md)
