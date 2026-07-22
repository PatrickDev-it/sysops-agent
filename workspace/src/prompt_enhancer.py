"""Prompt Enhancer — single-call task specialization layer.

Runs ONCE per objective (before planning), reusing the SAME model as the
supervisor — this machine budgets 16GB RAM for the whole agent, so no second
GGUF is loaded and no per-field call loop is used. Turns the raw user request
into a short SPECIALIST_BRIEF: a role framing + refined objective + a handful
of concrete considerations, all INFERRED dynamically from THIS request.

Why: a small model activates the right knowledge when framed as a specialist
for the exact task at hand ("you are a sysops engineer specialized in X")
instead of reasoning as a generalist. The specialization text itself is never
hardcoded per technology in the .jinja templates (AGENTS.md forbids
per-framework cases there) — it is produced at runtime by the model, exactly
like system_spec/research_notes are produced at runtime rather than
hand-authored.

The compiled brief is what supervisor.jinja and executor.jinja are framed
with — neither model reasons from the raw request alone; this layer always
runs first.
"""

from . import config, model_router

_FALLBACK_ROLE = "You are a sysops engineer working only via the terminal."


def enhance(goal: str, system_spec: str = "") -> dict:
    """Produce the specialist brief for `goal`. Never raises — falls back to
    a generic sysops framing (with the raw goal as objective) if the model
    call fails or returns nothing usable, so a bad/empty model response never
    blocks the run. `SISTEMISTA_ENHANCER=0` skips the model call entirely and
    uses the fallback framing — the A/B knob for measuring whether this call
    earns its latency.
    """
    result: dict = {}
    if config.ENHANCER:
        try:
            result = model_router.enhance_call({"goal": goal, "system_spec": system_spec})
        except Exception:
            result = {}

    role = str(result.get("specialist_role") or "").strip() or _FALLBACK_ROLE
    objective = str(result.get("refined_objective") or "").strip() or goal.strip()
    considerations = [
        str(c).strip() for c in (result.get("key_considerations") or []) if str(c).strip()
    ][:5]

    return {
        "specialist_role": role,
        "refined_objective": objective,
        "key_considerations": considerations,
    }


def compile_brief(brief: dict) -> str:
    """Render the brief into the compact block injected into every
    downstream model prompt (supervisor + executor)."""
    lines = [
        "SPECIALIST_BRIEF (generated once for this task — this is your framing for everything below):",
        f"ROLE: {brief['specialist_role']}",
        f"OBJECTIVE: {brief['refined_objective']}",
    ]
    if brief["key_considerations"]:
        lines.append("KEY_CONSIDERATIONS:")
        lines.extend(f"  - {c}" for c in brief["key_considerations"])
    return "\n".join(lines)
