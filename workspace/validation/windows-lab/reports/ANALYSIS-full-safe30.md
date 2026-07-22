# Windows Validation Lab — Failure Analysis (run `full-safe30`)

> ⚠️ **Documento storico — congelato.** Scritto prima della riorganizzazione del 2026-07-10;
> numeri, prosa e conclusioni sono lasciati esattamente com'erano. I path che cita si leggono così:
> `.workspace/` → `workspace/` · `validation/telemetry/` → `var/telemetry/` ·
> `validation/benchmark/` → `var/benchmark/` · `src/tests/` → `tests/` · `_test_workspaces/` → `_sandbox/`.
> I comandi di riproduzione al suo interno non sono più eseguibili alla lettera.

> Live run of the real dual-GGUF agent on GPU, one case at a time, on this Windows 10 host.
> 30 executable cases (28 SAFE + 2 refusal) of the 583 Windows osbench cases. The agent saw
> only the goal; it was never helped. Corpus: `validation/windows-lab/failure-db/`.

## Headline

| Metric | Value | Reading |
|---|---|---|
| ARR (osbench check) | **63.3%** (19/30) | **Optimistic** — the `artifact` check passes on placeholder content (see C0) |
| FTFR (First-Time Fix) | **26.7%** (8/30) | Only 8 solved cleanly on the first plan→act→verify pass |
| RAF (Recovery Amplification) | **2.11** | Success rate more than doubles via recovery — value comes from *retries*, not first-pass reasoning |
| Deviations | 22/30 | Cases needing maintainer study |

RAF=2.11 + FTFR=27% is the core story: **the agent's initial reasoning is weak; it survives by
retrying.** For a sysops agent, first-time fix is the product. This is where to invest.

## Root causes (by leverage, not by symptom)

### C0 — Benchmark check too lenient → ARR is inflated *(measurement bug, fix first)*
`success_check.kind == "artifact"` passes on `exists + nonempty`. Cases where the agent wrote a
**placeholder** (`PATH_CONTENT`, unexecuted `$(...)`) still count as resolved even though the file
is junk. The agent's OWN artifact-check (invariant #9) correctly returned INCOMPLETE — it is *more*
rigorous than the benchmark here. **Real ARR < 63%.**
- Cases: WIN-ENV_PATH-00001, WIN-USERS-00001, WIN-KERNEL-00001, WIN-PERFORMANCE-00003, WIN-RECOVERY-00001, WIN-SERVICES-00003, WIN-PROCESSES-00001 (the 7 "under-report").
- **Fix:** these osbench cases must use `file_contains` with a real pattern, not `artifact`. And the
  study must trust the agent's INCOMPLETE-on-placeholder over the weak check.

### C1 — Missing capability: "run a command and capture stdout into a file" *(dominant, ~10 cases)*
The single largest agent gap. Almost every SAFE Windows task is *"put diagnostic X into file Y"*.
The agent knows the right cmdlet but **cannot reliably land its output on disk**. It oscillates
between two broken strategies:
- (a) `write_file|file|$(Get-... )` — passes a **shell expression as literal content**; the internal
  `write_file` writes it verbatim → placeholder. (WIN-ENV_PATH, WIN-USERS)
- (b) in-shell redirect (`foreach`+`$content`, `| Out-File`, `> file`) that dies on
  quoting/encoding/`$null`/backtick mangling / PowerShell ParserError. (WIN-SERVICES, WIN-FIREWALL,
  WIN-NETWORKING)

This is a **category**, not a per-tool case: capture-to-file is a first-class primitive the agent
lacks. **Fix (highest leverage):** a `capture|<outfile>|<command>` tool that runs the command in the
session shell and writes stdout atomically as UTF-8, + executor prompt steering "put X in file" →
`capture`. Expected to flip 6–10 cases.

### C2 — Tool dispatch is fragile → raw TypeErrors, unrecoverable *(3 cases, trivial fix)*
`fileops.dispatch` does `fn(*args, cwd)` blindly ([fileops.py:266](../../../src/tools/fileops.py#L266)).
The 3B executor emits `make_dir|.github|workflows` (over-split path) or too few args, producing
`TypeError: make_dir() takes 2 positional arguments but 3 were given`. That raw Python error:
1. crashes the step, and
2. classifies as `UNKNOWN` → the recovery layer gets nothing actionable.
- Cases: WIN-CICD-00001, WIN-CICD-00004 (arity), WIN-CICD-00002 (WinError 183/267, path-sep + non-idempotent mkdir).
- **Fix:** signature-aware normalization (join surplus path args, detect missing args) + return an
  **actionable** error naming the exact expected shape, not a raw TypeError. Make `make_dir`
  idempotent and path-separator agnostic.

### C3 — `error_classifier` is blind to the failures that actually happen (UNKNOWN = 51/81)
63% of all failed-action signals are `UNKNOWN`, so recovery is derived from nothing. The classifier
misses: internal tool errors (`[ERROR] tool … wrong args`), Windows error codes (`WinError 183/267`),
PowerShell ParserErrors (`~~~~` / `is not recognized as … cmdlet` in a `$(...)` position),
placeholder-not-filled. **Fix (RFC-0005 §4):** add signal rows to `_SIGNAL_TABLE` — one owner, no
parallel Windows list. Turns UNKNOWN failures into recoverable, classified ones.

## Genuine unresolved, other (need per-case depth after C1/C2)
WIN-FIREWALL-00001 also hit **PERMISSION_DENIED** (some firewall enumeration needs elevation) — a
real elevation-strategy gap. WIN-GROUPS/SCHEDULER/TLS/PROCESSES-00002/SERVICES-00002: re-triage
after C1 lands, since several are output→file in disguise.

## Priority order
1. **C0** — fix the benchmark checks (else we optimize against a lying metric).
2. **C2 + C3** — safe, unambiguous code fixes; land + re-run CICD to verify (done in this iteration).
3. **C1** — the capability that moves the needle; own iteration with prompt + orchestrator changes.
