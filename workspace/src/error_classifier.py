"""
Error Classifier — maps raw command output to an error class, then to
a constrained set of allowed/forbidden recovery actions.

Design invariant:
    Recovery must be DERIVED from the actual error observation.
    No recovery action is invented from thin air.
    If the error class is UNKNOWN, the only allowed recovery is human escalation.

Architecture:
    raw output + exit code
        → classify() → ErrorClass
        → allowed_recoveries(class) → list[str]
        → forbidden_recoveries(class) → list[str]

The orchestrator uses this to validate that a proposed fix is in the allowed
set and not in the forbidden set before attempting it.
"""

from __future__ import annotations

import re
from enum import Enum

# POSIX/Unix shell builtins and coreutils that do NOT exist as PowerShell cmdlets.
# When one of these is the failing token on a "not recognized" error, the cause
# is wrong-shell syntax (a bash command run under PowerShell), NOT a missing tool.
# This is a portable shell-grammar fact, not a per-tool catalog: these are shell
# constructs, not installable executables.
_UNIX_SHELL_BUILTINS: frozenset[str] = frozenset(
    {
        "test",
        "[",
        "[[",
        "export",
        "source",
        "alias",
        "unset",
        "local",
        "declare",
        "grep",
        "egrep",
        "fgrep",
        "sed",
        "awk",
        "cat",
        "ls",
        "cp",
        "mv",
        "rm",
        "rmdir",
        "mkdir",
        "touch",
        "ln",
        "chmod",
        "chown",
        "which",
        "echo",
        "printf",
        "head",
        "tail",
        "wc",
        "cut",
        "tr",
        "sort",
        "uniq",
        "find",
        "xargs",
        "tee",
        "pwd",
        "basename",
        "dirname",
        "readlink",
        "stat",
        "du",
        "df",
        "ps",
        "kill",
        "sleep",
    }
)

# PowerShell "not recognized" error — extracts the offending token.
_NOT_RECOGNIZED_RE = re.compile(
    r"the term ['\"]?([^'\"\s]+)['\"]? is not recognized",
    re.IGNORECASE,
)


class ErrorClass(str, Enum):
    INVALID_EXECUTABLE = "INVALID_EXECUTABLE"  # binary is corrupt / wrong format
    FILE_NOT_FOUND = "FILE_NOT_FOUND"  # path does not exist
    PERMISSION_DENIED = "PERMISSION_DENIED"  # access refused by OS
    PACKAGE_NOT_FOUND = "PACKAGE_NOT_FOUND"  # pip/npm/cargo package unknown
    NETWORK_ERROR = "NETWORK_ERROR"  # download/registry unreachable
    ENV_SCOPE_MISMATCH = "ENV_SCOPE_MISMATCH"  # tool installed in venv, goal needs global
    COMMAND_SYNTAX = "COMMAND_SYNTAX"  # wrong flags, wrong shell syntax
    TIMEOUT = "TIMEOUT"  # command took too long
    UNKNOWN = "UNKNOWN"  # cannot classify — escalate


# Signals that indicate each error class (checked in order; first match wins).
# Each entry: (ErrorClass, list_of_substrings_in_output_lowercased)
_SIGNAL_TABLE: list[tuple[ErrorClass, list[str]]] = [
    (
        ErrorClass.INVALID_EXECUTABLE,
        [
            "is not a valid win32 application",
            "bad exe format",
            "exec format error",
            "cannot execute binary file",
            "invalid pe",
            "not a valid executable",
        ],
    ),
    (
        ErrorClass.FILE_NOT_FOUND,
        [
            "no such file or directory",
            "the system cannot find the file",
            "cannot find path",
            "pathnotfound",
            "filenotfoundexception",
            "does not exist",
            # NOTE: "is not recognized as the name of a cmdlet" is intentionally NOT
            # here. It is ambiguous — it can mean either a genuinely missing tool OR
            # a wrong-shell-syntax command (e.g. bash `test` on PowerShell). It is
            # classified by classify() with command context — see _NOT_RECOGNIZED_RE.
            # The bare "not found" is also avoided: it swallows "404 not found" and
            # "package not found" which belong to PACKAGE_NOT_FOUND. Use the specific
            # bash form instead.
            "command not found",
        ],
    ),
    (
        ErrorClass.PERMISSION_DENIED,
        [
            "access is denied",
            "permission denied",
            "unauthorizedaccessexception",
            "operation not permitted",
            "access denied",
        ],
    ),
    (
        ErrorClass.PACKAGE_NOT_FOUND,
        [
            "no matching distribution found",
            "could not find a version",
            "package not found",
            "404 not found",
            "no such package",
            "error: package id",  # cargo
            "npm err! 404",
        ],
    ),
    (
        ErrorClass.NETWORK_ERROR,
        [
            "connection refused",
            "connection timed out",
            "could not connect",
            "network unreachable",
            "name or service not known",
            "ssl: certificate_verify_failed",
            "proxyerror",
            "failed to establish a new connection",
            "getaddrinfo",
        ],
    ),
    (
        ErrorClass.ENV_SCOPE_MISMATCH,
        [
            "no module named",  # python import inside wrong env — real scope issue
        ],
    ),
    (
        ErrorClass.COMMAND_SYNTAX,
        [
            "invalid option",
            "unrecognized option",
            "unknown option",
            "usage:",
            "invalid argument",
            "unexpected argument",
            "the argument",
            "parameter cannot be found",
            "does not accept argument",
            # PowerShell parser errors — a malformed command, not a missing tool. The
            # recovery is to regenerate the command, so classify as SYNTAX not UNKNOWN.
            "parsererror",
            "unexpected token",
            "missing closing",
            "the string is missing the terminator",
            # Windows filesystem-operation conflicts (WinError 183/267): the operation
            # shape is wrong for the current state (e.g. create over an existing entry).
            "cannot create a file when that file already exists",
            "the directory name is invalid",
            # Malformed internal tool call surfaced by fileops.dispatch, and the agent's
            # own "unresolved placeholder" invariant — both mean: fix the emitted call.
            "wrong args",
            "positional argument",
            "placeholders not filled",
        ],
    ),
    (
        ErrorClass.TIMEOUT,
        [
            "timed out",
            "timeout expired",
            "deadline exceeded",
        ],
    ),
]


# What the orchestrator is ALLOWED to attempt for each class.
ALLOWED_RECOVERIES: dict[ErrorClass, list[str]] = {
    ErrorClass.INVALID_EXECUTABLE: [
        "delete_corrupt_binary",
        "reinstall",
        "discover_real_path",
    ],
    ErrorClass.FILE_NOT_FOUND: [
        "locate",
        "install",
        "create_parent_dirs",
        "use_alternative_path",
    ],
    ErrorClass.PERMISSION_DENIED: [
        "fix_permissions",
        "run_as_admin",
        "use_user_install",
    ],
    ErrorClass.PACKAGE_NOT_FOUND: [
        "search_registry",
        "install_alternative",
        "use_prebuilt_wheel",
    ],
    ErrorClass.NETWORK_ERROR: [
        "retry",
        "use_offline_cache",
        "change_registry_mirror",
    ],
    ErrorClass.ENV_SCOPE_MISMATCH: [
        "install_globally",
        "activate_venv",
        "use_absolute_path",
    ],
    ErrorClass.COMMAND_SYNTAX: [
        "correct_flags",
        "use_alternative_command",
        "run_discovery_for_syntax",
    ],
    ErrorClass.TIMEOUT: [
        "retry_with_longer_timeout",
        "split_into_smaller_steps",
    ],
    ErrorClass.UNKNOWN: [],  # no automated recovery — requires human input
}

# What is STRICTLY FORBIDDEN regardless of error class.
# These actions caused known catastrophic failures (overwrite-binary bug, etc.).
FORBIDDEN_ALWAYS: list[str] = [
    "write_placeholder",  # writing placeholder text to any path
    "overwrite_executable",  # writing text content to a known executable path
    "create_fake_output",  # pretending an artifact was created without creating it
    "claim_completion_without_verify",  # marking done without running verify
]


def classify(output: str, exit_code: int = 1, command: str = "") -> ErrorClass:
    """
    Classify an error from command output + exit code (+ optional command).
    Returns the most specific matching ErrorClass, or UNKNOWN.

    The classifier is signal-based (output substrings), not command-specific.
    It generalises across shells, OSes, and package managers.

    The optional `command` disambiguates "not recognized" errors: a wrong-shell
    construct (bash builtin under PowerShell) is COMMAND_SYNTAX, while a genuinely
    absent executable is FILE_NOT_FOUND.
    """
    if exit_code == 0:
        return ErrorClass.UNKNOWN  # not an error

    lower = (output or "").lower()

    # ── Disambiguate "is not recognized" (PowerShell) ──────────────────────
    # The offending token decides: a Unix shell builtin/coreutil means the
    # command used the wrong shell grammar (COMMAND_SYNTAX), not a missing tool.
    if "is not recognized" in lower:
        # A fileops-style call (verb|arg|arg, no space around the pipe) that
        # leaked to the shell is a MALFORMED call, not a missing installable
        # tool. Recovery = regenerate the command (COMMAND_SYNTAX), never refute
        # a file's existence (FILE_NOT_FOUND). Observed: `test-path-exists|
        # postcss.config.js|true` was refuting a file the shell never checked.
        if re.match(r"^\s*[\w.\-]+\|\S", command or ""):
            return ErrorClass.COMMAND_SYNTAX
        token = ""
        m = _NOT_RECOGNIZED_RE.search(output or "")
        if m:
            token = m.group(1).strip().lower()
        # Fall back to the first token of the command if the error didn't name one.
        if not token and command:
            token = command.strip().split()[0].lower() if command.strip() else ""
        # Strip a path/extension to get the bare command name.
        bare = token.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].removesuffix(".exe")
        if bare in _UNIX_SHELL_BUILTINS:
            return ErrorClass.COMMAND_SYNTAX
        # Genuinely unknown executable — treat as missing tool.
        return ErrorClass.FILE_NOT_FOUND

    for cls, signals in _SIGNAL_TABLE:
        if any(sig in lower for sig in signals):
            return cls
    return ErrorClass.UNKNOWN


def is_missing_tool_signal(output: str, command: str = "") -> bool:
    """SINGLE OWNER of the question "does this output prove the tool is absent?".

    True ONLY for a genuine "the shell could not find this command" signal —
    NOT for empty/filtered output (a discovery command whose filter matched
    nothing: `Get-NetRoute | Where …`, `netstat | findstr DNS`), and NOT for a
    missing *path* (that's a file, not the tool). Empty output is inconclusive:
    treating it as absence falsely refutes real tools and blocks their reuse.

    Replaces the per-file "not found" substring lists previously duplicated in
    state.py, reasoning.py and observer.py (one invariant → one owner).
    """
    lower = (output or "").lower()
    if any(
        s in lower
        for s in (
            "command not found",
            "unknown command",
            "not recognized as an internal or external command",
        )
    ):
        return True
    if "is not recognized" in lower:
        # A leaked fileops-style call (verb|arg, no space around the pipe) that
        # the shell rejected is a MALFORMED command, never an absent tool — must
        # not refute existence. A real fileop (locate|…) is dispatched internally
        # and never reaches the shell, so it never hits this "is not recognized"
        # path. Keeps this predicate consistent with classify() (→ COMMAND_SYNTAX).
        if re.match(r"^\s*[\w.\-]+\|\S", command or ""):
            return False
        # A Unix builtin under PowerShell is wrong-shell syntax, not a missing
        # tool — same disambiguation classify() uses.
        m = _NOT_RECOGNIZED_RE.search(output or "")
        token = (
            m.group(1).strip().lower()
            if m
            else (command.strip().split()[0].lower() if command.strip() else "")
        )
        bare = token.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].removesuffix(".exe")
        return bool(bare) and bare not in _UNIX_SHELL_BUILTINS
    # The dedicated `locate` probe reports "<tool>: not found on PATH …" — for
    # that probe (our own fileop verb, not a tool/OS catalog) "not found" is
    # definitive. Bare "not found" stays scoped here to avoid swallowing
    # "404 not found" / "package not found" in install/network contexts.
    if command.strip().startswith("locate") and "not found" in lower:
        return True
    return False


def powershell_grammar_issues(command: str) -> list[str]:
    """SINGLE OWNER of "is this bash grammar that PowerShell 5.1 cannot run?".

    Returns human-readable correction hints so the runtime can hand the coder a
    precise signal INSTEAD of running the command, failing, and misclassifying.
    Empty list = no known bash-ism. This is pure shell grammar (reuses the
    POSIX-builtin set), never a per-tool catalog.
    """
    issues: list[str] = []
    c = command or ""
    # Pipeline chain operators — PowerShell 5.1 has neither && nor ||.
    if re.search(r"(?<![&|])&&(?!&)", c):
        issues.append(
            "`&&` is invalid in PowerShell 5.1 — use `;` to chain, "
            "or `if ($?) { <next> }` to run only on success"
        )
    if re.search(r"(?<!\|)\|\|(?!\|)", c):
        issues.append("`||` is invalid in PowerShell 5.1 — use `; if (-not $?) { <next> }`")
    # POSIX test / [ ] existence checks are builtins that do not exist as cmdlets.
    first = c.strip().split()[0] if c.strip() else ""
    if first in ("test", "[", "[["):
        issues.append(
            "`test` / `[ ]` is a POSIX builtin absent in PowerShell — "
            "use `Test-Path <path>` (returns $true/$false)"
        )
    # bash null sink.
    if "/dev/null" in c:
        issues.append(
            "`/dev/null` does not exist on Windows — use `$null` (e.g. redirect with `2>$null`)"
        )
    return issues


def allowed_recoveries(cls: ErrorClass) -> list[str]:
    return ALLOWED_RECOVERIES.get(cls, [])


def is_recovery_allowed(cls: ErrorClass, proposed_recovery: str) -> bool:
    """True if the proposed recovery is in the allowed set for this error class."""
    if proposed_recovery in FORBIDDEN_ALWAYS:
        return False
    allowed = allowed_recoveries(cls)
    if not allowed:
        return False
    return proposed_recovery in allowed


def is_recovery_forbidden(proposed_recovery: str) -> tuple[bool, str]:
    """Check global forbidden list regardless of error class. Returns (forbidden, reason)."""
    if proposed_recovery in FORBIDDEN_ALWAYS:
        return True, f"recovery action '{proposed_recovery}' is globally forbidden"
    return False, ""


def classify_and_describe(output: str, exit_code: int = 1) -> tuple[ErrorClass, list[str]]:
    """Convenience: classify + return allowed recoveries."""
    cls = classify(output, exit_code)
    return cls, allowed_recoveries(cls)
