"""
OS Capability Knowledge Engine — Environment Detector.

Builds an EnvironmentProfile by probing the live host.
This is the single source of truth that gates ALL knowledge loading.

Design invariant: probe once at startup, cache forever for the run.
No framework names — only runtime observables.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EnvironmentProfile:
    """
    The complete platform fingerprint for one run.

    Fields are populated from live host probing — no guessing.
    Every field that could not be determined is left as an empty string.

    The profile is the key that unlocks exactly one slice of the
    knowledge base and forbids all others.
    """

    # Tier 1 — OS
    os_name: str = ""  # "windows" | "linux" | "darwin"
    os_version: str = ""  # "10.0.19045", "22.04", "14.1"
    os_major: int = 0  # 10, 11, 22 …

    # Tier 2 — Distribution (Linux only)
    distro: str = ""  # "ubuntu" | "debian" | "arch" | "fedora" | ""

    # Tier 3 — Shell
    shell: str = ""  # "powershell" | "pwsh" | "bash" | "zsh" | "cmd" | "fish"

    # Tier 4 — Package managers (confirmed available)
    package_managers: list[str] = field(default_factory=list)
    # e.g. ["pip", "winget"] or ["pip", "apt"] or ["pip", "brew"]

    # Tier 5 — Runtimes & tools (confirmed available)
    capabilities: list[str] = field(default_factory=list)
    # e.g. ["python", "git", "docker", "node"]

    # Tier 6 — Hardware / arch
    architecture: str = ""  # "x86_64" | "arm64" | "x86"
    cpu_count: int = 0

    # Internal
    _probed: bool = field(default=False, repr=False)

    # ── Derived helpers ───────────────────────────────────────────────────────

    @property
    def is_windows(self) -> bool:
        return self.os_name == "windows"

    @property
    def is_linux(self) -> bool:
        return self.os_name == "linux"

    @property
    def is_macos(self) -> bool:
        return self.os_name == "darwin"

    @property
    def active_shells(self) -> list[str]:
        """Shells that are valid on this platform."""
        if self.is_windows:
            return ["powershell", "pwsh", "cmd"]
        if self.is_macos:
            return [self.shell, "bash", "zsh", "sh"]
        return [self.shell, "bash", "zsh", "sh"]

    @property
    def forbidden_shells(self) -> list[str]:
        """Shells that must never be used on this platform."""
        all_shells = {"powershell", "pwsh", "cmd", "bash", "zsh", "sh", "fish"}
        return sorted(all_shells - set(self.active_shells))

    def has_capability(self, name: str) -> bool:
        return name.lower() in self.capabilities

    def has_package_manager(self, name: str) -> bool:
        return name.lower() in self.package_managers

    def summary(self) -> str:
        lines = [
            f"os={self.os_name} version={self.os_version}",
            f"shell={self.shell}",
            f"distro={self.distro or 'n/a'}",
            f"package_managers={self.package_managers}",
            f"capabilities={self.capabilities}",
            f"arch={self.architecture}",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "os_name": self.os_name,
            "os_version": self.os_version,
            "os_major": self.os_major,
            "distro": self.distro,
            "shell": self.shell,
            "package_managers": self.package_managers,
            "capabilities": self.capabilities,
            "architecture": self.architecture,
            "cpu_count": self.cpu_count,
        }


# ── Probe functions ────────────────────────────────────────────────────────────


def _probe_os() -> tuple[str, str, int]:
    """Returns (os_name, os_version, os_major). Never raises."""
    sysname = platform.system()
    if sysname == "Windows":
        v = platform.version()  # "10.0.19045"
        major = _extract_windows_major(v)
        return "windows", v, major
    if sysname == "Darwin":
        v = platform.mac_ver()[0]  # "14.1.0"
        try:
            major = int(v.split(".")[0])
        except Exception:
            major = 0
        return "darwin", v, major
    # Linux
    v = platform.release()  # "5.15.0-91-generic"
    try:
        major = int(v.split(".")[0])
    except Exception:
        major = 0
    return "linux", v, major


def _extract_windows_major(version: str) -> int:
    """
    Derives Windows 10 vs 11 from the build number.
    Build >= 22000 → Windows 11. Build < 22000 → Windows 10.
    Returns 0 if version string is not parseable.
    """
    try:
        parts = version.split(".")
        if len(parts) < 3:
            return 0
        build = int(parts[2])
        return 11 if build >= 22000 else 10
    except (ValueError, IndexError):
        return 0


def _probe_distro() -> str:
    """Linux only. Returns normalized distro id or empty string."""
    if sys.platform != "linux":
        return ""
    # Python 3.10+ has platform.freedesktop_os_release()
    try:
        info = platform.freedesktop_os_release()
        raw = info.get("ID", "").lower()
        return _normalize_distro(raw)
    except AttributeError:
        pass
    # Fallback: read /etc/os-release
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("ID="):
                    raw = line.split("=", 1)[1].strip().strip('"').lower()
                    return _normalize_distro(raw)
    except Exception:
        pass
    return ""


_DISTRO_ALIASES = {
    "ubuntu": "ubuntu",
    "debian": "debian",
    "linuxmint": "mint",
    "pop": "pop_os",
    "fedora": "fedora",
    "rhel": "rhel",
    "centos": "centos",
    "rocky": "rocky",
    "arch": "arch",
    "manjaro": "manjaro",
    "endeavouros": "endeavouros",
}


def _normalize_distro(raw: str) -> str:
    for key, normalized in _DISTRO_ALIASES.items():
        if key in raw:
            return normalized
    return raw


def _probe_shell() -> str:
    """Detect the active shell for command generation."""
    if sys.platform == "win32":
        # Check if running under pwsh (PowerShell 7+) vs powershell (5.x)
        if shutil.which("pwsh"):
            return "pwsh"
        return "powershell"
    raw = os.environ.get("SHELL", "")
    if not raw:
        return "bash"
    name = raw.rsplit("/", 1)[-1].lower()
    known = {"bash", "zsh", "fish", "sh", "dash", "ksh"}
    return name if name in known else "bash"


def _probe_package_managers() -> list[str]:
    """Return list of confirmed-available package manager names."""
    candidates = {
        "pip": ["pip", "pip3"],
        "winget": ["winget"],
        "scoop": ["scoop"],
        "choco": ["choco"],
        "apt": ["apt-get", "apt"],
        "dnf": ["dnf"],
        "pacman": ["pacman"],
        "brew": ["brew"],
        "pipx": ["pipx"],
        "cargo": ["cargo"],
        "npm": ["npm"],
        "yarn": ["yarn"],
        "bun": ["bun"],
        "pnpm": ["pnpm"],
    }
    found = []
    for name, binaries in candidates.items():
        if any(shutil.which(b) for b in binaries):
            found.append(name)
    return found


def _probe_capabilities() -> list[str]:
    """Return list of confirmed-available tools / runtimes."""
    tools = [
        "python",
        "python3",
        "pip",
        "pip3",
        "git",
        "docker",
        "node",
        "npm",
        "yarn",
        "bun",
        "cargo",
        "rustc",
        "go",
        "java",
        "mvn",
        "gradle",
        "curl",
        "wget",
        "ssh",
        "rsync",
        "winget",
        "scoop",
        "choco",
        "apt",
        "apt-get",
        "dnf",
        "pacman",
        "brew",
        "pipx",
        "uv",
    ]
    return [t for t in tools if shutil.which(t)]


def _probe_arch() -> str:
    m = platform.machine().lower()
    if m in ("x86_64", "amd64"):
        return "x86_64"
    if m in ("arm64", "aarch64"):
        return "arm64"
    if m in ("i686", "i386", "x86"):
        return "x86"
    return m


# ── Public API ─────────────────────────────────────────────────────────────────

_cached_profile: Optional[EnvironmentProfile] = None


def detect(force: bool = False) -> EnvironmentProfile:
    """
    Build and cache an EnvironmentProfile from the live host.

    Called once at run startup. Subsequent calls return the cached instance.
    force=True re-probes (used in tests).
    """
    global _cached_profile
    if _cached_profile is not None and not force:
        return _cached_profile

    os_name, os_version, os_major = _probe_os()
    distro = _probe_distro() if os_name == "linux" else ""
    shell = _probe_shell()
    package_managers = _probe_package_managers()
    capabilities = _probe_capabilities()
    arch = _probe_arch()

    profile = EnvironmentProfile(
        os_name=os_name,
        os_version=os_version,
        os_major=os_major,
        distro=distro,
        shell=shell,
        package_managers=package_managers,
        capabilities=capabilities,
        architecture=arch,
        cpu_count=os.cpu_count() or 0,
        _probed=True,
    )
    _cached_profile = profile
    return profile


def from_state(state) -> EnvironmentProfile:
    """
    Build a profile from an existing SystemState.environment object.
    Used so the orchestrator does not re-probe what state.py already did.
    """
    env = state.environment
    os_name = env.os_name.lower() if env.os_name else ""
    if os_name == "windows":
        os_name = "windows"
    elif os_name == "darwin":
        os_name = "darwin"
    elif os_name == "linux":
        os_name = "linux"

    profile = detect()
    # Override with the already-probed env data (richer version info from platform)
    profile.os_name = os_name
    profile.shell = env.shell or profile.shell
    return profile
