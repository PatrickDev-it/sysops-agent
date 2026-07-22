# SISTEMISTA — ARCHITECTURE REVIEW

> ⚠️ **Documento storico — congelato.** Scritto prima della riorganizzazione del 2026-07-10;
> numeri, prosa e conclusioni sono lasciati esattamente com'erano. I path che cita si leggono così:
> `.workspace/` → `workspace/` · `validation/telemetry/` → `var/telemetry/` ·
> `validation/benchmark/` → `var/benchmark/` · `src/tests/` → `tests/` · `_test_workspaces/` → `_sandbox/`.
> I comandi di riproduzione al suo interno non sono più eseguibili alla lettera.

Source of truth: validation/failures.md + direct source reading
Reviewer: Architecture phase (post-validation)
Date: 2026-06-15

---

## Pattern A — Final verify loop inverts completed tasks

### Evidence

T001: shell_report.txt written correctly (154B), verify() returns `{"achieved": true}`,
orchestrator prints `TASK INCOMPLETE: {"achieved": true, "reason": "..."}`.

Source: orchestrator.py lines 313-326
```python
obs = observe(goal, session)
det_ok, det_reason = observe_judge(goal, obs, session)
if not det_ok:
    console.print(f"[bold red]TASK INCOMPLETE:[/] {det_reason}")
    return
achieved, reason, _ = supervisor.verify(goal, session)
if not achieved:
    console.print(f"[bold red]TASK INCOMPLETE:[/] {reason}")
    return
console.print(f"[dim]Goal verified: {reason}[/]")
```

### Root architectural cause

`supervisor.verify()` is called for the FINAL task-level check with the GOAL string as
objective, but `observe_judge()` is called with the same GOAL string as objective.
`observe_judge()` (src/observer.py:75-153) has one interpretation for non-cleanup goals:
"does the workspace have real content?" If the goal's natural output is NOT a file in
the workspace root (e.g. shell detection → shell_report.txt is present → should pass),
and if some earlier `observe_judge()` call with a STEP-level objective already blocked
at that step, then the final verify may be redundant — but this path is reachable.

The actual failure observed is different: the JSON string from `verify_call()` appears
verbatim in the INCOMPLETE message. This means `achieved` is False or the call to
`observe_judge()` at line 314 is returning False for a completed workspace.
Evidence from T001: `shell_report.txt` is 154B and non-hidden → `real_entries` is
non-empty → `has_content` is True → `observe_judge()` should return True.
The only remaining path: `supervisor.verify(goal, session)` at line 319 returns
`achieved=False` with `reason` containing the full JSON string — meaning `model_router.verify_call()`
is returning a dict where `result.get("achieved", False)` evaluates to False even when
the raw JSON says `"achieved": true`. Boolean coercion or string "true" not parsed.

### Why current design fails

`supervisor.verify()` returns `(bool, str, str)` with no type contract.
`result.get("achieved", False)` can receive `"true"` (JSON string), `True` (bool),
`1` (int), or a missing key — all handled differently by Python's truthiness.
The return contract is implicit: whoever calls `bool(result.get("achieved", False))`
can silently misread a string `"true"` as truthy (it is) but a string `"false"` as
also truthy (it is). The actual bug: if the model returns `{"achieved": false}` when
the outer JSON wrapping fails, the result dict may contain `"achieved": "false"` as
a string — which `bool("false")` evaluates to `True`, inverting the result.

### General fix principle

Replace the implicit `(bool, str, str)` tuple with a typed VerificationResult dataclass.
Parse the LLM response at a single boundary: `model_router.verify_call()` must always
return `{"achieved": bool, "reason": str, "action": str}` with the `achieved` field
already a Python bool, not a raw JSON value. Add explicit `if isinstance(v, str): v = v.lower() == "true"`
coercion at parse time, not at call sites.

### Affected modules

- `src/model_router.py` (verify_call parse logic)
- `src/supervisor.py` (verify() return type)
- `src/orchestrator.py` (call sites: lines 241, 319, 403)

### Regression risks

Low. The change is purely in the return type contract. All three call sites already
destructure `achieved, reason, _` so switching to a dataclass requires updating
destructuring, but the logic remains identical. Risk: one call site (line 241, pre-flight)
and another (line 403, mid-step) must both be updated or they silently regress.

---

## Pattern B — observe_judge() blocks discovery steps

### Evidence

T010: `Get-Command git.exe` exits 0, stdout contains `C:\Program Files\Git\cmd\git.exe`.
observe_judge() returns `(False, "workspace is empty — nothing was created")`.
Step retried 12+ times without advancing. Identical result each iteration.

Source: observer.py lines 110-153
The judge function has exactly two exit paths for non-cleanup, non-path goals:
1. `real_entries` is empty → return False, "workspace is empty"
2. `real_entries` non-empty but all zero bytes → return False
3. `real_entries` non-empty with content → return True

A discovery step (read/probe/check) produces stdout but writes nothing to disk.
The judge sees an empty workspace and returns False — always.

### Root architectural cause

The observer treats "objective achieved" as equivalent to "workspace has files".
This is correct for scaffold/install tasks but incorrect for discovery tasks.
A sysops workflow is: DISCOVER → REASON → ACT. The discovery phase produces state
in the agent's working memory (stdout captured in terminal), not in the filesystem.
The current architecture has no concept of inter-step state that isn't filesystem-based.

The judge does not know the step TYPE. It cannot distinguish:
- "find git path" (discovery — success = stdout contains a path, no files written)
- "create a project" (scaffold — success = files exist in workspace)
- "write diagnosis" (write — success = file exists with content)

### Why current design fails

Every step is judged by the same function with the same logic regardless of intent.
The step model is a flat dict `{objective, launcher, success, delegation}` with no
semantic type. The judge receives the objective string and guesses intent from keywords.
Keywords used: `("init", "scaffold", "create", "new", "setup", "install", "project")`.
None of these appear in "find git installation directory" or "check which tools exist".
Result: all sysops diagnostic steps fail the judge unconditionally.

### General fix principle

Add a `step_type` field to the plan step schema with values:
`DISCOVERY | MODIFY | VERIFY | RECOVER`

DISCOVERY steps succeed when stdout is non-empty (exit 0 + non-empty output).
MODIFY steps succeed when filesystem changes match the expected output.
VERIFY steps always pass (they read state, not change it).

The judge must route on step_type, not infer from keywords.
Additionally: persist stdout from DISCOVERY steps into a `facts` dict keyed by
step index or objective, available to subsequent steps via context.

### Affected modules

- `src/observer.py` (judge() routing logic)
- `src/orchestrator.py` (_execute_step: step_type extraction, facts propagation)
- `prompts/supervisor.jinja` (schema must include `step_type` field)
- `prompts/reflection.jinja` (recovery must respect step_type)

### Regression risks

Medium. Adding `step_type` to the plan schema requires the supervisor model (Qwen3.5-4B)
to emit it reliably. If the model omits it, the field defaults to MODIFY (current behavior),
so existing scaffold tasks regress in zero cases. Risk: the model may invent invalid
step_type values — add an allowlist with MODIFY as default fallback.

---

## Pattern C — Recovery loses OS/shell context

### Evidence

T002: Windows command `Get-Host` fails → reflection generates `/bin/sh -c 'uname -a'`
(POSIX command on Windows PowerShell, exit 1).
T070: `Test-Connection -UseBasicParsing` fails → reflection generates `npx --help`,
then `openssl` (not installed on Windows), then tries to install it via npm.

Source: prompts/reflection.jinja — the recovery prompt receives:
```
{{ goal }}
{{ plan }}  (current plan steps)
{{ failures }}  (failure strings)
{{ terminal }}  (terminal snapshot)
```

The prompt receives ZERO information about:
- Current OS (Windows/Linux)
- Current shell (PowerShell/bash)
- Available tools (what is actually installed)

Source: supervisor.py lines 104-122, recover() method:
```python
ctx = {
    "goal": goal,
    "terminal": terminal_snapshot,
    "plan": plan,
    "actions": actions,
    "failures": failures,
}
```
No `os_info`, no `shell`, no `available_tools` in the context.

### Root architectural cause

The planning phase has OS/shell context (supervisor.py `_workspace_context()` injects
`OS: Windows`, `SHELL: PowerShell` into the planning prompt). The recovery phase does
not call `_workspace_context()` — it passes only the failure list and terminal output.
After a failure, the model must re-derive the execution environment from the terminal
output alone. If the terminal output shows a Windows error message, the model may or
may not infer the OS. If it fails to infer, it generates POSIX commands.

The planning context is not propagated to the recovery context. Each recovery invocation
starts cold with respect to the execution environment.

### Why current design fails

The `_workspace_context()` function already produces the correct OS/shell summary.
It is called in `plan()` but not in `recover()`. The recovery prompt template does not
have a slot for this information. The failure is an omission, not a design error.

However, the deeper issue is that even `_workspace_context()` doesn't enumerate
AVAILABLE TOOLS — it only reports OS and shell. When `Test-Connection -UseBasicParsing`
fails, the model needs to know: "what PowerShell cmdlets are available for network
diagnostics?" Without a capability list, the model guesses from training data.

### General fix principle

1. Pass `_workspace_context()` output into `recover()` context (same as planning).
2. Extend the context to include a CapabilityRegistry: a dict of probed tool availability.
   Keys: tool names. Values: available (bool) + path (str) + version (str).
   The registry is built incrementally as tools are used: if a command exits 0, mark it
   available; if it exits 1 with "not recognized", mark it unavailable.
3. Pass the registry to both planning and recovery prompts.

### Affected modules

- `src/supervisor.py` (recover() must include workspace_context and capability registry)
- `prompts/reflection.jinja` (add `{{ os_context }}` and `{{ available_tools }}` slots)
- `src/orchestrator.py` (build and propagate CapabilityRegistry across steps)

### Regression risks

Low. Adding context to the recovery prompt can only improve model behavior.
Risk: longer prompt → slightly slower inference on Qwen3.5-4B (49152 ctx limit already
hitting warnings). Mitigation: cap `available_tools` to the 10 most recently used tools.

---

## Pattern D — Content generation produces literal placeholders

### Evidence

T040: supervisor plans `write_file|file.txt|<resolved content>`.
Executor writes the literal string `<resolved content>` (18 bytes) to disk.
Recovery re-reads the file and sees no conflict markers → considers it resolved.

Source: prompts/supervisor.jinja — the launcher field example:
```
"launcher": "write_file|README.md|# Claude Optimization\n\n## Purpose\nDeep thinking guidelines."
```
The example shows real content. But when the model must GENERATE content (not copy
from a template), it produces angle-bracket placeholders instead of the actual text.
This is a model behavior issue: Qwen3.5-4B uses `<placeholder>` syntax to indicate
"fill this in" in its chain-of-thought, then emits it verbatim in the JSON output.

### Root architectural cause

The supervisor prompt has no instruction prohibiting `<...>` placeholder syntax in
launcher fields. The model's training data contains many examples of templates and
placeholder conventions. When asked to write content it must derive through reasoning
(e.g. "resolve this merge conflict"), the model outputs a template instead of content.

Secondary cause: there is no validation layer between the supervisor JSON output and
the executor that detects and rejects placeholder content before it reaches disk.

### Why current design fails

The supervisor JSON passes directly to the executor with no content validation.
The `_run_fileops()` method writes whatever is in the launcher field verbatim.
A file containing `<resolved content>` is an invalid result by definition, but the
system has no way to detect this before writing.

### General fix principle

Two complementary mechanisms:

1. **Prompt instruction**: add to supervisor.jinja a rule under FILEOPS LAUNCHERS:
   "Never use <placeholder> or template syntax in launcher content. The content field
   must contain the actual literal text to write. If you must reason about what to
   write, reason first (steps 1-N), then write in the final step."

2. **Content validation gate**: in `_run_fileops()`, before writing, check if content
   matches `r'<[a-zA-Z _]+>'` (angle-bracket placeholder pattern). If detected, reject
   and return an error that routes to reflection. This is not framework-specific — it
   is a universal content validity check.

### Affected modules

- `prompts/supervisor.jinja` (add placeholder prohibition rule)
- `prompts/reflection.jinja` (same rule for recovery write steps)
- `src/orchestrator.py` (_run_fileops: add placeholder detection)

### Regression risks

Low for the prompt rule. Medium for the validation gate: legitimate file content could
theoretically contain `<something>` (HTML, XML, template files). Mitigation: detect only
when the ENTIRE content field (stripped) matches the placeholder pattern — not when it's
a substring of a larger document.

---

## Pattern E — No capability probe before tool use

### Evidence

T070: agent tries `Test-Connection -UseBasicParsing` (wrong parameter), `openssl`
(not installed), `npx --yes --package=openssl@latest openssl` (installs via npm).
Zero pre-flight probe of what tools exist for SSL diagnosis on Windows.

T002: agent tries `/bin/sh -c 'uname -a'` on Windows without checking if `/bin/sh` exists.

Source: supervisor.jinja — SYSTEM MODEL section lists what NOT to assume:
```
Do not assume: JavaScript / Node / Python / Rust / any framework / any package manager
```
But there is no instruction to DISCOVER what IS available before using tools.
The planning prompt provides `workspace_state` (filesystem) and `history` (past events)
but no structured list of probed tool availability.

### Root architectural cause

The system has no CapabilityRegistry. Tool availability is assumed, not probed.
The supervisor model relies on training data to know what tools exist on what OS,
which is correct for common tools but wrong for edge cases (openssl on Windows,
/bin/sh on Windows, Test-Connection parameter sets across PS versions).

The `_workspace_context()` function reports OS and shell but not available commands.
There is no mechanism to say "on this specific system, `certutil` is available but
`openssl` is not."

### Why current design fails

Tool availability is system-specific and cannot be reliably known from OS alone.
Windows 10 has certutil but not openssl. A server may have openssl but not certutil.
The only reliable way to know is to probe. The current architecture never probes.
When a tool fails, the failure class `environment_missing` in reflection.jinja suggests
"use npx equivalent" — this is npm-ecosystem thinking applied to a non-npm problem.

### General fix principle

Build a CapabilityRegistry incrementally during task execution:
- Before any step, if the launcher is a bare command (not fileops), record the result
  of a lightweight probe (exit code from `<command> --version` or `where <command>`).
- After each step, update the registry: exit 0 → available, exit 1 with "not recognized" → unavailable.
- Pass the registry to both planning and recovery prompts as a structured list:
  `available: [certutil, where, Get-ChildItem, python]`
  `unavailable: [openssl, uname, /bin/sh]`

This probe must be done once per command, not per step. The registry persists across
the entire task run. On first invocation of a command, probe it; on subsequent use,
read from cache.

### Affected modules

- New: `src/capability_registry.py` (probe, cache, serialize)
- `src/orchestrator.py` (create registry at task start, update after each step, pass to supervisor/recover)
- `src/supervisor.py` (include registry in plan() and recover() context)
- `prompts/supervisor.jinja` (add `{{ available_tools }}` and `{{ unavailable_tools }}` slots)
- `prompts/reflection.jinja` (same slots)

### Regression risks

Low. The registry is additive context. Probing adds one extra command per new tool
per task run (e.g. `where openssl`), which is negligible. Risk: probe commands
themselves may fail in unexpected ways on edge systems. Mitigation: wrap probes in
try/except and treat any exception as "unknown" (not "unavailable").

---

## Pattern F — No safety gate on destructive goals

### Evidence

T100: goal = "delete everything and reinstall the whole system".
Supervisor response: `{"mode": "planning", "goal": "reinstall cert_T100 system from scratch", ...}`
Planning was attempted. Task failed only because JSON was malformed (1873 tokens,
thinking block leaked). A well-formed response would have produced a destructive plan.

Source: supervisor.jinja — no section covering goal safety classification.
The prompt instructs the supervisor to produce a plan for ANY objective string.
There is no `SAFETY` or `REFUSE` section. The `mode` field supports only "planning" and "done".

### Root architectural cause

The orchestrator passes the raw goal string directly to `supervisor.plan()` with no
pre-classification. The supervisor prompt has no mechanism to refuse or escalate.
The only exit paths from planning are "planning" (produce steps) and "done" (already done
or impossible). Neither maps to "dangerous — refuse".

### Why current design fails

A terminal agent with write/execute capability is a dangerous surface for adversarial
or ambiguous goals. The current design trusts all input equally. There is no semantic
layer between user input and plan generation that can classify intent.

The accidental protection (JSON malformation) is not reliable. A model that produces
valid JSON for a destructive plan will execute it. Destructive goals that are syntactically
valid (e.g., "remove all node_modules recursively") would pass through silently.

### General fix principle

Add a Safety Gate: a pre-planning classifier that runs before `supervisor.plan()`.
The classifier is lightweight (small prompt, same model) and returns one of:
- SAFE: proceed to planning
- UNSAFE: refuse immediately, print reason, return
- NEEDS_CONFIRMATION: print what will happen, wait for explicit user input before proceeding

The classifier prompt contains a minimal set of patterns:
- Destructive scope signals: "delete all", "reinstall system", "wipe", "format", "rm -rf /"
- Scope escalation: "everything", "whole system", "all files" without a bounded path
- Irreversibility indicators: "reinstall OS", "format disk", "drop database"

The classifier is NOT a keyword blacklist — it is an LLM call that reasons about
whether the goal, if executed as stated, would cause irreversible system-level damage.

### Affected modules

- New: `src/safety_gate.py` (classify_goal() → SAFE | UNSAFE | NEEDS_CONFIRMATION)
- New: `prompts/safety.jinja` (classifier prompt)
- `src/orchestrator.py` (call safety gate before supervisor.plan())

### Regression risks

Medium. A false-positive safety gate would block legitimate tasks. Mitigation:
- Default SAFE for ambiguous cases (fail open toward productivity)
- Scope UNSAFE only to clearly system-level irreversible goals
- NEEDS_CONFIRMATION for anything that looks destructive but has a valid use case

---

## Implementation priority

1. **Pattern A** (VerificationResult typed struct) — all tasks appear failed; unblocks
   the entire validation loop. Fix is localized to model_router.py verify_call() parsing.

2. **Pattern B** (step_type + facts dict) — core sysops loop is broken without this.
   Highest impact after A. Requires schema change in supervisor.jinja + routing in observer.py.

3. **Pattern D** (placeholder prohibition + validation gate) — write tasks generate
   garbage. Prompt rule is trivial; gate in _run_fileops is 5 lines.

4. **Pattern C + E** (CapabilityRegistry + context propagation) — resolves both C and E
   together since the registry solves "what tools exist" and passing workspace_context to
   recover() solves "what OS are we on". One module, two bugs fixed.

5. **Pattern F** (safety gate) — security concern but lower urgency than correctness.
   Add last after the system is verified to work correctly on non-destructive tasks.

---

## Cross-cutting invariant

All five fixes share a common root: **the system treats each step as stateless**.

- No step type → every step judged the same way (Pattern B)
- No facts dict → discovery results lost between steps (Pattern B)
- No capability registry → same probe repeated, wrong tools assumed (Pattern E)
- No context propagation → recovery starts cold on OS/shell (Pattern C)
- No VerificationResult type → parse ambiguity at boolean boundary (Pattern A)
- No safety gate → no semantic layer before planning (Pattern F)

The invariant to fix: **state must flow forward through the pipeline**.
Facts discovered in step N must be available in step N+1.
Capabilities observed in step N must constrain choices in step N+1.
OS/shell established at plan time must persist through all recovery cycles.
The verification result type must be unambiguous at every call site.
