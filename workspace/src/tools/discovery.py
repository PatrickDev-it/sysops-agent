"""
Bounded Discovery — finds executables and tools in priority order.

Priority (lowest cost first, highest reliability first):
  1. shutil.which()           — portable, instant, no shell
  2. PATH scan                — iterate PATH entries directly
  3. Get-Command / which      — shell probe (Windows / Unix)
  4. Registry                 — Windows App Paths (for GUI-installed tools)
  5. pip show / npm list      — package managers
  6. Bounded filesystem scan  — LAST RESORT, max depth 3, known install dirs only

Invariant: filesystem recursion from root (C://) is NEVER used.
The function aborts after each tier if the tool is found.

Design note: no tool or framework names are hard-coded here. The priority
order reflects system-level reliability, not per-tool knowledge.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class DiscoveryResult:
    """Result of a bounded tool-discovery probe."""

    tool: str
    found: bool
    path: str  # absolute path if found, "" otherwise
    method: str  # which tier found it
    version: str = ""  # populated when a --version probe succeeds


def _run_silent(cmd: list[str], timeout: float = 5.0) -> tuple[int, str]:
    """Run a command, capture output, never raise."""
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as exc:
        return 1, str(exc)


def _probe_version(path: str) -> str:
    """Try `path --version`; return first line of output or ""."""
    rc, out = _run_silent([path, "--version"], timeout=3.0)
    if rc == 0 and out:
        return out.splitlines()[0].strip()[:80]
    return ""


# ── Tier 1: shutil.which ────────────────────────────────────────────────────


def _tier_which(tool: str) -> Optional[str]:
    return shutil.which(tool) or shutil.which(tool.lower()) or None


# ── Tier 2: PATH scan ────────────────────────────────────────────────────────


def _tier_path_scan(tool: str) -> Optional[str]:
    """Walk PATH entries and look for the tool file directly."""
    path_env = os.environ.get("PATH", "")
    suffixes = ["", ".exe", ".cmd", ".bat"] if sys.platform == "win32" else [""]
    for entry in path_env.split(os.pathsep):
        entry = entry.strip()
        if not entry:
            continue
        p = Path(entry)
        if not p.is_dir():
            continue
        for suf in suffixes:
            candidate = p / (tool + suf)
            try:
                if candidate.is_file():
                    return str(candidate)
            except OSError:
                continue
    return None


# ── Tier 3: Shell probe ──────────────────────────────────────────────────────


def _tier_shell_probe(tool: str) -> Optional[str]:
    if sys.platform == "win32":
        # Get-Command (PowerShell) — do NOT use 'where' (aliased to Where-Object)
        rc, out = _run_silent(
            [
                "powershell",
                "-NonInteractive",
                "-NoProfile",
                "-Command",
                f"(Get-Command '{tool}' -ErrorAction SilentlyContinue).Source",
            ],
            timeout=6.0,
        )
        if rc == 0 and out and "\n" not in out.strip() and "\\" in out:
            return out.strip()
    else:
        rc, out = _run_silent(["which", tool], timeout=4.0)
        if rc == 0 and out.strip():
            return out.strip()
    return None


# ── Tier 4: Windows Registry App Paths ──────────────────────────────────────


def _tier_registry(tool: str) -> Optional[str]:
    if sys.platform != "win32":
        return None
    try:
        import winreg

        key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{tool}.exe"
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    val, _ = winreg.QueryValueEx(key, "")
                    if val and Path(val).exists():
                        return val
            except FileNotFoundError:
                continue
    except Exception:
        pass
    return None


# ── Tier 5: Package manager probes ──────────────────────────────────────────


def _tier_package_managers(tool: str) -> Optional[str]:
    """Try pip show / npm list / cargo metadata for package-installed tools."""
    # pip show — returns Location field
    rc, out = _run_silent([sys.executable, "-m", "pip", "show", tool], timeout=6.0)
    if rc == 0 and out:
        for line in out.splitlines():
            if line.startswith("Location:"):
                loc = line.split(":", 1)[1].strip()
                # The executable is usually in .../Scripts/<tool> (Windows) or .../bin/<tool>
                scripts = Path(loc).parent / ("Scripts" if sys.platform == "win32" else "bin")
                candidate = scripts / tool
                if candidate.exists():
                    return str(candidate)
                candidate_exe = scripts / (tool + ".exe")
                if candidate_exe.exists():
                    return str(candidate_exe)
    return None


# ── Tier 6: Bounded filesystem scan ─────────────────────────────────────────

# Only these root dirs are considered — never recurse from drive root.
_KNOWN_INSTALL_ROOTS_WIN = [
    Path("C:/Program Files"),
    Path("C:/Program Files (x86)"),
    Path("C:/tools"),
    Path("C:/yt-dlp"),
    Path("C:/ffmpeg"),
    Path(os.environ.get("LOCALAPPDATA", "C:/Users")) / "Programs",
    Path(os.environ.get("APPDATA", "C:/Users")),
    Path.home() / ".local" / "bin",
    Path.home() / "AppData" / "Local" / "Programs",
]

_KNOWN_INSTALL_ROOTS_UNIX = [
    Path("/usr/local/bin"),
    Path("/usr/bin"),
    Path("/opt"),
    Path("/home") / (os.environ.get("USER", "user")) / ".local" / "bin",
    Path.home() / ".local" / "bin",
]

_MAX_DEPTH = 3


def _tier_filesystem(tool: str) -> Optional[str]:
    """Bounded filesystem scan: only known install roots, max depth 3."""
    roots = _KNOWN_INSTALL_ROOTS_WIN if sys.platform == "win32" else _KNOWN_INSTALL_ROOTS_UNIX
    suffixes = [".exe", ".cmd", ""] if sys.platform == "win32" else [""]

    def _scan(directory: Path, depth: int) -> Optional[str]:
        if depth > _MAX_DEPTH:
            return None
        try:
            for entry in directory.iterdir():
                if entry.is_file():
                    for suf in suffixes:
                        if entry.stem.lower() == tool.lower() and entry.suffix.lower() == suf:
                            return str(entry)
                        if entry.name.lower() == tool.lower() + suf:
                            return str(entry)
                elif entry.is_dir():
                    result = _scan(entry, depth + 1)
                    if result:
                        return result
        except (PermissionError, OSError):
            pass
        return None

    for root in roots:
        if not root.exists():
            continue
        result = _scan(root, 0)
        if result:
            return result
    return None


# ── Public API ────────────────────────────────────────────────────────────────


def discover(tool: str, probe_version: bool = False) -> DiscoveryResult:
    """
    Discover a tool using the priority-ordered tier system.
    Returns a DiscoveryResult; never raises.

    Tiers tried in order (stops at first hit):
      1. shutil.which
      2. PATH scan
      3. Shell probe (Get-Command / which)
      4. Registry (Windows only)
      5. Package managers (pip show)
      6. Bounded filesystem scan

    Filesystem recursion from drive root is NEVER used.
    """
    tiers = [
        ("shutil.which", lambda: _tier_which(tool)),
        ("path_scan", lambda: _tier_path_scan(tool)),
        ("shell_probe", lambda: _tier_shell_probe(tool)),
        ("registry", lambda: _tier_registry(tool)),
        ("package_manager", lambda: _tier_package_managers(tool)),
        ("filesystem", lambda: _tier_filesystem(tool)),
    ]
    for method, probe in tiers:
        try:
            found_path = probe()
        except Exception:
            continue
        if found_path:
            ver = _probe_version(found_path) if probe_version else ""
            return DiscoveryResult(
                tool=tool,
                found=True,
                path=found_path,
                method=method,
                version=ver,
            )

    return DiscoveryResult(tool=tool, found=False, path="", method="exhausted")
