"""Session manager — one persistent shell session per agent run.

Maintains a single subprocess shell with persistent cwd and environment.
Registers all child processes. Handles safe shutdown and recovery.
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from .. import trace
from ..config import RUNTIME_DIR
from .confinement import Confinement
from .template_guard import (
    recreates_the_workspace_dir,
    self_truncating_redirect,
    unresolved_placeholder,
)

SESSIONS_FILE = RUNTIME_DIR / "sessions.json"
REGISTRY_FILE = RUNTIME_DIR / "process_registry.json"


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def _save_json(path: Path, data: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Process registry
# ---------------------------------------------------------------------------


class ProcessRegistry:
    def __init__(self):
        self._lock = threading.Lock()

    def register(self, owner: str, parent_pid: int, child_pid: int, kind: str) -> None:
        with self._lock:
            data = _load_json(REGISTRY_FILE)
            data.setdefault("processes", []).append(
                {
                    "owner": owner,
                    "parent_pid": parent_pid,
                    "child_pid": child_pid,
                    "type": kind,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            )
            _save_json(REGISTRY_FILE, data)

    def remove(self, child_pid: int) -> None:
        with self._lock:
            data = _load_json(REGISTRY_FILE)
            data["processes"] = [
                p for p in data.get("processes", []) if p.get("child_pid") != child_pid
            ]
            _save_json(REGISTRY_FILE, data)

    def all_children(self) -> list[int]:
        with self._lock:
            data = _load_json(REGISTRY_FILE)
            return [p["child_pid"] for p in data.get("processes", [])]

    def clear(self) -> None:
        _save_json(REGISTRY_FILE, {"processes": []})


REGISTRY = ProcessRegistry()


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

_LONG_CMDS = (
    "npx",
    "npm",
    "pnpm",
    "yarn",
    "bun",
    "shadcn",
    "create-next",
    "pip",
    "apt",
    "yum",
    "brew",
    "git clone",
)


# ── Robust filesystem operations ─────────────────────────────────────────────
# Windows path names can be pathological: trailing dots/spaces, reserved names
# (CON, NUL...), paths > 260 chars, unicode. Shell commands (Remove-Item, rd)
# all fail on these. We use Python's os/shutil with \\?\ prefix to bypass all
# Windows path restrictions.


def _win_long(p: str) -> str:
    """Prefix an absolute Windows path with \\?\\ to bypass all restrictions."""
    p = str(Path(p).resolve())
    if not p.startswith("\\\\?\\"):
        p = "\\\\?\\" + p
    return p


def _safe_remove(path: str) -> tuple[bool, str]:
    """
    Remove a file or directory tree regardless of path quirks.
    Uses os.unlink / shutil.rmtree with \\?\\ prefix on Windows.
    Returns (success, message).
    """
    import shutil

    p = Path(path).resolve()
    if not p.exists():
        return True, f"already absent: {p}"

    if sys.platform == "win32":
        raw = _win_long(str(p))
        raw_p = Path(raw)
        try:
            if raw_p.is_file() or raw_p.is_symlink():
                os.unlink(raw)
            else:
                # Walk bottom-up, remove each entry with long path
                for root, dirs, files in os.walk(raw, topdown=False):
                    for f in files:
                        try:
                            os.unlink(os.path.join(root, f))
                        except Exception:
                            # Fallback: attrib -r then unlink
                            fp = os.path.join(root, f)
                            os.chmod(fp, 0o777)
                            os.unlink(fp)
                    for d in dirs:
                        dp = os.path.join(root, d)
                        try:
                            os.rmdir(dp)
                        except Exception:
                            shutil.rmtree(dp, ignore_errors=True)
                os.rmdir(raw)
            return True, f"removed: {p}"
        except Exception as e:
            # Last resort: robocopy trick — mirror an empty dir over the target
            try:
                import tempfile

                with tempfile.TemporaryDirectory() as empty:
                    subprocess.run(
                        ["robocopy", empty, str(p), "/MIR", "/NFL", "/NDL", "/NJH", "/NJS"],
                        capture_output=True,
                    )
                shutil.rmtree(str(p), ignore_errors=True)
                return True, f"removed via robocopy: {p}"
            except Exception as e2:
                return False, f"failed: {e} | robocopy fallback: {e2}"
    else:
        try:
            if p.is_file() or p.is_symlink():
                p.unlink()
            else:
                import shutil

                shutil.rmtree(str(p))
            return True, f"removed: {p}"
        except Exception as e:
            return False, str(e)


def _safe_mkdir(path: str) -> tuple[bool, str]:
    """Create directory tree, no-op if already exists."""
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return True, f"created: {path}"
    except Exception as e:
        return False, str(e)


def _normalize_to_powershell(cmd: str) -> str:
    """
    Intercept filesystem-destructive commands and route them through
    _safe_remove / _safe_mkdir instead of PowerShell cmdlets.
    Returns a sentinel string '__SAFE_FS__:<op>:<path>' that session.run()
    detects and executes natively.
    """
    import re

    c = cmd.strip()

    # Unwrap cmd.exe /c "..." or cmd /c "..." wrappers — extract inner command
    # Also handle compound commands joined with && — process only the first part
    # that matches a known destructive pattern, skip the rest
    m = re.match(r'^cmd(?:\.exe)?\s+/[cC]\s+"?(.+?)"?\s*$', c, re.IGNORECASE)
    if m:
        inner = m.group(1).strip()
        # Split on && and normalize only the first part we can handle
        parts = re.split(r"\s*&&\s*", inner)
        for part in parts:
            normalized = _normalize_to_powershell(part.strip())
            if normalized.startswith("__SAFE_FS__:"):
                return normalized
        return _normalize_to_powershell(parts[0].strip())

    # del /f /s /q <path> — cmd.exe delete syntax; path may have trailing !
    m = re.match(r"^del\s+(?:/[fFsqaA]\s+)*(.+)$", c, re.IGNORECASE)
    if m:
        path = m.group(1).strip().strip('"').strip("'").rstrip("!").rstrip()
        if path:
            return f"__SAFE_FS__:rm:{path}"
        return c  # no path — leave as-is, will fail gracefully

    # rm -rf / rm -f / rm  AND  rd /s /q (cmd.exe style)
    m = re.match(r"^rm\s+(?:-rf?\s+|-f\s+)?(.+)$", c, re.IGNORECASE)
    if m:
        return f"__SAFE_FS__:rm:{m.group(1).strip()}"
    # rd / rmdir — skip all /x flags, last non-flag token is the path
    m = re.match(r"^(?:rd|rmdir)\s+((?:/[a-zA-Z]\s+)*)(.+)$", c, re.IGNORECASE)
    if m:
        path = m.group(2).strip().strip('"').strip("'")
        if path:
            return f"__SAFE_FS__:rm:{path}"

    # mkdir -p / mkdir
    m = re.match(r"^mkdir\s+(?:-p\s+)?(.+)$", c, re.IGNORECASE)
    if m:
        return f"__SAFE_FS__:mkdir:{m.group(1).strip()}"

    # New-Item -ItemType File without -Force fails if the file already exists.
    # Add -Force to make file creation idempotent (matches touch semantics).
    # Only for File items — Directory creation intentionally keeps default behavior.
    if re.search(r"New-Item\b.*-ItemType\s+File\b", c, re.IGNORECASE) and "-Force" not in c:
        c = c + " -Force"

    # PowerShell 5.1 does not support && as statement separator — replace with ;
    # This covers "cmd1 && cmd2" patterns that slip through normalization
    if "&&" in c:
        c = c.replace("&&", ";")
        return c

    # Standard Unix → PowerShell translations for non-destructive ops
    translations = [
        (r"^cp\s+-r\s+(\S+)\s+(\S+)$", r"Copy-Item -Recurse '\1' '\2'"),
        (r"^cp\s+(\S+)\s+(\S+)$", r"Copy-Item '\1' '\2'"),
        (r"^mv\s+(\S+)\s+(\S+)$", r"Move-Item '\1' '\2'"),
        (r"^touch\s+(.+)$", r"New-Item -ItemType File '\1' -Force | Out-Null"),
        (r"^cat\s+(.+)$", r"Get-Content '\1'"),
        (r"^ls\s*(.*)$", r"Get-ChildItem \1"),
        (r"^which\s+(.+)$", r"(Get-Command '\1' -ErrorAction SilentlyContinue).Source"),
        (
            r"^find\s+(\S+)\s+-name\s+(\S+)$",
            r"Get-ChildItem -Recurse -Path '\1' -Filter '\2' | Select-Object FullName",
        ),
    ]
    for pattern, replacement in translations:
        if re.match(pattern, c, re.IGNORECASE):
            return re.sub(pattern, replacement, c, flags=re.IGNORECASE)

    return c


def _autoyes_package_runner(command: str) -> str:
    """Insert the non-interactive 'yes' flag into a package-runner invocation so
    its "Need to install ... Ok to proceed? (y)" prompt auto-accepts in a batch
    context. Generic over the runner grammar, not any specific package.

    npx <x>      → npx --yes <x>   (only if no -y/--yes already present)
    (pnpm dlx / bunx auto-install without prompting; left unchanged.)
    """
    import re as _re

    # Only the bare `npx` runner prompts; add --yes right after it, once.
    def _fix(m):
        head = m.group(0)
        return (
            head
            if _re.search(r"\s-y\b|\s--yes\b", command[m.start() : m.start() + 40])
            else head + " --yes"
        )

    return _re.sub(r"(?<![\w./-])npx(?=\s)", _fix, command, count=1)


_INTERACTIVE_SIGNALS = (
    "select",
    "choose",
    "arrow keys",
    "use arrow",
    "(y/n)",
    "yes/no",
    "press enter",
)
_HARD_FAIL = (
    "access is denied",
    "permission denied",
    "is not recognized as an internal",
    "cannot find path",
    "cannot find the path",
    "could not find a part of the path",
    "fatal error",
    "enoent",
    "no such file",
)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError, SystemError):
        return False


# Variables that change how the OS RESOLVES a program, loads a library, or finds its own
# system files. A model-authored `$env:PATH='C:\evil'` used to be written straight into the
# AGENT's own os.environ, and every subsequent Popen in this file invokes its target by BARE
# NAME — powershell.exe, bash, taskkill, robocopy. Poisoning PATH therefore redirected not just
# the next command but the shutdown and kill paths too, and `predicates.tool_on_path` /
# `fileops.locate` then reported the planted binary as the system tool. On POSIX, LD_PRELOAD is
# unconditional code execution in the next child. One token, full agent-integrity compromise.
_ENV_DENY = frozenset(
    {
        "PATH",
        "PATHEXT",
        "PSMODULEPATH",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "LD_AUDIT",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONHOME",
        "NODE_OPTIONS",
    }
)


def _reject_env_rebind(var: str) -> bool:
    """True when `var` must not be bound from a model-authored command."""
    return var.upper() in _ENV_DENY


class Session:
    """One persistent shell session. Reuse for all commands in a task."""

    def __init__(self, workspace: str | Path, session_id: str | None = None):
        self.session_id = session_id or f"sysops_{int(time.time())}"
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._cwd: Path = self.workspace
        self._env = self._build_env()
        self._children: list[int] = []
        self._lock = threading.Lock()
        self._active = True
        # Write confinement, scoped to the workspace the operator named. It used to be
        # opt-in via SISTEMISTA_CONFINE_ROOT, which only the three benchmark harnesses ever
        # set — so in every production run this was None and the `if self._confine is not
        # None:` guards below silently evaluated to nothing, `_ALWAYS_FATAL` included.
        # Reading outside the root stays allowed (a sysops agent must diagnose the system);
        # it is WRITES that are scoped, and SISTEMISTA_UNCONFINED=1 is the explicit opt-out.
        self._confine = Confinement.current()

        self._save_state()

        # Register signal handlers for safe shutdown
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self._signal_handler)
            except (OSError, ValueError):
                pass

    def _build_env(self) -> dict:
        env = os.environ.copy()
        # Strip any active virtual environment so workspace subprocesses see
        # system Python/PATH, not Sistemista's own venv.
        venv_dir = env.pop("VIRTUAL_ENV", None)
        if venv_dir:
            scripts = os.path.join(venv_dir, "Scripts" if sys.platform == "win32" else "bin")
            env["PATH"] = os.pathsep.join(
                p for p in env.get("PATH", "").split(os.pathsep) if not p.startswith(scripts)
            )
            env.pop("VIRTUAL_ENV_PROMPT", None)
        return env

    def _signal_handler(self, signum, frame):
        self.shutdown()
        sys.exit(0)

    def _save_state(self) -> None:
        _save_json(
            SESSIONS_FILE,
            {
                "active": self._active,
                "session_id": self.session_id,
                "main_pid": os.getpid(),
                "children": self._children,
                "cwd": str(self._cwd),
                "workspace": str(self.workspace),
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )

    def clear_workspace(self) -> tuple[bool, str]:
        """Remove all entries inside workspace without deleting the workspace itself."""
        errors = []
        for entry in list(self.workspace.iterdir()):
            ok, msg = _safe_remove(str(entry))
            if not ok:
                errors.append(msg)
        if errors:
            return False, "; ".join(errors)
        return True, f"workspace cleared: {self.workspace}"

    def _enforce_workspace(self, path: Path) -> Path:
        """Ensure path stays within workspace. Falls back to workspace root."""
        try:
            path.resolve().relative_to(self.workspace)
            return path
        except ValueError:
            return self.workspace

    def cd(self, path: str) -> tuple[str, int]:
        """Change working directory within workspace."""
        p = Path(path) if os.path.isabs(path) else (self._cwd / path)
        p = p.resolve()
        p = self._enforce_workspace(p)
        if p.exists():
            self._cwd = p
            self._save_state()
            return f"cwd → {self._cwd}", 0
        return f"path does not exist: {p}", 1

    def run(self, command: str, timeout: float | None = None) -> tuple[str, int]:
        """
        Execute command in the persistent session cwd.
        Returns (output, exit_code).
        """
        # Dev server commands never exit — detect and cap at 15s so we get
        # enough output to verify startup without hanging forever.
        _DEV_SERVER_PATTERNS = (
            "run dev",
            "run start",
            "next dev",
            "vite",
            "uvicorn",
            "flask run",
            "fastapi run",
        )
        _is_dev_server = any(p in command.lower() for p in _DEV_SERVER_PATTERNS)

        if timeout is None:
            if _is_dev_server:
                timeout = 15.0  # short cap: read startup output then move on
            elif any(kw in command.lower() for kw in _LONG_CMDS):
                timeout = 240.0  # scaffold/install: bounded to 4 min (was 600 —
                # longer than the whole 2-5 min task budget and
                # longer than any real install; a command over
                # this is stuck, not slow)
            else:
                timeout = 30.0

        # Normalize Unix commands; intercept safe-fs sentinels
        if sys.platform == "win32":
            command = _normalize_to_powershell(command)

        # Invariant #2 — no unresolved placeholder reaches the shell. Enforced HERE, where a
        # command becomes a process, not at one of the several places that build one. The
        # predicate was previously consulted only for coder-authored commands, so the
        # planner's `& "$DISCOVERED_PATH" --version` executed verbatim.
        leak = unresolved_placeholder(command)
        if leak:
            trace.emit(
                "exec",
                command=command,
                exit_code=126,
                blocked=True,
                reason=f"unresolved placeholder {leak}",
            )
            return f"PLACEHOLDER LEAK: refused — {leak} was never substituted", 126

        # A pipeline that reads a file it also redirects into truncates it to zero bytes.
        # Measured on T01 and T20: a correct artifact, captured a moment earlier, replaced by
        # an empty file. This is a property of shells, not of a product, so the runtime
        # refuses it rather than teaching the model to avoid it.
        # A bare `mkdir <workspace-name>` inside the workspace builds an empty folder and
        # nothing else. The initializer runs here; if it insists on naming its own directory,
        # `workspace_shape` hoists the result up afterwards.
        dup = recreates_the_workspace_dir(command, self.workspace)
        if dup:
            # A bare `mkdir <workspace-name>` inside the workspace is a NO-OP, not a failure:
            # the project root already exists (it IS the workspace). Returning 126 here made the
            # step a failed MODIFY prerequisite, which HALTED the plan; the replan then led with
            # the same mkdir and framework-init DEADLOCKED (`workspace is empty`, known-issues /
            # debt #7). The prerequisite is already satisfied, so this is exit 0 — the plan
            # proceeds to the real initializer, and `workspace_shape` hoists a nested scaffold up.
            trace.emit(
                "exec",
                command=command,
                exit_code=0,
                blocked=True,
                skipped=True,
                reason=f"no-op: recreates the workspace directory {dup!r}",
            )
            return (
                f"SKIPPED (no-op): the workspace already IS the project root — creating "
                f"'{dup}' inside it is unnecessary. Run the initializer here; a nested "
                f"scaffold is hoisted up automatically."
            ), 0

        trunc = self_truncating_redirect(command)
        if trunc:
            trace.emit(
                "exec",
                command=command,
                exit_code=126,
                blocked=True,
                reason=f"self-truncating redirection into {trunc}",
            )
            return (
                f"SELF-TRUNCATING REDIRECT: refused — {trunc} is both an input and the "
                f"redirection target; the shell would empty it"
            ), 126

        # Write confinement, on the FINAL command string (post-normalisation): the shell
        # is about to see exactly this. A block is a non-zero exit, not an exception —
        # the agent observes it, classifies it and recovers, as with any refusal.
        reason = self._confine.check(command, cwd=self._cwd)
        if reason:
            trace.emit("exec", command=command, exit_code=126, blocked=True, reason=reason)
            return f"CONFINEMENT: refused — {reason}", 126

        if command.startswith("__SAFE_FS__:"):
            _, op, path = command.split(":", 2)
            # Resolve relative paths against cwd
            p = path.strip().strip("'\"")
            if not os.path.isabs(p):
                p = str(self._cwd / p)
            reason = self._confine.check_path(p, cwd=self._cwd)
            if reason:
                trace.emit("exec", command=command, exit_code=126, blocked=True, reason=reason)
                return f"CONFINEMENT: refused — {reason}", 126
            if op == "rm":
                ok, msg = _safe_remove(p)
            elif op == "mkdir":
                ok, msg = _safe_mkdir(p)
            else:
                ok, msg = False, f"unknown safe-fs op: {op}"
            trace.emit(
                "exec",
                command=command,
                exit_code=0 if ok else 1,
                blocked=False,
                output_head=msg[:200],
            )
            return msg, 0 if ok else 1

        # Extract and persist $env:VAR=value assignments so they survive across steps.
        # Invariant: env var assignment is session-level state, not a per-subprocess
        # ephemeral. Splitting into separate steps loses the env mutation.
        command = self._extract_env_assignments(command)

        # Strip pure cd/Set-Location from compound commands; handle cwd change
        command = self._resolve_set_location(command)

        # A5: a package-runner (npx/pnpm dlx/bunx) that must install a package
        # first prompts "Ok to proceed? (y)". In a non-interactive batch it must
        # auto-accept, else it blocks on stdin. Insert the runner's yes-flag once.
        command = _autoyes_package_runner(command)

        if sys.platform == "win32":
            args = [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ]
        else:
            args = ["bash", "-c", command]

        try:
            proc = subprocess.Popen(
                args,
                cwd=str(self._cwd),
                env=self._run_env(),
                # A1: batch commands are NON-interactive. Give the child an empty
                # stdin (EOF) so any unexpected prompt ("Ok to proceed?", "Overwrite?")
                # fails fast instead of blocking forever until the outer timeout.
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            REGISTRY.register("sysops", os.getpid(), proc.pid, "subprocess")
            with self._lock:
                self._children.append(proc.pid)
            self._save_state()

            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
                self._unregister(proc.pid)
                return f"timeout after {timeout}s", 1

            self._unregister(proc.pid)
            # Strip ANSI before anyone downstream reads this text. PowerShell/npm
            # emit colour codes (e.g. `\x1b[31m"_try"\x1b[39m`) that corrupt the
            # substring matching in error_classifier / is_missing_tool_signal —
            # a coloured "is not recognized" was silently classified UNKNOWN.
            # Reuses the single ANSI owner (tools.terminal); the PTY path keeps
            # raw bytes (invariant 8) — this only touches batch subprocess output.
            from .terminal import _strip_ansi

            output = _strip_ansi(stdout + "\n" + stderr).strip()

            trace.emit(
                "exec",
                command=command,
                exit_code=proc.returncode,
                blocked=False,
                cwd=str(self._cwd),
                output_head=output[:400],
            )

            if proc.returncode != 0:
                return output, 1

            lower = output.lower()
            if any(kw in lower for kw in _HARD_FAIL):
                return output, 1

            return output, 0

        except Exception as e:
            return str(e), 1

    def _run_env(self) -> dict:
        """Per-command env: base session env + the WORKSPACE's own venv bin dir
        prepended to PATH if one exists (C4). Console scripts a project venv
        installs (django-admin, pytest, black, uvicorn…) live in that bin dir;
        without this they are 'not recognized' because each step is a fresh
        subprocess that never 'activated' the venv. Generic: any workspace venv,
        any tool — no per-tool knowledge."""
        env = dict(self._env)
        bin_name = "Scripts" if sys.platform == "win32" else "bin"
        for venv in (".venv", "venv", "env"):
            vbin = self.workspace / venv / bin_name
            if vbin.is_dir():
                env["PATH"] = str(vbin) + os.pathsep + env.get("PATH", "")
                break
        return env

    def _extract_env_assignments(self, command: str) -> str:
        """
        Parse `$env:VAR='value'` (PowerShell) or `export VAR=value` (bash)
        assignments out of the command and persist them into self._env so that
        all subsequent subprocess calls inherit them.

        Returns the command with pure assignment-only statements removed.
        A compound command like `$env:FOO='x'; pip install bar` keeps the
        `pip install bar` part and injects FOO into the session env.

        Invariant: env var assignment is session state, not process-local ephemeral.
        This ensures that setting CUDAHOSTCXX, CMAKE_ARGS, etc. in one step
        actually affects the build tool invoked in the next step.
        """
        import re as _re

        if sys.platform == "win32":
            # Match one or more $env:VAR='value' or $env:VAR="value" statements,
            # separated by semicolons, possibly followed by a real command.
            # Pattern: `$env:NAME='val'` or `$env:NAME="val"`
            env_pat = _re.compile(
                r'\$env:([A-Za-z_][A-Za-z0-9_]*)=["\']([^"\']*)["\']',
                _re.IGNORECASE,
            )
            # Split on ; to find assignment-only vs real-command parts
            parts = [p.strip() for p in command.split(";")]
            real_parts = []
            for part in parts:
                if not part:
                    continue
                m = env_pat.fullmatch(part.strip())
                if m:
                    # Pure assignment — extract and persist in session env
                    var, val = m.group(1).upper(), m.group(2)
                    if _reject_env_rebind(var):
                        trace.emit(
                            "exec",
                            command=part[:200],
                            blocked=True,
                            reason=f"refused to rebind {var}",
                        )
                        continue
                    # SESSION env only. This used to also write os.environ — the agent's own
                    # process state — which is not session state and is not the model's to set.
                    self._env[var] = val
                else:
                    real_parts.append(part)
            return "; ".join(real_parts) if real_parts else ""
        else:
            # bash: `export VAR=value` or `VAR=value` at start of line
            export_pat = _re.compile(
                r"^export\s+([A-Za-z_][A-Za-z0-9_]*)=(.+)$",
                _re.MULTILINE,
            )

            def _absorb(m):
                var, val = m.group(1), m.group(2).strip().strip("'\"")
                if _reject_env_rebind(var):
                    trace.emit(
                        "exec",
                        command=m.group(0)[:200],
                        blocked=True,
                        reason=f"refused to rebind {var}",
                    )
                    return ""
                self._env[var] = val
                return ""

            cleaned = export_pat.sub(_absorb, command).strip().strip(";").strip()
            return cleaned if cleaned else ""

    def _resolve_set_location(self, command: str) -> str:
        """
        If command starts with 'Set-Location X;' or 'cd X;', update cwd
        and return the remainder. Otherwise return command unchanged.
        """
        stripped = command.strip()
        lower = stripped.lower()

        if ";" in stripped and lower.startswith(("set-location ", "cd ")):
            idx = stripped.index(";")
            nav_part = stripped[:idx].strip()
            rest = stripped[idx + 1 :].strip()
            path = nav_part.split(None, 1)[-1].strip().strip("'\"")
            p = Path(path) if os.path.isabs(path) else (self._cwd / path)
            p = p.resolve()
            if p.exists():
                self._cwd = self._enforce_workspace(p)
                self._save_state()
            return rest  # run only the remainder in updated cwd

        return command

    def _unregister(self, pid: int) -> None:
        REGISTRY.remove(pid)
        with self._lock:
            self._children = [c for c in self._children if c != pid]
        self._save_state()

    def shutdown(self, timeout: float = 10.0) -> None:
        """Safe shutdown: terminate all children, clear registry."""
        if not self._active:
            return
        self._active = False

        deadline = time.monotonic() + timeout
        children = list(self._children)

        for pid in children:
            if _pid_alive(pid):
                try:
                    if sys.platform == "win32":
                        subprocess.run(
                            ["taskkill", "/F", "/PID", str(pid)],
                            capture_output=True,
                            timeout=3,
                        )
                    else:
                        os.kill(pid, signal.SIGTERM)
                except Exception:
                    pass

        # Wait for children to exit
        while time.monotonic() < deadline:
            alive = [p for p in children if _pid_alive(p)]
            if not alive:
                break
            time.sleep(0.2)

        # Force kill stragglers
        for pid in children:
            if _pid_alive(pid):
                try:
                    if sys.platform == "win32":
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True
                        )
                    else:
                        os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass

        REGISTRY.clear()
        _save_json(SESSIONS_FILE, {"active": False, "session_id": self.session_id})


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


def recover_sessions() -> None:
    """On startup: clean up any leftover sessions from previous crashes."""
    data = _load_json(SESSIONS_FILE)
    if not data.get("active"):
        return

    children = data.get("children", [])
    for pid in children:
        if _pid_alive(pid):
            try:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
                else:
                    os.kill(pid, signal.SIGTERM)
            except Exception:
                pass

    REGISTRY.clear()
    _save_json(SESSIONS_FILE, {"active": False, "recovered": True})
