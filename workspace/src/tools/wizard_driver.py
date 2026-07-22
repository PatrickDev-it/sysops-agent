"""
Deterministic wizard drivers for known interactive tools.

When the supervisor specifies a known launcher, the orchestrator can bypass
the executor LLM entirely and derive stdin answers from the constraints.
This is more reliable than a 1.7B model guessing wizard prompts.
"""

import re
from pathlib import Path

# Launchers that CREATE a new directory — must run from the parent of the target.
_CREATES_DIR = {
    "create-next-app",
    "create-react-app",
    "create-vite",
    "create-astro",
    "create-vue",
    "create-svelte",
    "create-remix",
    "create-nuxt",
    "ng new",  # Angular CLI
    "cargo new",  # Rust
}

# Launchers that must run INSIDE an existing project root.
_NEEDS_PROJECT_ROOT = {
    "shadcn",
    "npm",
    "yarn",
    "pnpm",
    "git",
    "prisma",
    "turbo",
    "cargo init",  # cargo init runs inside existing dir
    "bun init",  # bun init runs inside existing dir
    "uv init",  # Python uv
    "poetry init",  # Python poetry
}

# Keywords that indicate a PTY-interactive wizard (needs the full PTY loop).
_INTERACTIVE_KEYWORDS = {
    "create-next-app",
    "shadcn",
    "create-react-app",
    "create-vite",
    "create-astro",
    "create-remix",
    "create-svelte",
    "sv create",  # SvelteKit
    "create-vue",  # Vue
    "ng new",  # Angular bare CLI
    "@angular/cli",  # Angular via npx (may still prompt for analytics/autocompletion)
    "bun create",  # Bun scaffolding
    "init",  # many tools: cargo init, bun init, uv init, poetry init
}


def is_interactive(launcher: str) -> bool:
    """True if the launcher opens an interactive PTY wizard that needs the full loop.

    Non-interactivity depends on the (tool, flag) pair — not on the flag alone.
    -y / --yes are universally non-interactive (npm/pnpm convention).
    --defaults is tool-specific: Angular respects it; create-vue ignores it.
    """
    lc = launcher.lower()

    # Tools that are ALWAYS batch regardless of flags
    _ALWAYS_BATCH_PREFIXES = ("cargo ", "python ", "pip ", "uv ", "rustup ")
    if any(lc.startswith(p) for p in _ALWAYS_BATCH_PREFIXES):
        return False

    # Universal non-interactive flags (npm/pnpm convention)
    if any(flag in lc for flag in (" -y", " --yes", " --no-interaction")):
        return False

    # Angular CLI: --defaults skips project questions but the process can still
    # prompt for unrelated things (autocompletion, analytics). Always run via PTY
    # so the state machine can answer any residual prompts with Enter.

    # Match keywords as whole tokens, not substrings — "init" must not match
    # "initialized" in file content embedded in a launcher string.
    import re as _re2

    if any(
        _re2.search(r"(?<![a-zA-Z0-9_-])" + _re2.escape(kw) + r"(?![a-zA-Z0-9_-])", lc)
        for kw in _INTERACTIVE_KEYWORDS
    ):
        return True

    # Any `npx create-*`, `npm create *`, or `pnpm create *` is an interactive
    # wizard by convention unless already handled above.
    import re as _re

    if _re.search(r"\bnpx\s+create-\S+|(?:npm|pnpm)\s+create\s+\S+", lc):
        return True

    return False


_CANONICAL: dict[str, str] = {
    # JS / TS
    "shadcn": "npx shadcn@latest init",
    "create-next-app": "npx create-next-app@latest",
    "create-react-app": "npx create-react-app",
    "create-vite": "npx create-vite",
    "create-vue": "npx create-vue@latest",
    # SvelteKit official CLI
    "sv create": "npx sv create",
    "create-svelte": "npx sv create",
    # Angular: v17 is the last version supporting Node 22.x (< 22.22.3)
    # @latest requires Node >= 22.22.3; v17 works with Node 18-22.13
    # --defaults skips all interactive questions; creates app/ subdirectory
    "ng new": "npx @angular/cli@17 new app --defaults",
    "@angular/cli": "npx @angular/cli@17 new app --defaults",
    # Bun — use -y to skip interactive prompts
    "bun create": "bun create",
    "bun init": "bun init -y",
    # Rust
    "cargo new": "cargo new",
    "cargo init": "cargo init",
    # Python — use non-interactive flags where possible
    "uv init": "uv init",
    "poetry new": "poetry new",
    "poetry init": "poetry init --no-interaction",
}


def _has_inline_flags(launcher: str) -> bool:
    """True if the launcher already contains meaningful option flags (-- or - prefixed args).

    When the supervisor has already specified inline flags, normalize_launcher
    must NOT strip them by replacing with the bare canonical form — the flags
    are the instruction and may make the tool non-interactive.
    """
    # Count tokens that look like flags (--flag or -f), excluding the base command tokens
    tokens = launcher.strip().split()
    # Skip the first 1-2 tokens (e.g. "npx", "create-next-app@latest")
    flag_tokens = [t for t in tokens[2:] if t.startswith("-")]
    return len(flag_tokens) >= 2


def normalize_launcher(launcher: str, objective: str = "") -> str:
    """
    Canonicalize launcher to its exact expected form.

    Key invariant: if the supervisor already provided inline flags (--ts, --tailwind, etc.),
    do NOT strip them. The canonical form is only used when the launcher is bare (no flags).
    A launcher with flags is already the instruction — replacing it with the canonical
    bare form would undo the flags and force interactive mode.
    """
    stripped = launcher.strip()
    lc = stripped.lower()

    # Convert Start-Process to synchronous direct invocation.
    # Start-Process is fire-and-forget by default — it exits 0 immediately
    # while the spawned process still runs, making verification unreliable.
    # Rewrite: Start-Process <cmd> -ArgumentList <a>, <b> → & <cmd> <a> <b>
    if lc.startswith("start-process "):
        import re as _re

        m = _re.match(
            r"Start-Process\s+(\S+)\s+-ArgumentList\s+(.*)",
            stripped,
            _re.IGNORECASE | _re.DOTALL,
        )
        if m:
            cmd = m.group(1)
            raw_args = m.group(2).strip()
            # Parse comma-separated quoted args: '-m', 'pip', 'install', 'pkg'
            args = _re.findall(r"['\"]([^'\"]*)['\"]|(\S+)", raw_args)
            flat_args = " ".join(a[0] or a[1] for a in args)
            stripped = f"& {cmd} {flat_args}".strip()
            lc = stripped.lower()

    # If the launcher already has meaningful inline flags, trust it as-is.
    # The supervisor explicitly chose those flags — do not replace with bare canonical.
    if _has_inline_flags(stripped):
        return stripped

    # Match known interactive tools by substring (longest match first to avoid
    # "init" matching before "cargo init" or "bun init")
    for key in sorted(_CANONICAL, key=len, reverse=True):
        if key in lc:
            canonical = _CANONICAL[key]
            # For non-interactive launchers that take a project name arg (cargo new, poetry new),
            # keep the canonical but preserve a trailing name arg if present in the original.
            if key in ("cargo new", "poetry new", "ng new"):
                # Extract project name from launcher or objective
                name = _extract_name_arg(stripped, objective)
                if name:
                    return f"{canonical} {name}"
            return canonical

    # `pnpm create <name>[@ver]` and `npm create <name>[@ver]` are equivalent to
    # `npx create-<name>[@ver]`. Normalize to the npx form so _CANONICAL matches.
    import re as _re

    m = _re.match(r"(?:pnpm|npm)\s+create\s+([\w@/.-]+)(.*)", stripped, _re.IGNORECASE)
    if m:
        pkg, rest = m.group(1), m.group(2).strip()
        # Strip any -- --defaults or similar trailing args that the model may add
        rest = _re.sub(r"\s*--\s*--\S+", "", rest).strip()
        # Convert `vue@latest` → `create-vue@latest`, `vue` → `create-vue@latest`
        name_part = pkg.split("@")[0]  # e.g. "vue"
        ver_part = ("@" + pkg.split("@")[1]) if "@" in pkg else "@latest"
        npx_form = f"npx create-{name_part}{ver_part}"
        if rest:
            npx_form = f"{npx_form} {rest}"
        # Recurse once to let _CANONICAL match the npx form
        return normalize_launcher(npx_form, objective)

    # Bare "npx" with framework hint in objective
    obj_lc = objective.lower()
    if lc == "npx":
        if "shadcn" in obj_lc:
            return "npx shadcn@latest init"
        if "vue" in obj_lc:
            return "npx create-vue@latest"
        if "svelte" in obj_lc:
            return "npx sv create"
        if "vite" in obj_lc:
            return "npx create-vite"

    return stripped


def _extract_name_arg(launcher: str, objective: str) -> str:
    """
    For launchers that take a project name arg (cargo new <name>, ng new <name>),
    extract the name from the launcher string or objective.
    Returns '' if no usable name found.
    """
    # Try to extract last non-flag token from launcher string
    parts = launcher.split()
    if len(parts) >= 3:
        last = parts[-1]
        if not last.startswith("-"):
            return last

    # Fall back to extracting from absolute path in objective
    m = re.search(r"[A-Za-z]:[/\\]([^\s,;\'\"]+)", objective)
    if m:
        return Path(re.sub(r"[.,;\'\"]+$", "", m.group(1))).name

    return ""


def resolve_cwd(launcher: str, goal: str, workspace: str) -> str:
    """
    Deterministically compute the working directory for a launcher.

    Rules (checked in order, filesystem-authoritative):
      1. Extract the target path from the goal text (first absolute path found).
      2. If the launcher creates a directory (create-next-app, cargo new, ng new, etc.):
           - target exists → use target (project already scaffolded, re-run in place)
           - target missing → use target's parent (tool will create the dir)
      3. If the launcher needs a project root (shadcn, npm, cargo init, bun init, etc.):
           - target exists → use target
           - target missing → use workspace (fallback)
      4. No path found in goal → use workspace.
    """
    target = _extract_target_path(goal)
    lc = launcher.lower()

    creates = any(k in lc for k in _CREATES_DIR)
    needs_root = any(k in lc for k in _NEEDS_PROJECT_ROOT)

    if target:
        p = Path(target)
        if creates:
            if not p.exists():
                return str(p.parent)
            else:
                # Target exists — run from INSIDE, scaffold in place with "."
                return str(p)
        if needs_root:
            return str(p) if p.exists() else workspace
        return str(p) if p.exists() else str(p.parent)

    # No path in goal — use workspace (for tools like `cargo init`, `bun init`,
    # `uv init`, `poetry init` that operate on the current directory)
    return workspace


def _is_empty_dir(p: Path) -> bool:
    """True if p is a directory with no files (ignoring hidden dot-files)."""
    if not p.is_dir():
        return False
    return not any(True for _ in p.iterdir())


def _extract_target_path(text: str) -> str:
    """Return the first absolute path found in text, or ''."""
    # Windows: C:\... or C:/...
    m = re.search(r"[A-Za-z]:[/\\][^\s,;\'\"]+", text)
    if m:
        # Strip trailing punctuation including > (appears in PS prompts: PS C:\path>)
        return re.sub(r"[.,;\'\">]+$", "", m.group(0))
    # Unix: /absolute/path — must start after whitespace or at line start to
    # exclude relative path fragments like `src/main.py` (where `/` is mid-word)
    m = re.search(r"(?:(?<=\s)|^)(/[^\s,;\'\"]+)", text)
    if m:
        return re.sub(r"[.,;\'\"]+$", "", m.group(1))
    return ""


def answers_for(
    launcher: str, objective: str, constraints: list[str], cwd: str
) -> list[str] | None:
    """
    Return ordered stdin lines for a known wizard, or None if not handled.
    Each string is one answer (no trailing newline — caller adds \\n separator).
    """
    lc = launcher.strip().lower()

    if "create-next-app" in lc:
        return _create_next_app(objective, constraints, cwd)
    if "shadcn" in lc:
        return _shadcn_init(objective, constraints, cwd)
    if "create-vue" in lc:
        return _create_vue(objective, constraints, cwd)
    if "sv create" in lc or "create-svelte" in lc:
        return _sv_create(objective, constraints, cwd)

    # For `cargo init`, `bun init`, `uv init`, `poetry init`, and `ng new`:
    # answers are driven by the state machine (project name + confirm prompts)
    # so return None to let the state machine handle it.
    return None


def _create_next_app(objective: str, constraints: list[str], cwd: str) -> list[str]:
    """
    npx create-next-app@latest wizard (Next.js 15+):
      1. Recommended defaults? → Enter (Yes)
      2. Project name → "." (scaffold in place)
    """
    return [
        "",  # Enter = Yes, use recommended defaults
        ".",  # scaffold in place
    ]


def _shadcn_init(objective: str, constraints: list[str], cwd: str) -> list[str]:
    """
    npx shadcn@latest init wizard:
      1. Select template → Enter (first = Next.js)
      2. Monorepo? → N
    """
    return [
        "",  # Enter = first option
        "N",  # No monorepo
    ]


def _create_vue(objective: str, constraints: list[str], cwd: str) -> list[str]:
    """
    npx create-vue@latest wizard:
      1. Project name → "."
      Then a series of Yes/No feature flags — accept defaults (Enter each)
    """
    return [
        ".",  # project name / scaffold in place
        "",  # TypeScript → No (default) or Enter
        "",  # JSX → No
        "",  # Router → No
        "",  # Pinia → No
        "",  # Vitest → No
        "",  # End-to-end testing → No
        "",  # ESLint → Yes
        "",  # Prettier → No
    ]


def _sv_create(objective: str, constraints: list[str], cwd: str) -> list[str]:
    """
    npx sv create wizard (SvelteKit CLI):
      1. Directory → "." (in place)
      2. Template → SvelteKit minimal (Enter)
      3. Type checking → yes, using TypeScript (Enter)
      4. Additional tools → none (Enter)
    """
    return [
        ".",  # directory
        "",  # template: minimal (first option)
        "",  # type checking: yes TypeScript (first option)
        "",  # additional tools: none
    ]
