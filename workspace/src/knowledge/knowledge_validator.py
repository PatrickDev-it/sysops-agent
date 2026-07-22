"""
OS Capability Knowledge Engine — Knowledge Validator.

Guards against cross-platform pollution in any command string,
regardless of origin (LLM output, supervisor plan, executor fix).

Usage (called before any command reaches the shell):
    validator = KnowledgeValidator(profile)
    ok, reason = validator.validate(command_string)
    if not ok:
        # block the command — it would fail on this platform

Also provides a lighter audit mode that annotates rather than blocks,
for use in the supervisor prompt injection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .environment_detector import EnvironmentProfile
from .knowledge_loader import forbidden_platform_tags


@dataclass
class ValidationResult:
    ok: bool
    reason: str
    violations: list[str]  # specific tags or patterns that triggered rejection
    severity: str  # "HARD" (block) | "WARN" (annotate) | "OK"


class KnowledgeValidator:
    """
    Deterministic cross-platform contamination detector.

    Hard blocks:
      - Wrong-OS package manager in command (apt on Windows, winget on Linux)
      - Wrong-shell syntax patterns (bash-specific #!/bin/bash, zsh-isms on Windows)
      - Hardcoded wrong-platform paths (/usr/bin on Windows, C:\\ on Linux)

    Warnings:
      - Tool names that exist on both platforms but behave differently
      - Ambiguous path separators
    """

    # Shell-syntax patterns that are only valid in specific shells.
    # Each pattern: (regex, bad_shell, description)
    _SHELL_SYNTAX_RULES: list[tuple[re.Pattern, str, str]] = [
        (re.compile(r"#!/bin/(bash|sh|zsh)"), "powershell", "shebang line (Unix-only)"),
        (re.compile(r"\bsource\s+\S+"), "powershell", "`source` command (bash/zsh only)"),
        (re.compile(r"\bexport\s+[A-Z_]+="), "powershell", "`export VAR=` (bash/zsh only)"),
        (re.compile(r"\bsudo\b"), "powershell", "`sudo` (Unix-only)"),
        (re.compile(r"\bchmod\b|\bchown\b"), "powershell", "`chmod`/`chown` (Unix-only)"),
        (re.compile(r"\bln\s+-s\b"), "powershell", "`ln -s` (Unix-only)"),
        # $(...) is valid PowerShell subexpression syntax — only block when it contains
        # bash-only commands (backtick, subshell commands that don't exist in PowerShell).
        # Distinguisher: bash uses $(...) for command substitution with Unix commands;
        # PowerShell uses $(...) as a subexpression operator (always valid there).
        # Rule: block $(...) only on bash/zsh, where it conflicts with PowerShell cmdlets.
        (
            re.compile(r"\$\([^)]*\bGet-[A-Z]\w+\b[^)]*\)"),
            "bash",
            "PowerShell subexpression $() on bash",
        ),
        (re.compile(r"\bcat\s+/"), "powershell", "`cat /path` (Unix-only)"),
        (re.compile(r"\bgrep\b"), "powershell", "`grep` (use Select-String on PowerShell)"),
        (re.compile(r"\bsed\b|\bawk\b"), "powershell", "`sed`/`awk` (Unix-only)"),
        # PowerShell-specific patterns that would fail on bash
        (re.compile(r"\bGet-ChildItem\b", re.IGNORECASE), "bash", "PowerShell cmdlet on bash"),
        (re.compile(r"\bSet-Content\b", re.IGNORECASE), "bash", "PowerShell cmdlet on bash"),
        (re.compile(r"\bNew-Item\b", re.IGNORECASE), "bash", "PowerShell cmdlet on bash"),
        (re.compile(r"\bRemove-Item\b", re.IGNORECASE), "bash", "PowerShell cmdlet on bash"),
        (re.compile(r"\bTest-Path\b", re.IGNORECASE), "bash", "PowerShell cmdlet on bash"),
        (re.compile(r"\[Environment\]::", re.IGNORECASE), "bash", "PowerShell .NET call on bash"),
        (re.compile(r"\$env:", re.IGNORECASE), "bash", "$env: syntax (PowerShell only)"),
    ]

    # Platform-specific path patterns
    _WINDOWS_PATH_PAT = re.compile(r"[A-Za-z]:\\")
    _UNIX_PATH_PAT = re.compile(r"(?<!\w)/(?:usr|bin|etc|var|home|opt|tmp)/")

    def __init__(self, profile: EnvironmentProfile):
        self.profile = profile
        self._forbidden_tags = forbidden_platform_tags(profile)

    def validate(self, command: str) -> ValidationResult:
        """
        Full validation: returns HARD block, WARN, or OK.
        Any HARD violation means the command must not run.
        """
        violations: list[str] = []
        hard = False

        # 1. Package manager contamination (always HARD)
        for tag in self._forbidden_tags:
            # Match whole-word to avoid false positives (e.g. "aptly" is not "apt")
            pat = re.compile(rf"\b{re.escape(tag)}\b", re.IGNORECASE)
            if pat.search(command):
                violations.append(f"forbidden tool/tag `{tag}` for {self.profile.os_name}")
                hard = True

        # 2. Shell syntax mismatch (HARD when the active shell is the wrong one)
        for pattern, bad_shell, description in self._SHELL_SYNTAX_RULES:
            if self.profile.shell == bad_shell and pattern.search(command):
                violations.append(f"shell syntax violation: {description} on {self.profile.shell}")
                hard = True

        # 3. Platform-specific path contamination
        if self.profile.is_windows and self._UNIX_PATH_PAT.search(command):
            violations.append("Unix path pattern detected on Windows")
            hard = True
        if self.profile.is_linux or self.profile.is_macos:
            if self._WINDOWS_PATH_PAT.search(command):
                violations.append("Windows drive path (C:\\...) detected on Unix")
                hard = True

        if not violations:
            return ValidationResult(ok=True, reason="ok", violations=[], severity="OK")

        if hard:
            reason = "; ".join(violations[:3])
            return ValidationResult(
                ok=False,
                reason=f"OCKE BLOCK: {reason}",
                violations=violations,
                severity="HARD",
            )

        return ValidationResult(
            ok=True,
            reason=f"WARN: {'; '.join(violations[:2])}",
            violations=violations,
            severity="WARN",
        )

    def audit(self, command: str) -> str:
        """
        Lightweight audit for prompt annotation.
        Returns a short string like "OK" or "WARN: grep on PowerShell".
        Does not block — caller decides.
        """
        result = self.validate(command)
        return result.severity if result.ok else f"BLOCK: {result.reason[:80]}"

    def filter_plan(self, plan: list[dict]) -> tuple[list[dict], list[str]]:
        """
        Walk a supervisor plan and remove / annotate steps with hard violations.

        Returns (filtered_plan, list_of_rejection_reasons).
        Steps that fail validation are replaced with a BLOCKED marker, not silently dropped,
        so the orchestrator can log the cause.
        """
        filtered: list[dict] = []
        rejections: list[str] = []

        for step in plan:
            launcher = step.get("launcher") or step.get("tool") or ""
            if not launcher:
                filtered.append(step)
                continue
            result = self.validate(launcher)
            if result.severity == "HARD":
                reason = f"OCKE blocked step [{step.get('objective', '?')[:60]}]: {result.reason}"
                rejections.append(reason)
                blocked_step = dict(step)
                blocked_step["_ocke_blocked"] = result.reason
                blocked_step["_ocke_violations"] = result.violations
                filtered.append(blocked_step)
            else:
                filtered.append(step)

        return filtered, rejections


def validate_command(command: str, profile: EnvironmentProfile) -> ValidationResult:
    """Convenience function for one-off validation."""
    return KnowledgeValidator(profile).validate(command)
