"""
OS Capability Knowledge Engine — Command Registry.

A typed, in-memory dictionary of intent → commands, built from the loaded
knowledge entries for the active EnvironmentProfile.

The registry is the bridge between semantic intent ("install globally") and
a concrete, platform-correct command template. It does NOT generate commands —
it only maps verified knowledge entries.

Usage:
    registry = CommandRegistry.build(profile)
    entries = registry.resolve("install_global")
    best = registry.best("install_global", requires=["pip"])
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .environment_detector import EnvironmentProfile
from .knowledge_loader import _KB_ROOT, KnowledgeEntry, load_for_profile

# Intent taxonomy — the canonical set of semantic labels the ranker uses.
# Adding a new intent here is the ONLY change needed to support a new goal category.
INTENT_TAXONOMY = {
    # Package management
    "install_global",
    "install_user",
    "install_python_package",
    "install_python_tool",
    "install_package",
    "uninstall_package",
    "update_package_list",
    "list_packages",
    # Environment
    "add_to_path",
    "path_permanent",
    "path_session",
    "read_path",
    "discover_path",
    "set_env_var",
    "read_env_var",
    "env_var_permanent",
    # Discovery
    "find_executable",
    "which",
    "locate_tool",
    "check_installed",
    "verify_package",
    "discover_scripts_path",
    "find_pip_scripts",
    "find_file",
    "search_file",
    "locate_file",
    # Filesystem
    "create_directory",
    "mkdir",
    "delete_file",
    "delete_directory",
    "remove",
    "copy_file",
    "copy",
    "move_file",
    "rename_file",
    "move",
    "read_file",
    "cat_file",
    "view_file",
    "list_files",
    "ls",
    "dir",
    "check_exists",
    "test_path",
    # Search
    "search_package",
    "find_package",
}


@dataclass
class CommandRegistry:
    """
    Platform-gated command index. Built once per run from filtered entries.

    Internal structure:
        _by_intent: intent → sorted list[KnowledgeEntry] (desc confidence)
        _by_id:     entry_id → KnowledgeEntry
    """

    profile: EnvironmentProfile
    _by_intent: dict[str, list[KnowledgeEntry]] = field(default_factory=lambda: defaultdict(list))
    _by_id: dict[str, KnowledgeEntry] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        profile: EnvironmentProfile,
        kb_root: Path = _KB_ROOT,
    ) -> "CommandRegistry":
        """
        Load the knowledge base, filter by profile, and index by intent.
        This is the only entry point — callers never call the loader directly.
        """
        entries = load_for_profile(profile, kb_root)
        reg = cls(profile=profile)
        for entry in entries:
            reg._by_id[entry.id] = entry
            for intent in entry.intent:
                reg._by_intent[intent].append(entry)
        # Sort each intent bucket by descending confidence
        for intent_entries in reg._by_intent.values():
            intent_entries.sort(key=lambda e: e.confidence, reverse=True)
        return reg

    # ── Query API ─────────────────────────────────────────────────────────────

    def resolve(self, intent: str) -> list[KnowledgeEntry]:
        """
        All platform-matched entries for an intent, sorted by confidence.
        Returns [] if no entry matches — caller must handle this.
        """
        return list(self._by_intent.get(intent, []))

    def best(
        self,
        intent: str,
        requires: Optional[list[str]] = None,
        exclude_ids: Optional[list[str]] = None,
    ) -> Optional[KnowledgeEntry]:
        """
        Single best entry for an intent, respecting additional constraints.

        requires: tools that must appear in entry.requires (further narrows)
        exclude_ids: entries to skip (already tried / failed)
        """
        candidates = self.resolve(intent)
        if not candidates:
            return None
        exclude = set(exclude_ids or [])
        for entry in candidates:
            if entry.id in exclude:
                continue
            if requires:
                # Prefer entries that explicitly list the required tool
                if not any(r in entry.requires for r in requires):
                    continue
            return entry
        # Relax requires constraint — return highest-confidence non-excluded entry
        for entry in candidates:
            if entry.id not in exclude:
                return entry
        return None

    def get_by_id(self, entry_id: str) -> Optional[KnowledgeEntry]:
        return self._by_id.get(entry_id)

    def all_entries(self) -> list[KnowledgeEntry]:
        return list(self._by_id.values())

    def intents_available(self) -> list[str]:
        return sorted(self._by_intent.keys())

    def has_intent(self, intent: str) -> bool:
        return bool(self._by_intent.get(intent))

    # ── Capability assertions ─────────────────────────────────────────────────

    def can_install_globally(self) -> bool:
        """True if at least one global install method is available."""
        return self.has_intent("install_global") or self.has_intent("install_python_package")

    def preferred_package_manager(self) -> str:
        """
        Return the name of the highest-confidence available package manager
        for install operations.
        """
        for intent in ("install_global", "install_package", "install_python_package"):
            entries = self.resolve(intent)
            if entries:
                # The highest-confidence entry's first require is the preferred pm
                for entry in entries:
                    if entry.requires:
                        return entry.requires[0]
        return ""

    def summary(self) -> str:
        lines = [
            f"Registry for {self.profile.os_name}/{self.profile.shell}",
            f"  entries: {len(self._by_id)}",
            f"  intents: {len(self._by_intent)}",
            f"  top intents: {', '.join(list(self._by_intent.keys())[:8])}",
        ]
        return "\n".join(lines)


# ── Intent-from-text extraction ────────────────────────────────────────────────
# Maps common goal keywords to canonical intent labels.
# Used by the ranker to map a free-text step objective to knowledge entries.

_KEYWORD_TO_INTENTS: list[tuple[list[str], list[str]]] = [
    # Install / remove
    (["install", "add package", "get package"], ["install_global", "install_package"]),
    (["install globally", "global install"], ["install_global"]),
    (["install python", "pip install", "python package"], ["install_python_package"]),
    (["pipx", "python tool", "cli tool"], ["install_python_tool"]),
    (["uninstall", "remove package", "deinstall"], ["uninstall_package"]),
    (["update package", "refresh repos", "apt update"], ["update_package_list"]),
    # PATH / env
    (["add to path", "path permanent", "set path", "path env"], ["add_to_path", "path_permanent"]),
    (["session path", "temporary path"], ["add_to_path", "path_session"]),
    (["read path", "show path", "current path"], ["read_path", "discover_path"]),
    (["set env", "environment variable", "env var"], ["set_env_var"]),
    (["read env", "get env", "show env"], ["read_env_var"]),
    # Discovery
    (
        ["find executable", "which", "where is", "locate tool"],
        ["find_executable", "which", "locate_tool"],
    ),
    (["check installed", "is installed", "verify install"], ["check_installed", "verify_package"]),
    (
        ["scripts path", "pip scripts", "user scripts"],
        ["discover_scripts_path", "find_pip_scripts"],
    ),
    (["find file", "search file", "locate file"], ["find_file", "search_file"]),
    # Filesystem
    (["create dir", "mkdir", "new directory"], ["create_directory", "mkdir"]),
    (["delete", "remove file", "rm "], ["delete_file", "remove"]),
    (["copy", "cp "], ["copy_file", "copy"]),
    (["move", "rename", "mv "], ["move_file", "rename_file", "move"]),
    (["list files", "ls ", "dir ", "show files"], ["list_files", "ls", "dir"]),
    (["read file", "cat ", "show content"], ["read_file", "cat_file", "view_file"]),
    (["check exists", "test path", "does path exist"], ["check_exists", "test_path"]),
    (["search package", "find package", "winget search"], ["search_package", "find_package"]),
]


def intents_from_text(text: str) -> list[str]:
    """
    Extract canonical intent labels from free-text step objective.
    Returns a deduplicated list, ordered by first match.
    """
    lower = text.lower()
    found: list[str] = []
    seen: set[str] = set()
    for keywords, intents in _KEYWORD_TO_INTENTS:
        if any(kw in lower for kw in keywords):
            for intent in intents:
                if intent not in seen:
                    found.append(intent)
                    seen.add(intent)
    return found
