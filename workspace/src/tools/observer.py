"""
Filesystem observer.

Responsibility: read the real filesystem and produce a structured snapshot.
The LLM (supervisor / reflection) decides whether the objective is achieved
by evaluating that snapshot against the success criteria it defined.

This module never hard-codes framework names, file patterns, or tool-specific
knowledge. It just reads what is on disk and reports it faithfully.
"""

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .session import Session


# ── Public API ───────────────────────────────────────────────────────────────


def observe(objective: str, session: "Session") -> str:
    """Produce a structured snapshot of the workspace for the LLM to evaluate."""
    ws = session.workspace
    lines = [f"workspace: {ws}"]

    # Directory listing — full picture so the LLM can reason about it
    try:
        entries = sorted(ws.iterdir(), key=lambda x: (x.is_dir(), x.name))
        lines.append("contents:")
        for e in entries[:60]:
            kind = "dir" if e.is_dir() else "file"
            size = "" if e.is_dir() else f"  ({e.stat().st_size}B)"
            lines.append(f"  {kind}  {e.name}{size}")
        if len(entries) > 60:
            lines.append(f"  ... ({len(entries)} total)")
    except Exception as exc:
        lines.append(f"  (listing failed: {exc})")

    # One level deep — some tools scaffold into a subdirectory
    try:
        for sub in ws.iterdir():
            if sub.is_dir() and not sub.name.startswith(".") and sub.name != "node_modules":
                sub_entries = list(sub.iterdir())
                if sub_entries:
                    names = ", ".join(e.name for e in sub_entries[:10])
                    lines.append(f"  {sub.name}/ → {names}")
    except Exception:
        pass

    # Explicitly list executables in tool-environment runtime dirs (e.g. .venv/Scripts/).
    # Dot-prefixed dirs are excluded from the listing above, so we add them here so
    # the verifier can confirm executables like .venv/Scripts/python.exe exist.
    try:
        for sub in ws.iterdir():
            if not sub.is_dir() or not sub.name.startswith("."):
                continue
            for runtime_subdir in ("Scripts", "bin"):
                rt = sub / runtime_subdir
                if rt.is_dir():
                    exes = sorted(e.name for e in rt.iterdir() if e.is_file())[:10]
                    if exes:
                        lines.append(f"  {sub.name}/{runtime_subdir}/ → {', '.join(exes)}")
    except Exception:
        pass

    # Python venv installed packages — list dist-info names from site-packages.
    # Works for both Windows (Lib/site-packages) and Unix (lib/pythonX.Y/site-packages).
    try:
        for sub in sorted(ws.iterdir()):
            if not sub.is_dir():
                continue
            sp_dirs = []
            if (sub / "Lib" / "site-packages").is_dir():
                sp_dirs.append(sub / "Lib" / "site-packages")
            lib_dir = sub / "lib"
            if lib_dir.is_dir():
                for d in lib_dir.iterdir():
                    sp = d / "site-packages"
                    if sp.is_dir():
                        sp_dirs.append(sp)
            for sp in sp_dirs:
                dist_pkgs = sorted(
                    e.name.split("-")[0] for e in sp.iterdir() if e.name.endswith(".dist-info")
                )
                if dist_pkgs:
                    lines.append(f"{sub.name}/ installed packages: " + ", ".join(dist_pkgs[:30]))
    except Exception:
        pass

    # package.json deps — useful context for the LLM
    pkg = ws / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            if deps:
                lines.append(
                    f"package.json deps ({len(deps)}): " + ", ".join(list(deps.keys())[:20])
                )
        except Exception:
            pass

    # Any manifest / config file content snippets for context
    for name in ("Cargo.toml", "pyproject.toml", "go.mod"):
        p = ws / name
        if p.exists():
            try:
                head = p.read_text(encoding="utf-8", errors="replace")[:200]
                lines.append(f"{name}: {head.strip()[:120]}")
            except Exception:
                pass

    # Content previews of small text files. The verifier cannot judge a
    # "write findings to X.txt" task without seeing what X.txt contains.
    # We show a short preview of each small, non-hidden text file so the
    # OBSERVE phase reports enough state to actually VERIFY. Generic — no
    # filename or task assumptions.
    previews = _text_file_previews(ws)
    if previews:
        lines.append("file contents:")
        lines.extend(previews)

    return "\n".join(lines)


# Text file extensions whose content is meaningful to a verifier. Binary files
# are never previewed. This is a portable content-type heuristic, not a catalog.
_TEXT_EXT = {
    # config / data
    ".txt",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".env",
    ".log",
    ".csv",
    ".xml",
    ".properties",
    # source code — content previews let the verifier catch corrupted files
    # (e.g. literal \n instead of newlines, empty stubs, wrong content)
    ".py",
    ".js",
    ".ts",
    ".sh",
    ".bash",
    ".rs",
    ".go",
    ".rb",
    ".lua",
    ".jsx",
    ".tsx",
    ".java",
    ".c",
    ".cpp",
    ".h",
    "",
}
_PREVIEW_MAX_BYTES = 4000


def _text_file_previews(ws: "Path") -> list[str]:
    out = []
    try:
        for e in sorted(ws.iterdir(), key=lambda x: x.name):
            if not e.is_file() or e.name.startswith("."):
                continue
            if e.suffix.lower() not in _TEXT_EXT:
                continue
            try:
                size = e.stat().st_size
            except Exception:
                continue
            if size == 0 or size > _PREVIEW_MAX_BYTES:
                continue
            try:
                text = e.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            snippet = text.strip()[:600]
            indented = "\n".join("    " + ln for ln in snippet.splitlines())
            out.append(f"  --- {e.name} ({size}B) ---\n{indented}")
    except Exception:
        pass
    return out


def judge(
    objective: str,
    observation: str,
    session: "Session",
    step_type: str = "MODIFY",
    stdout: str = "",
    pre_check: bool = False,
    exit_code: int | None = None,
) -> tuple[bool, str]:
    """
    Evaluate whether the objective is achieved.

    Routes on step_type:
      DISCOVERY — success when the command SUCCEEDED and produced usable output
      MODIFY    — success when workspace has real content matching the goal
      VERIFY    — always passes (pure read, no state change)
      RECOVER   — same as MODIFY
    """
    if step_type == "DISCOVERY":
        # A command that failed discovered nothing. This used to be decided by sniffing the
        # output for error-shaped text, and the sniffer was fooled: `npm install -g vite`
        # exited 1 with `npm error code EPERM`, which is non-empty text, and the step was
        # marked "✓ Step complete". A non-zero exit is a fact; error-shaped text is a guess.
        # The text filter stays, for the shells that report failure with exit 0.
        if exit_code not in (None, 0):
            return False, f"discovery command failed (exit {exit_code}) — nothing was discovered"
        out = (stdout or "").strip()
        if not out:
            return False, "discovery step produced no output"
        # Some shells (PowerShell non-terminating errors, warnings) exit 0 on failure.
        clean = _strip_error_noise(out)
        if not clean:
            return False, "discovery output is only error/warning text — no usable data"
        return True, f"discovery produced output ({len(clean)} chars)"

    if step_type == "VERIFY":
        # Judge cannot inspect exit code here — that check happens in the orchestrator.
        # Return passthrough so the orchestrator decides based on run_ok.
        return True, "verify step — check command exit code"

    ws = session.workspace

    # ── Cleanup / delete objective ────────────────────────────────────────
    obj = objective.lower()
    is_cleanup = any(
        kw in obj for kw in ("empty", "clean", "delete all", "remove all", "clear", "wipe")
    )
    is_scaffold = any(
        kw in obj for kw in ("init", "scaffold", "create", "new", "setup", "install", "project")
    )
    if is_cleanup and not is_scaffold:
        try:
            empty = not any(ws.iterdir())
        except Exception:
            empty = False
        reason = "workspace is empty" if empty else "workspace still has content"
        return empty, reason

    # ── Explicit path operations ──────────────────────────────────────────
    path_in_obj = _extract_path(objective)
    if path_in_obj:
        p = Path(path_in_obj)
        if any(kw in obj for kw in ("mkdir", "make dir", "make directory")):
            return p.exists(), f"{p} {'exists' if p.exists() else 'missing'}"
        if any(kw in obj for kw in ("delete", "remove")):
            return not p.exists(), f"{p} {'gone' if not p.exists() else 'still exists'}"

    # ── Scaffold / init objective: workspace must have real content ───────
    # pre_check=True: called BEFORE running the tool to detect "already done".
    # For this we need SPECIFIC evidence matching the step, not just any content.
    # The coarse "workspace has content" check is only valid post-execution.
    if pre_check:
        # Only pass pre-check if there's a specific path artifact we can verify.
        return False, "pre-check: no specific artifact found"

    # We do not know which files a specific tool creates — that is the LLM's
    # knowledge. We only check: did anything land on disk?
    try:
        entries = list(ws.iterdir())
    except Exception:
        return False, "cannot read workspace"

    # Filter out only node_modules (dependency cache, never a project artifact).
    # Dot-prefixed entries (.venv, .git, .next, .gitignore) are real tool/project
    # artifacts and must NOT be excluded — hiding them produces false "empty" verdicts.
    real_entries = [e for e in entries if e.name not in ("node_modules",)]

    if not real_entries:
        return False, "workspace is empty — nothing was created"

    # If the only thing present is a single non-dot subdirectory, the tool
    # scaffolded into a nested folder instead of directly into the workspace root.
    # Dot-prefixed directories (.venv, .git, etc.) are tool environment dirs, not
    # scaffolding mistakes, so we skip the check for them.
    # Also skip directories that look like tool environments (have Scripts/ or bin/
    # with executables) — these are intentional artifacts, not scaffolding errors.
    # VCS metadata (.git) is excluded from THIS check only: it is never itself
    # "the project", so its mere presence must not mask a genuinely misplaced
    # scaffold sitting alongside it (observed: a scaffold nested itself while
    # .git was still present — len(real_entries)==2 — so this check never fired
    # until a far more expensive final verify pass, three steps later).
    _scaffold_candidates = [e for e in real_entries if e.name != ".git"]
    if (
        len(_scaffold_candidates) == 1
        and _scaffold_candidates[0].is_dir()
        and not _scaffold_candidates[0].name.startswith(".")
        and not _is_tool_env_dir(_scaffold_candidates[0])
    ):
        sub_content = list(_scaffold_candidates[0].iterdir())
        if not sub_content:
            return False, f"only empty subdirectory {_scaffold_candidates[0].name}/ was created"
        names = ", ".join(e.name for e in sub_content[:5])
        return False, (
            f"project was created inside {_scaffold_candidates[0].name}/ instead of workspace root — "
            f"must move contents up one level. Contents: {names}"
        )

    # Files exist but may all be 0 bytes — check that at least one has real content.
    # A directory with any children counts as non-empty (e.g. node_modules, src/).
    has_content = any(
        (e.is_dir() and any(e.iterdir())) or (e.is_file() and e.stat().st_size > 0)
        for e in real_entries
    )
    if not has_content:
        names = ", ".join(e.name for e in real_entries[:8])
        return False, f"files exist but are all empty (0B): {names}"

    names = ", ".join(e.name for e in real_entries[:8])
    return True, names


def _is_tool_env_dir(path) -> bool:
    """True if directory is a tool runtime environment (venv, conda env, etc.).
    Invariant: environments have a bin/ or Scripts/ subdir containing executables.
    """
    from pathlib import Path as _Path

    p = _Path(path)
    for subname in ("Scripts", "bin"):
        sub = p / subname
        if sub.is_dir() and any(f.is_file() for f in sub.iterdir()):
            return True
    return False


# ── Helpers ───────────────────────────────────────────────────────────────────

# Portable error/warning signatures — not tied to any shell or framework.
_ERROR_SIGNATURES = (
    "is not recognized",
    "not recognized as",
    "command not found",
    "cannot be found",
    "cannot find",
    "no such file",
    ": error",
    "error:",
    "exception",
    "parsererror",
    "is not a cmdlet",
    "missing terminator",
    "missing expression",
    "a parameter cannot be found",
    "unexpected token",
)


def _strip_error_noise(text: str) -> str:
    """
    Return the lines of `text` that are NOT error/warning noise.
    If every line is an error signature, returns "" — meaning the output
    carried no usable discovered data.
    """
    usable = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        low = line.lower()
        if any(sig in low for sig in _ERROR_SIGNATURES):
            continue
        # PowerShell error position markers ("+ ...", "At line:1 char:..")
        if low.startswith(("at line:", "+ ", "+ category", "+ fullyqualified")):
            continue
        usable.append(stripped)
    return "\n".join(usable).strip()


def _extract_path(text: str) -> str:
    m = re.search(r"[A-Za-z]:[/\\][^\s,;\'\"]+", text)
    if m:
        return re.sub(r"[.,;\'\"]+$", "", m.group(0))
    m = re.search(r"/[^\s,;\'\"]+", text)
    if m:
        return re.sub(r"[.,;\'\"]+$", "", m.group(0))
    return ""
