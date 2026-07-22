"""
Native file operations tool for Sistemista.

The supervisor (4B) decides WHAT to write and to which file.
The executor dispatches these as TOOL() action tokens.
The orchestrator calls this module — no shell involved, no quoting issues.

Tools available to the executor:
  write_file(path, content)       — create or overwrite a file
  read_file(path)                 — read a file, returns content string
  append_file(path, content)      — append to existing file
  replace_in_file(path, old, new) — exact string replacement
  list_dir(path)                  — list directory contents
  web_search(query)               — search DuckDuckGo, no API key needed
"""

import inspect as _inspect
import os
import shutil
import sys
from pathlib import Path

from .. import trace
from . import predicates
from .confinement import Confinement
from .web_search import search as _web_search


def locate(tool: str, cwd: Path) -> tuple[bool, str]:
    """
    Find the absolute path of an executable, portably, without a shell.
    Uses the same resolver the OS uses (PATHEXT-aware on Windows). This avoids
    shell quirks like PowerShell aliasing `where` to `Where-Object`.
    Returns (found, "<tool> -> <path>" or "<tool>: not found").

    Strips the currently active venv from PATH before searching so that
    Sistemista's own venv Python does not shadow system executables.

    On Windows, if not found on PATH, additionally queries vswhere.exe (the
    official Visual Studio discovery tool) so that MSVC build tools are found
    regardless of whether vcvarsall.bat has been run. This is the correct
    mechanism — not hardcoded paths — because vswhere knows about all VS versions.
    """
    try:
        name = (tool or "").strip().strip("'\"")
        # Build a PATH that excludes the currently active venv (same logic as
        # Session._build_env) so we report the system executable, not our own.
        search_path = os.environ.get("PATH", "")
        venv_dir = os.environ.get("VIRTUAL_ENV", "")
        if venv_dir:
            scripts = os.path.join(
                venv_dir,
                "Scripts" if sys.platform == "win32" else "bin",
            )
            search_path = os.pathsep.join(
                p for p in search_path.split(os.pathsep) if not p.startswith(scripts)
            )
        # Include Python user-install Scripts directory so tools installed via
        # `pip install --user` are found even when their dir is not yet on PATH.
        # Uses Python's own site module — the same source pip uses for --user paths.
        try:
            import site as _site

            _user_base = _site.getuserbase()
            if _user_base:
                _user_scripts = os.path.join(
                    _user_base,
                    f"Python{sys.version_info.major}{sys.version_info.minor}",
                    "Scripts" if sys.platform == "win32" else "bin",
                )
                if _user_scripts not in search_path:
                    search_path = search_path + os.pathsep + _user_scripts
        except Exception:
            pass
        path = shutil.which(name, path=search_path)
        if path:
            directory = str(Path(path).parent)
            return True, f"{name} -> {path}\ndirectory: {directory}"

        # On Windows: try vswhere.exe if the tool is not on PATH.
        # vswhere is the official VS discovery tool — it finds MSVC tools
        # that are only accessible after running vcvarsall.bat.
        # Fallback: filesystem scan of standard VS installation roots for
        # prerelease/BuildTools versions that vswhere may not track.
        if sys.platform == "win32":
            vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
            if vswhere.exists():
                import subprocess as _sp

                for vswhere_args in [
                    # First try: -all includes prerelease
                    [
                        str(vswhere),
                        "-all",
                        "-prerelease",
                        "-find",
                        f"VC\\Tools\\MSVC\\**\\bin\\Hostx64\\x64\\{name}",
                    ],
                    # Second try: specific component requirement
                    [
                        str(vswhere),
                        "-all",
                        "-requires",
                        "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                        "-find",
                        f"VC\\Tools\\MSVC\\**\\bin\\Hostx64\\x64\\{name}",
                    ],
                ]:
                    try:
                        out = _sp.check_output(
                            vswhere_args,
                            stderr=_sp.DEVNULL,
                            timeout=10,
                            text=True,
                        ).strip()
                        if out:
                            found_path = out.splitlines()[0].strip()
                            return True, (
                                f"{name} -> {found_path}\n"
                                f"directory: {str(Path(found_path).parent)}\n"
                                f"NOTE: not on PATH — found via vswhere (VS Build Tools)"
                            )
                    except Exception:
                        pass

            # Fallback: scan known VS installation roots (covers BuildTools
            # versions not registered in vswhere, e.g. VS 18/2026 preview).
            # Invariant: sort by MSVC toolset version number (14.x.y) so the
            # newest toolchain is returned first, matching what cmake auto-detects.
            _vs_roots = [
                Path(r"C:\Program Files (x86)\Microsoft Visual Studio"),
                Path(r"C:\Program Files\Microsoft Visual Studio"),
            ]
            # (exe_path, msvc_version_tuple) pairs for sorting
            _candidates: list[tuple] = []
            for vs_root in _vs_roots:
                if not vs_root.exists():
                    continue
                for version_dir in vs_root.iterdir():
                    for sub in ("BuildTools", "Professional", "Enterprise", "Community"):
                        msvc_root = version_dir / sub / "VC" / "Tools" / "MSVC"
                        if not msvc_root.is_dir():
                            continue
                        for msvc_ver_dir in msvc_root.iterdir():
                            exe = msvc_ver_dir / "bin" / "Hostx64" / "x64" / name
                            if exe.is_file():
                                # Parse version tuple for numeric sort: "14.50.35717" → (14, 50, 35717)
                                try:
                                    ver = tuple(int(x) for x in msvc_ver_dir.name.split("."))
                                except ValueError:
                                    ver = (0,)
                                _candidates.append((ver, exe))
            if _candidates:
                # Newest MSVC toolset first (highest version number)
                _candidates.sort(key=lambda x: x[0], reverse=True)
                found_path = str(_candidates[0][1])
                return True, (
                    f"{name} -> {found_path}\n"
                    f"directory: {str(Path(found_path).parent)}\n"
                    f"NOTE: not on PATH — found via filesystem scan (VS Build Tools)"
                )

        # Final fallback: bounded multi-tier discovery (pip, package manager, known dirs)
        try:
            from .discovery import discover as _bounded_discover

            _dresult = _bounded_discover(name)
            if _dresult.found:
                directory = str(Path(_dresult.path).parent)
                return True, (
                    f"{name} -> {_dresult.path}\n"
                    f"directory: {directory}\n"
                    f"NOTE: found via {_dresult.method}"
                )
        except Exception:
            pass

        return False, f"{name}: not found on PATH or known install locations"
    except Exception as e:
        return False, f"[ERROR] locate: {e}"


class _Refused(Exception):
    """A write fileops refused by the confinement filter."""


def _resolve(path: str, cwd: Path, *, write: bool = False) -> Path:
    """The single funnel for every fileops path.

    `fileops` is the SECOND execution owner in this tree: `delegation: fileops` steps never
    reach `session.run`, so the confinement filter wired there does not see them. A guard
    that covers one of two owners is not a guard. Writes resolve through the same predicate;
    reads are left alone, as they are in the shell path.
    """
    p = Path(path)
    if not p.is_absolute():
        p = cwd / p
    resolved = p.resolve()
    if write:
        # The RESOLVED path, and the cwd it was resolved against. Passing the raw relative
        # token let the filter join it to the confinement root while the write actually
        # landed under `cwd` — a different directory whenever a step moved the cwd, which is
        # the case the `_enforce_workspace` guard exists to handle.
        confine = Confinement.current()
        reason = confine.check_path(resolved, cwd=cwd)
        if reason:
            trace.emit(
                "exec", command=f"fileops:write {path}", exit_code=126, blocked=True, reason=reason
            )
            raise _Refused(reason)
    return resolved


def write_file(path: str, content: str, cwd: Path) -> tuple[bool, str]:
    try:
        target = _resolve(path, cwd, write=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        trace.emit("exec", command=f"fileops:write_file {target}", exit_code=0, blocked=False)
        return True, f"[OK] written: {target.name} ({len(content)}B)"
    except _Refused as e:
        return False, f"[ERROR] CONFINEMENT: refused — {e}"
    except Exception as e:
        return False, f"[ERROR] write_file: {e}"


def read_file(path: str, cwd: Path) -> tuple[bool, str]:
    try:
        target = _resolve(path, cwd)
        if not target.exists():
            return False, f"[ERROR] read_file: not found: {path}"
        content = predicates.read_text(target)
        return True, content
    except Exception as e:
        return False, f"[ERROR] read_file: {e}"


def append_file(path: str, content: str, cwd: Path) -> tuple[bool, str]:
    try:
        target = _resolve(path, cwd, write=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write(content)
        trace.emit("exec", command=f"fileops:append_file {target}", exit_code=0, blocked=False)
        return True, f"[OK] appended to: {target.name}"
    except _Refused as e:
        return False, f"[ERROR] CONFINEMENT: refused — {e}"
    except Exception as e:
        return False, f"[ERROR] append_file: {e}"


def replace_in_file(path: str, old: str, new: str, cwd: Path) -> tuple[bool, str]:
    try:
        target = _resolve(path, cwd, write=True)
        if not target.exists():
            return False, f"[ERROR] replace_in_file: not found: {path}"
        content = predicates.read_text(target)
        if old not in content:
            return False, f"[ERROR] replace_in_file: old_string not found in {path}"
        count = content.count(old)
        target.write_text(content.replace(old, new, 1), encoding="utf-8")
        trace.emit("exec", command=f"fileops:replace_in_file {target}", exit_code=0, blocked=False)
        return True, f"[OK] replaced in {target.name} (occurrences: {count})"
    except _Refused as e:
        return False, f"[ERROR] CONFINEMENT: refused — {e}"
    except Exception as e:
        return False, f"[ERROR] replace_in_file: {e}"


def make_dir(path: str, cwd: Path) -> tuple[bool, str]:
    """Create a directory (and any missing parents). Idempotent."""
    try:
        target = _resolve(path, cwd, write=True)
        target.mkdir(parents=True, exist_ok=True)
        trace.emit("exec", command=f"fileops:make_dir {target}", exit_code=0, blocked=False)
        return True, f"[OK] directory ready: {target}"
    except _Refused as e:
        return False, f"[ERROR] CONFINEMENT: refused — {e}"
    except Exception as e:
        return False, f"[ERROR] make_dir: {e}"


def list_dir(path: str, cwd: Path) -> tuple[bool, str]:
    try:
        target = _resolve(path, cwd)
        if not target.exists():
            return False, f"[ERROR] list_dir: not found: {path}"
        entries = sorted(target.iterdir(), key=lambda x: (x.is_file(), x.name))
        lines = [f"{'DIR ' if e.is_dir() else 'FILE'} {e.name}" for e in entries[:60]]
        return True, "\n".join(lines) if lines else "(empty)"
    except Exception as e:
        return False, f"[ERROR] list_dir: {e}"


# ── Dispatch table — executor calls by name ───────────────────────────────────

TOOLS = {
    "write_file": write_file,
    "read_file": read_file,
    "append_file": append_file,
    "replace_in_file": replace_in_file,
    "list_dir": list_dir,
    "make_dir": make_dir,
    "mkdir": make_dir,  # alias: matches shell muscle memory
    "locate": locate,
    "web_search": _web_search,
}


def _normalize_args(fn, name: str, args: list[str]) -> tuple[list[str] | None, str]:
    """Reconcile the arg count the model produced with the tool's real signature.

    The `|`-delimited tool syntax makes two failure modes routine from a 3B model:
    an over-split path (`make_dir|.github|workflows`) and a `|` inside content
    (`write_file|f|a|b`). Rather than crash with a raw TypeError (which classifies as
    UNKNOWN and gives recovery nothing), we normalize by the signature — the first
    parameter is always the path, and surplus args are absorbed by the LAST parameter:
    joined with '/' when that last param IS the path (single-arg tools → rejoin the
    split path), else with '|' (content that legitimately contained a pipe).
    Too few args → an actionable error naming the exact expected shape.
    """
    # cwd is injected by dispatch, so it never comes from the model. Optional params
    # (those with a default, e.g. web_search's max_results) set the max but not the min.
    params = [p for p in _inspect.signature(fn).parameters.values() if p.name != "cwd"]
    required = [p.name for p in params if p.default is _inspect.Parameter.empty]
    n_min, n_max = len(required), len(params)
    if n_min <= len(args) <= n_max:
        return args, ""
    if len(args) > n_max:
        if n_max <= 1:
            return ["/".join(args)], ""  # rejoin an over-split path
        return args[: n_max - 1] + ["|".join(args[n_max - 1 :])], ""  # surplus → last param
    return None, (
        f"[ERROR] tool {name} needs {n_min} arg(s): {'|'.join(required)} "
        f"— got {len(args)}: {'|'.join(args) or '(none)'}"
    )


def dispatch(name: str, args: list[str], cwd: Path) -> tuple[bool, str]:
    """
    Called by the orchestrator when executor emits TOOL(name, arg1, arg2, ...).
    Returns (ok, output_string).
    """
    fn = TOOLS.get(name)
    if fn is None:
        return False, f"[ERROR] unknown tool: {name}. Available: {', '.join(TOOLS)}"
    norm, err = _normalize_args(fn, name, list(args))
    if norm is None:
        return False, err
    try:
        return fn(*norm, cwd)
    except TypeError as e:
        return False, f"[ERROR] tool {name} wrong args: {e}"
