"""Command-level confinement — the single owner of "may this command touch that path?".

This is a FILTER, not a jail. It runs in-process, as the same user, before `session.run`
hands the string to a shell. A command it fails to parse can still do harm. Do not mistake
it for a sandbox; it exists so that a 50-run benchmark on a live host has a floor, not a
guarantee. Real isolation is a kernel boundary (WSL/VM), and that remains the right answer
for unattended mutating runs.

The predicate is deliberately asymmetric, because the workload is:

    READS  outside the root are ALLOWED.  47 of the 50 benchmark tasks exist precisely to
           read outside the workspace: system logs, home directory, disk usage, installed
           packages. A blanket path-scope check would make the suite meaningless.
    WRITES outside the root are BLOCKED.  A command is "mutating" if it contains a shell
           primitive that changes state.

To avoid the obvious false positive — `Get-ChildItem C:\\Users | Out-File out.txt`, which
reads outside and writes inside — the path scope is evaluated only on the PIPELINE SEGMENT
that carries the mutating verb, not on the whole command line.

Fail-closed: inside a mutating segment, a path we cannot resolve (an env-var expansion, a
subshell) is treated as outside the root. A blocked command is not an exception; it is a
non-zero exit with a legible message, so the agent observes it, classifies the error and
recovers — which is also what we want to measure.

Only shell primitives appear below. No tool, framework or product knowledge: `rm` and
`Remove-Item` are properties of a shell, not of a product.
"""

from __future__ import annotations

import os
import re
from pathlib import Path


class ConfinementViolation(Exception):
    pass


# Three disjoint classes, because they need three different answers.
#
# 1. PATH-mutating: the mutation has a filesystem target, so it can be SCOPED. This is the
#    only class where "is the target inside the root?" is a meaningful question.
_PATH_MUTATING = re.compile(
    r"(?<![\w-])("
    r"rm|rmdir|unlink|shred|truncate|dd|mv|chmod|chown|chgrp|tee|ln|"
    r"Remove-Item|Clear-Content|Set-Content|Add-Content|Out-File|Move-Item|Rename-Item|"
    r"New-Item|Copy-Item|Set-ItemProperty|Remove-ItemProperty"
    r")(?![\w-])",
    re.IGNORECASE,
)

# 2. SYSTEM-mutating: changes machine state that has no path, so scoping is meaningless —
#    a service, an ACL, a registry value, the power state. Under a confinement root these
#    are out of scope BY DEFINITION: nothing a workspace-scoped task does should touch them.
#    Note the verb qualifiers: `reg query` and `sc query` are reads and must pass.
_SYSTEM_MUTATING = re.compile(
    r"(?<![\w-])(shutdown|Stop-Computer|Restart-Computer|Remove-Service|Stop-Service|"
    r"Start-Service|Set-Service|Set-Acl|icacls|attrib|cipher|takeown|setx|"
    r"Stop-Process|taskkill)(?![\w-])"
    r"|(?<![\w-])reg(\.exe)?\s+(add|delete|import|copy|restore|load)(?![\w-])"
    r"|(?<![\w-])sc(\.exe)?\s+(delete|create|config|stop|start)(?![\w-])"
    r"|(?<![\w-])net(\.exe)?\s+(user|localgroup|stop|start)(?![\w-])"
    r"|(?<![\w-])(winget|choco|scoop)\s+(install|uninstall|upgrade|update)(?![\w-])"
    r"|(?<![\w-])(sudo\s+)?(apt|apt-get|dnf|yum|pacman|zypper|apk|brew)\s+"
    r"(install|remove|uninstall|upgrade|update)(?![\w-])"
    r"|(?<![\w-])(python\s+-m\s+pip|pip3?|uv\s+pip)\s+(install|uninstall)(?![\w-])"
    r"|(?<![\w-])(npm|pnpm)\s+(install|add|remove|uninstall)\b[^|;]*(\s-g|--global)"
    r"|(?<![\w-])yarn\s+global\s+(add|remove)(?![\w-])",
    re.IGNORECASE,
)

# 3. ALWAYS fatal: irreversible, whole-device or boot-level. Refused wherever they appear.
#    Note what is NOT here: `C:\Windows` on its own. Reading it is legitimate and 47 of the
#    50 benchmark tasks read outside the root. Writing to it is caught by the scope rule in
#    class 1, with a precise reason — not by a blanket pattern that also kills the reads.
_ALWAYS_FATAL = re.compile(
    r"(?<![\w-])(mkfs\S*|diskpart|bcdedit|vssadmin\s+delete|format\s+[a-z]:)(?![\w-])"
    r"|(?<![\w-])rm\s+(-\w+\s+)*/\s*$"
    r"|(?<![\w-])rm\s+(-\w+\s+)*/(etc|usr|bin|boot|var|lib|sys|proc)(/|\s|$)",
    re.IGNORECASE,
)

# A token that denotes a filesystem location.
_ABS_WIN = re.compile(r"^[A-Za-z]:[\\/]")
_UNC = re.compile(r"^\\\\")
_REGISTRY = re.compile(r"^(HKLM|HKCU|HKCR|HKU|HKCC|HKEY_[A-Z_]+):", re.IGNORECASE)
_HAS_EXPANSION = re.compile(r"[$%`]|\$\(|\bsubst\b")
_SEPARATOR = re.compile(r"[\\/]")
_EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,6}$")

# A dynamic VALUE is legitimate (`Set-Content report.txt -Value $totalRAM`); a dynamic write
# DESTINATION is not. The parent process cannot resolve shell variables safely, so accepting one
# makes the path boundary depend on model-authored runtime state. These expressions identify only
# target positions: redirection, explicit path flags, and the first positional operand of a
# mutating verb. They are deliberately checked before token/path heuristics.
_DYNAMIC_REDIRECT_TARGET = re.compile(r"(?<![0-9<>])>>?(?!&)\s*['\"]?[$%`]")
_DYNAMIC_FLAG_TARGET = re.compile(
    r"-(?:Path|LiteralPath|Destination|FilePath)\s+['\"]?[$%`]", re.IGNORECASE
)
_DYNAMIC_POSITIONAL_TARGET = re.compile(rf"{_PATH_MUTATING.pattern}\s+['\"]?[$%`]", re.IGNORECASE)


def _is_path_candidate(tok: str) -> bool:
    """Does this token denote a location at all?

    `Set-Content out.txt -Value $totalRAM` mutates, and `$totalRAM` is a VALUE, not a path.
    Treating every `$var` as an unresolvable path made the filter refuse 4 of the first 5
    benchmark tasks — a filter that corrupts the measurement is worse than none. So a token
    must look like a location: a separator, a drive letter, `~`, a registry hive, or a file
    extension. A bare `$var` is not a location.

    The trade-off is explicit: `Out-File $target` where `$target` holds an absolute path
    outside the root will NOT be caught. That is a false negative this filter accepts, and
    the reason it is not a sandbox.
    """
    if not tok:
        return False
    if _SEPARATOR.search(tok) or _ABS_WIN.match(tok) or _UNC.match(tok):
        return True
    if tok.startswith("~") or _REGISTRY.match(tok):
        return True
    return bool(_EXTENSION.search(tok))


_SEGMENT_SPLIT = re.compile(r"\||;|&&|\|\||(?<![0-9<>])>>?(?!&)")


def _tokens(segment: str) -> list[str]:
    """Bare words and quoted strings, minus flags."""
    raw = re.findall(r"'([^']*)'|\"([^\"]*)\"|(\S+)", segment)
    out = []
    for single, double, bare in raw:
        tok = single or double or bare
        if not tok or tok.startswith("-"):
            continue
        out.append(tok)
    return out


# ── The run's confinement root — one owner, set once ─────────────────────────
# Mirrors `workspace_paths.set_root`. The root is the workspace the operator named, which is a
# run-level fact; a per-call derivation (e.g. from the current cwd) would make every relative
# write "inside" by construction and the filter would enforce nothing.
_root: Path | None = None


def set_root(path: str | Path | None) -> None:
    global _root
    _root = Path(path).resolve() if path else None


def current_root() -> Path | None:
    return _root


class Confinement:
    """Write confinement. `check()` returns a reason string, or None to allow.

    TWO MODES, and the distinction is why this class no longer returns None to its callers.

    ROOTED (`root` set) — the full filter: fatal patterns, system-mutating patterns, and path
    scoping against the root.

    FATAL-ONLY (`root is None`) — the pattern classes that no workspace scope can justify:
    `mkfs`, `diskpart`, `bcdedit`, `rm -rf /`, whole-device and boot-level operations. These
    used to live INSIDE the object that `from_env()` returned as None whenever
    SISTEMISTA_CONFINE_ROOT was unset, which is every production run — the variable was set
    only by the three benchmark harnesses. So on the documented invocation path, invariant #14
    was structurally wired and semantically vacuous: `_ALWAYS_FATAL` never executed, and the
    only guards a model-authored command passed were the placeholder check, the
    self-truncating-redirect check and OS-platform validity.

    There is no environment-variable opt-out. An env flag is not a capability boundary: any
    wrapper that can set it could silently reopen writes to the whole host.
    """

    def __init__(self, root: str | Path | None) -> None:
        self.root = Path(root).resolve() if root is not None else None

    @property
    def rooted(self) -> bool:
        return self.root is not None

    @classmethod
    def for_workspace(cls, workspace: str | Path | None) -> "Confinement":
        """Confined to `workspace` unless explicitly opted out.

        Never returns None. A caller handed None writes `if confine is not None:`, and that
        guard is indistinguishable from no guard at all — which is precisely how this one
        disappeared from production for the lifetime of the project.
        """
        root = os.environ.get("SISTEMISTA_CONFINE_ROOT") or workspace
        return cls(root) if root else cls(None)

    @classmethod
    def current(cls) -> "Confinement":
        """The run's filter, as every execution owner should obtain it.

        The confinement root is a property of the RUN, not of the call: it is the workspace the
        operator named. `fileops` only ever receives a cwd, and deriving the root from that cwd
        would make every relative write trivially "inside" — the filter would type-check and
        enforce nothing. So the root is set once per run, mirroring `workspace_paths.set_root`,
        which exists for the same reason.
        """
        return cls.for_workspace(_root)

    @classmethod
    def from_env(cls) -> "Confinement":
        return cls.current()

    def _outside(self, token: str, cwd: Path | None = None) -> bool:
        """Is `token` outside the root, resolved from the directory the command will RUN in?

        `cwd` is load-bearing. This used to resolve a relative token against `self.root`, while
        the process actually executed with `cwd=session._cwd` and fileops wrote to `cwd / path`
        — the same directory only by accident. Since `workspace_paths` deliberately forces every
        prompt to speak in RELATIVE paths, the bare relative name is not an edge case, it is the
        dominant form. Verified before the fix: with the root set to one temp directory and the
        cwd to a sibling, `check_path('pwned.txt')` returned None (allowed) and the write landed
        outside the root.
        """
        if self.root is None:
            return False
        if _HAS_EXPANSION.search(token):
            return True  # fail closed: we cannot resolve it here
        if token.startswith("~"):
            return True
        if _UNC.match(token) or _REGISTRY.match(token):
            return True
        try:
            if _ABS_WIN.match(token) or token.startswith("/"):
                p = Path(token).resolve()
            else:
                base = Path(cwd).resolve() if cwd is not None else self.root
                p = (base / token).resolve()
            p.relative_to(self.root)
            return False
        except (ValueError, OSError):
            return True

    def check(self, command: str, cwd: Path | None = None) -> str | None:
        cmd = (command or "").strip()
        if not cmd:
            return None

        if _ALWAYS_FATAL.search(cmd):
            return "irreversible whole-device or boot-level operation"

        if _SYSTEM_MUTATING.search(cmd):
            return "mutates machine state that no workspace-scoped task owns (service, ACL, registry, power)"

        # Fatal-only mode stops here: the two pattern classes above are the ones no workspace
        # scope can justify, and they apply whether or not a root was configured.
        if self.root is None:
            return None

        if (
            _DYNAMIC_REDIRECT_TARGET.search(cmd)
            or _DYNAMIC_FLAG_TARGET.search(cmd)
            or _DYNAMIC_POSITIONAL_TARGET.search(cmd)
        ):
            return "mutating command has a dynamic destination that cannot be confined"

        # Evaluate scope only where a path mutation actually happens, so that reading
        # outside the root and writing inside it — the shape of a diagnostic task — passes.
        segments = _SEGMENT_SPLIT.split(cmd)
        redirect_targets = re.findall(r"(?<![0-9<>])>>?(?!&)\s*(\S+)", cmd)

        for seg in segments:
            if not seg or not _PATH_MUTATING.search(seg):
                continue
            for tok in _tokens(seg):
                if _PATH_MUTATING.fullmatch(tok) or not _is_path_candidate(tok):
                    continue
                if self._outside(tok, cwd):
                    return f"mutating command targets a path outside the root: {tok!r}"

        for tgt in redirect_targets:
            tgt = tgt.strip("'\"")
            if _is_path_candidate(tgt) and self._outside(tgt, cwd):
                return f"redirection writes outside the root: {tgt!r}"

        return None

    def check_path(self, path: str | Path, cwd: Path | None = None) -> str | None:
        """Direct path check, for the `__SAFE_FS__` sentinels that bypass the shell."""
        return None if not self._outside(str(path), cwd) else f"path outside the root: {path!r}"
