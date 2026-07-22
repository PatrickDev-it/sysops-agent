"""Environment fixtures for the certification checks.

This file used to carry eleven builders — merge-conflict repos, detached HEADs, corrupted
git indexes, a broken resolv.conf, read-only trees, a PATH stripper. Every one of them
served a certification group that reimplemented the logic it certified, and was deleted
with those groups. What remains is what the surviving checks actually construct.

A fixture nobody calls is not neutral: it reads as coverage and has to be maintained
through every refactor that touches it.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def temp_workspace() -> Generator[Path, None, None]:
    """An empty directory, removed on exit whatever the check did inside it.

    `ignore_errors=True` on teardown is deliberate: on Windows a subprocess a check
    started (py_compile, a package manager) can hold a handle for a moment after exiting,
    and a teardown that raised would mask the check's own verdict with a cleanup error.
    """
    path = Path(tempfile.mkdtemp(prefix="sist_cert_"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def current_env_info() -> dict[str, str]:
    """Host facts recorded on every CertRecord, so a failure names the machine it ran on."""
    return {
        "os": platform.system(),
        "os_version": platform.version(),
        "python": sys.version.split()[0],
        "shell": _detect_shell(),
        "arch": platform.machine(),
    }


def _detect_shell() -> str:
    if sys.platform == "win32":
        return "powershell" if os.environ.get("PSModulePath") else "cmd"
    return Path(os.environ.get("SHELL", "sh")).name
