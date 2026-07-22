"""
System Spec — deterministic, mechanically-injected fingerprint of the live host.

Purpose: overcome the model's frozen-in-time / version-blind priors. Every prompt
receives, mechanically, TODAY's date + the actual OS/shell/tool versions of THIS
machine — so the model plans for the current reality, not its training era.

Single owner of "what the runtime knows about the host, right now" as a
prompt-injectable block. Probes tool versions once and caches for the run.
No framework names — only runtime observables (runtimes / package managers).
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import date
from typing import Optional

from .. import config

# Tools whose version materially changes HOW a task is done today. Only those
# actually present on PATH are probed. These are runtimes / package managers —
# the axes on which "the current way to do a thing" pivots — not a catalog.
_VERSIONED_TOOLS = [
    "node",
    "npm",
    "pnpm",
    "yarn",
    "bun",
    "python",
    "pip",
    "git",
    "cargo",
    "rustc",
    "go",
    "java",
    "docker",
    "uv",
]

_cached_block: Optional[str] = None


def _tool_version(tool: str) -> str:
    """Run `<tool> --version`, return first line trimmed, or '' on any failure."""
    exe = shutil.which(tool)
    if not exe:
        return ""
    try:
        r = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=4.0,
            errors="replace",
        )
        out = (r.stdout or r.stderr or "").strip()
        if not out:
            return ""
        first = out.splitlines()[0].strip()
        # Generic guard: a tool that rejects `--version` prints an error, not a
        # version. Drop it rather than surfacing noise (e.g. `go` wants `version`,
        # `java` wants `-version`). Not tool-specific — pure output shape.
        low = first.lower()
        if any(
            sig in low
            for sig in (
                "not defined",
                "unknown",
                "unrecognized",
                "invalid",
                "usage:",
                "no such",
            )
        ):
            return ""
        # Trim trailing provenance ("pip X from <path>") — keep the version head.
        first = first.split(" from ", 1)[0].strip()
        return first[:60]
    except Exception:
        return ""


def build(environment, force: bool = False) -> str:
    """
    Build the mechanically-injected SYSTEM_SPEC block for `environment`
    (a state.Environment). Probes tool versions once; caches for the run.

    The block is authoritative: it carries TODAY's real date and the exact
    installed versions, both of which override whatever the model assumes from
    training. It is injected into every model prompt, not left to the model to
    discover.
    """
    global _cached_block
    if _cached_block is not None and not force:
        return _cached_block

    # Live date by default; pinned under DETERMINISTIC so a benchmark is time-invariant.
    # Owner of the knob is config (alongside SEED); system_spec only reads it. See config.SPEC_DATE.
    today = config.SPEC_DATE or date.today().isoformat()
    year = today[:4]
    lines = [
        "SYSTEM_SPEC (deterministic live-host facts — authoritative over any training assumption):",
        f"  TODAY: {today}   (use THIS date and year {year}; never assume a year from training)",
        f"  OS: {environment.os_name} {environment.os_version}",
        f"  SHELL: {environment.shell}",
    ]
    versions = [f"  {t}: {v}" for t in _VERSIONED_TOOLS if (v := _tool_version(t))]
    if versions:
        lines.append("  INSTALLED_VERSIONS (plan for THESE exact versions, not older ones):")
        lines.extend(versions)
    lines.append(
        "  RULE: assume conventions, flags and defaults may have changed since your "
        f"training. Ground every choice on TODAY ({year}) + the versions above; when "
        "unsure of the current method, web_search WITHOUT hardcoding any year."
    )
    _cached_block = "\n".join(lines)
    return _cached_block


def reset() -> None:
    """Clear the cache (tests)."""
    global _cached_block
    _cached_block = None
