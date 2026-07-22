"""Supervisor: defines WHAT, not HOW. Returns goal/constraints/success/plan."""

from . import memory, model_router
from .redact import is_secret_file
from .tools import predicates
from .tools.observer import observe


def _workspace_context(cwd: str) -> str:
    """
    Build a rich, unambiguous context about the workspace so the supervisor
    does not need to guess or re-derive what already exists.

    Includes: existence, emptiness, OS, shell, file listing, inferred project type.
    """
    import sys as _sys
    from pathlib import Path

    p = Path(cwd)
    lines = []

    # Existence and emptiness — explicit, never ambiguous
    if not p.exists():
        lines.append("WORKSPACE_EXISTS: no")
        lines.append("ACTION_REQUIRED: create the workspace directory first")
        return "\n".join(lines)

    lines.append("WORKSPACE_EXISTS: yes")
    lines.append(f"WORKSPACE_PATH: {p}")
    lines.append(f"WORKSPACE_NAME: {p.name}")

    # OS and shell — executor uses these to pick correct commands
    if _sys.platform == "win32":
        lines.append("OS: Windows")
        lines.append("SHELL: PowerShell")
        lines.append("FILE_CREATE_CMD: New-Item <name> -ItemType File")
        lines.append("MULTI_FILE_CMD: New-Item file1.md,file2.md -ItemType File")
    else:
        lines.append("OS: Linux/macOS")
        lines.append("SHELL: bash")
        lines.append("FILE_CREATE_CMD: touch <name>")
        lines.append("MULTI_FILE_CMD: touch file1.md file2.md file3.md")

    # Contents
    try:
        entries = sorted(p.iterdir(), key=lambda x: (x.is_dir(), x.name))
        if not entries:
            lines.append("WORKSPACE_STATE: empty — no files or directories exist yet")
        else:
            lines.append(f"WORKSPACE_STATE: contains {len(entries)} items")
            for e in entries[:40]:
                if not e.is_dir() and is_secret_file(e.name):
                    # The NAME stays: a sysops agent legitimately needs to know a `.env` is
                    # present in order to plan around it. The SIZE does not — file length is
                    # an information leak about a secret, and this listing is interpolated
                    # into every planner prompt, which reaches a remote oracle when one is
                    # configured. The marker also tells the planner not to try reading it.
                    lines.append(f"  FILE {e.name} (credential store — never read its contents)")
                    continue
                size = "" if e.is_dir() else f" ({e.stat().st_size}B)"
                lines.append(f"  {'DIR ' if e.is_dir() else 'FILE'} {e.name}{size}")
            if len(entries) > 40:
                lines.append(f"  ... ({len(entries)} total)")
    except Exception as exc:
        lines.append(f"WORKSPACE_STATE: (listing failed: {exc})")

    # Inferred project type from existing files — helps supervisor plan correctly
    indicators = {
        "package.json": "Node.js project",
        "Cargo.toml": "Rust project",
        "pyproject.toml": "Python project",
        "go.mod": "Go project",
        "CLAUDE.md": "Claude Code project",
        ".claude": "Claude Code configuration directory",
        "requirements.txt": "Python project",
        "angular.json": "Angular project",
    }
    detected = [label for fname, label in indicators.items() if (p / fname).exists()]
    if detected:
        lines.append(f"DETECTED_CONTEXT: {', '.join(detected)}")

    # Virtual environment detection — tell the supervisor which pip/python to use.
    # Invariant: a project venv is the authoritative install target; bare `pip`
    # resolves to system pip when no venv is activated, which installs in the
    # wrong location and may silently appear to succeed.
    for venv_name in (".venv", "venv"):
        venv = p / venv_name
        if not venv.is_dir():
            continue
        if _sys.platform == "win32":
            pip_path = venv / "Scripts" / "pip.exe"
            py_path = venv / "Scripts" / "python.exe"
        else:
            pip_path = venv / "bin" / "pip"
            py_path = venv / "bin" / "python"
        if pip_path.exists():
            lines.append(f"VENV_DETECTED: {venv_name}/")
            lines.append(f"VENV_PIP: {pip_path}")
            lines.append(f"VENV_PYTHON: {py_path}")
            lines.append("VENV_RULE: ALWAYS use VENV_PIP for pip install — never bare 'pip'")
            break

    return "\n".join(lines)


class Supervisor:
    def plan(
        self, goal: str, cwd: str, terminal_snapshot: str, failure_reason: str = "", sysstate=None
    ) -> dict:
        ws_ctx = _workspace_context(cwd)

        # Prepend the workspace snapshot so the supervisor sees what already exists
        # BEFORE generating any plan. This prevents planning steps that redo work
        # already done or make wrong assumptions about the workspace state.
        if sysstate is not None:
            _snap_fact = sysstate.facts.get("workspace_snapshot")
            if _snap_fact and _snap_fact.value:
                ws_ctx = _snap_fact.value + "\n\n" + ws_ctx

        if failure_reason:
            # Inject the verified failure reason directly into the workspace context
            # so the model cannot ignore it. Without this, the model sees "DONE: write X
            # and Y → success" in event history and returns an empty recovery plan.
            ws_ctx += (
                f"\n\nVERIFICATION_FAILURE: {failure_reason}\n"
                "The above gap was detected by automatic verification after all steps "
                "completed. You MUST produce a plan that addresses exactly this gap. "
                "Do not return mode=done."
            )
        # Reasoning context: ranked, token-budgeted constraints + beliefs + failed assumptions
        reasoning_ctx = ""
        if sysstate is not None and getattr(sysstate, "reasoning", None) is not None:
            try:
                reasoning_ctx = sysstate.reasoning.get_prompt_context()
            except Exception:
                pass
        # OCKE: extract the platform knowledge block stored as a fact in sysstate.
        # This tells the supervisor exactly what tools exist, what is forbidden, and
        # what the knowledge memory says about past attempts — preventing LLM hallucination
        # of wrong-platform commands (e.g. `apt` on Windows, `sudo` in PowerShell).
        ocke_block = ""
        system_spec = ""
        if sysstate is not None:
            _f = sysstate.facts.get("ocke_context")
            if _f:
                ocke_block = _f.value
            # SYSTEM_SPEC: deterministic TODAY + installed-version block, injected
            # mechanically so every plan is grounded on the live machine, not the
            # model's training era.
            _sf = sysstate.facts.get("system_spec")
            if _sf:
                system_spec = _sf.value

        # SPECIALIST_BRIEF: the one-time prompt_enhancer output (role + refined
        # objective + key considerations for THIS request). The planner is framed
        # by this before it ever reasons about the raw goal — see prompt_enhancer.py.
        task_brief = ""
        if sysstate is not None:
            _tb = sysstate.facts.get("task_brief")
            if _tb:
                task_brief = _tb.value

        # RESEARCH NOTES: what prior DISCOVERY steps (web_search, probes) found.
        # Fed to the planner so a re-plan uses what was learned instead of guessing
        # the same wrong command again (the DISCOVERY→re-plan channel).
        research_notes = ""
        if sysstate is not None:
            _notes = [
                f.value.strip()
                for k, f in sysstate.facts.items()
                if k.startswith("discovery::") and f.value.strip()
            ]
            if _notes:
                research_notes = "\n".join(_notes)[:1500]

        ctx = {
            "goal": goal,
            "cwd": cwd,
            "system_spec": system_spec,
            "task_brief": task_brief,
            "research_notes": research_notes,
            "workspace_state": ws_ctx,
            "terminal": terminal_snapshot,
            "history": memory.get_recent_events(),
            "memory": (
                memory.get_summary()
                + ("\n\n" + reasoning_ctx if reasoning_ctx else "")
                + ("\n\n" + ocke_block if ocke_block else "")
            ),
        }
        return model_router.supervisor_call(ctx)

    def verify(
        self,
        objective: str,
        session,
        success_criteria: list[str] | None = None,
        command_output: str | None = None,
    ) -> tuple[bool, str, str]:
        """
        Ask the supervisor model to evaluate whether a step's objective was achieved.
        Returns (achieved, reason, corrective_action).

        When success_criteria are provided (from the plan's 'success' field), they
        are injected as the highest-priority check. The LLM must satisfy ALL listed
        criteria — not just judge by vibe or partial structure.
        command_output, when provided, is the stdout of the command just run and
        takes precedence over filesystem inference.
        """
        from pathlib import Path as _Path

        ws = _Path(session.workspace)
        # Filesystem-root workspaces (C:\, /, /root) produce misleading snapshots:
        # they show every directory and .venv on the machine, not the target artifact.
        # When the workspace is a root, suppress the snapshot and rely on command_output.
        _is_fs_root = (
            ws == ws.anchor  # C:\ on Windows, / on Unix
            or str(ws).rstrip("/\\") in ("C:", "/root", "/home")
            or len(ws.parts) <= 2  # e.g. C:\Users — still too shallow
        )
        if _is_fs_root:
            snapshot = (
                f"WORKSPACE is a filesystem root ({ws}) — snapshot suppressed to avoid "
                "confusion with unrelated project directories visible on this machine. "
                "Use COMMAND OUTPUT exclusively to judge success."
            )
        else:
            snapshot = observe(objective, session)
        ctx = {
            "objective": objective,
            "workspace": str(ws),
            "snapshot": snapshot,
            "success_criteria": "\n".join(
                f"- {c}" for c in predicates.render(success_criteria or [])
            ),
            "command_output": (command_output or "")[:600],
        }
        result = model_router.verify_call(ctx)
        achieved = bool(result.get("achieved", False))
        reason = result.get("reason", "")
        action = result.get("action", "") if not achieved else ""
        return achieved, reason, action
