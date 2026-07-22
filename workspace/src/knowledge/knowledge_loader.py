"""
OS Capability Knowledge Engine — Knowledge Loader.

Reads YAML files from the knowledge base tree (`src/knowledge/kb/`) and returns
ONLY the entries that match the active EnvironmentProfile.

No entry for the wrong OS/shell/distro ever leaves this module.

The KB is source: versioned, read-only, shipped with the package. It is read here and
nowhere else, and nothing in this module writes.

There was once a companion `knowledge_memory.py` holding per-OS success/failure counts in
`var/knowledge/`. It was deleted with the command-resolution pipeline that was its only
writer: the counters were never incremented on any reachable path, so the two prompt fields
they fed were permanently empty lists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..config import KB_DIR as _KB_ROOT
from .environment_detector import EnvironmentProfile

try:
    import yaml

    _YAML_OK = True
except ImportError:
    _YAML_OK = False


@dataclass
class KnowledgeEntry:
    """
    A single validated knowledge entry — safe to pass to the command ranker.

    All platform filtering has already been applied; consumers can trust
    that shell, platform, and distro are compatible with the active profile.
    """

    id: str
    platform: list[str]  # normalized: ["windows"] or ["linux","darwin"]
    shell: list[str]  # shells this entry is valid for
    intent: list[str]  # semantic labels, e.g. ["add_to_path", "path_permanent"]
    command: str  # the raw command template with $VAR tokens
    verify: str = ""  # lightweight verification command
    vars: list[str] = field(default_factory=list)  # required $VAR names
    notes: str = ""
    confidence: float = 0.80
    requires: list[str] = field(default_factory=list)  # tools that must be available
    distros: list[str] = field(default_factory=list)  # Linux: ["ubuntu","debian"] or []
    forbidden_shells: list[str] = field(default_factory=list)
    source_file: str = ""  # for debugging


def _normalize_platform(raw) -> list[str]:
    """Always return a list of lowercase platform strings."""
    if isinstance(raw, str):
        return [raw.lower()]
    if isinstance(raw, list):
        return [str(x).lower() for x in raw]
    return []


def _normalize_list(raw, default=None) -> list[str]:
    if raw is None:
        return list(default or [])
    if isinstance(raw, str):
        return [raw] if raw else []
    return [str(x) for x in raw]


def _parse_entry(raw: dict, source_file: str) -> Optional[KnowledgeEntry]:
    """Parse and validate one YAML dict. Returns None if malformed."""
    try:
        return KnowledgeEntry(
            id=str(raw.get("id", "")),
            platform=_normalize_platform(raw.get("platform", "")),
            shell=_normalize_list(raw.get("shell")),
            intent=_normalize_list(raw.get("intent")),
            command=str(raw.get("command", "")).strip(),
            verify=str(raw.get("verify", "") or ""),
            vars=_normalize_list(raw.get("vars")),
            notes=str(raw.get("notes", "") or ""),
            confidence=float(raw.get("confidence", 0.80)),
            requires=_normalize_list(raw.get("requires")),
            distros=_normalize_list(raw.get("distros")),
            forbidden_shells=_normalize_list(raw.get("forbidden_shells")),
            source_file=source_file,
        )
    except Exception:
        return None


def _entry_matches_profile(entry: KnowledgeEntry, profile: EnvironmentProfile) -> bool:
    """
    Hard predicate: returns True only when ALL of these hold:
      1. Platform matches (or entry is cross-platform)
      2. Shell is not forbidden
      3. If entry has distro restrictions, the active distro is in that list
      4. All required tools are available in the profile
    """
    # 1. Platform
    if entry.platform:
        # "windows" maps to profile.os_name == "windows", etc.
        if profile.os_name not in entry.platform:
            return False

    # 2. Forbidden shells — hard block
    if profile.shell in entry.forbidden_shells:
        return False

    # 3. Shell allowlist — if the entry restricts shells, must match
    if entry.shell and profile.shell not in entry.shell:
        return False

    # 4. Distro restriction (Linux only)
    if entry.distros and profile.is_linux:
        if profile.distro not in entry.distros:
            return False

    # 5. Required tools must be present
    if entry.requires:
        for req in entry.requires:
            if not (profile.has_capability(req) or profile.has_package_manager(req)):
                return False

    return True


def load_for_profile(profile: EnvironmentProfile, kb_root: Path = _KB_ROOT) -> list[KnowledgeEntry]:
    """
    Walk the knowledge/ tree. Return only entries that pass the profile filter.

    Guarantees:
      - No entry with wrong OS, shell, or distro is included.
      - Entries requiring unavailable tools are excluded.
      - Result is sorted by descending confidence.
    """
    if not _YAML_OK:
        return []

    entries: list[KnowledgeEntry] = []
    if not kb_root.exists():
        return entries

    for yaml_file in sorted(kb_root.rglob("*.yaml")):
        try:
            text = yaml_file.read_text(encoding="utf-8")
            data = yaml.safe_load(text)
        except Exception:
            continue

        if not isinstance(data, list):
            continue

        for raw in data:
            if not isinstance(raw, dict):
                continue
            entry = _parse_entry(raw, str(yaml_file.relative_to(kb_root)))
            if entry is None:
                continue
            if _entry_matches_profile(entry, profile):
                entries.append(entry)

    entries.sort(key=lambda e: e.confidence, reverse=True)
    return entries


_PM_ALIASES: dict[str, list[str]] = {
    "apt": ["apt-get", "apt"],
    "brew": ["brew"],
    "winget": ["winget"],
    "pip": ["pip", "pip3"],
    "dnf": ["dnf", "yum"],
    "pacman": ["pacman"],
    "scoop": ["scoop"],
    "choco": ["choco", "chocolatey"],
    "cargo": ["cargo"],
    "npm": ["npm", "npx"],
    "bun": ["bun", "bunx"],
    "pipx": ["pipx"],
}


def active_platform_tags(profile: EnvironmentProfile) -> set[str]:
    """
    Return the canonical tag set for the active profile.
    Includes all aliases for available package managers so that
    e.g. 'apt-get' is not flagged as forbidden when 'apt' is available.
    """
    tags: set[str] = {profile.os_name, profile.shell}
    if profile.distro:
        tags.add(profile.distro)
    tags.update(profile.package_managers)
    tags.update(profile.capabilities)
    # Expand aliases: if profile has "apt", also mark "apt-get" as active
    for pm in list(profile.package_managers) + list(profile.capabilities):
        for aliases in _PM_ALIASES.get(pm, []):
            tags.add(aliases)
    return tags


def forbidden_platform_tags(profile: EnvironmentProfile) -> set[str]:
    """
    Tags that should NEVER appear in a command on this platform.
    Used by knowledge_validator.py.
    """
    all_os = {"windows", "linux", "darwin"}
    all_shells = {"powershell", "pwsh", "cmd", "bash", "zsh", "fish", "sh"}
    all_pkg = {"apt", "apt-get", "dnf", "pacman", "brew", "winget", "scoop", "choco"}

    active = active_platform_tags(profile)
    forbidden: set[str] = set()

    for tag in all_os - {profile.os_name}:
        forbidden.add(tag)
    for tag in all_shells - {profile.shell}:
        if tag not in profile.active_shells:
            forbidden.add(tag)
    for tag in all_pkg:
        if tag not in profile.package_managers:
            forbidden.add(tag)

    # Never forbid things we actually have
    return forbidden - active
