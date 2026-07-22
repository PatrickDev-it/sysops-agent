"""Single owner of the success-predicate DSL: its vocabulary, its JSON schema, its
evaluation, and its rendering. Nothing else may define, parse or interpret a success
criterion.

Why this module exists — the measurement, not the intuition.

Before it, the vocabulary lived in three places that had drifted apart:
  * `supervisor.jinja` advertised twelve predicates (`not_empty`, `absent`, `tool_on_path`,
    `command_exits_ok`, `version_matches`, `service_running`, …).
  * `orchestrator._artifact_check` implemented four (`exists`, `dir_not_empty`,
    `contains_string`, `is_executable`) — of which exactly ONE, `exists`, was ever
    advertised to the model.
  * The plan schema typed `success` as a free string, so the model was free to write
    prose.

Measured over 127 real plans from the 8B planner: **0 of 19 declared criteria were
machine-checkable**. The model emitted `FileExists:python_path.txt`, `Content not empty`,
`Exit code 0` — natural-language approximations of a DSL it had never been shown. So
`_artifact_check` no-opped on every run, and invariant #9 ("a step is COMPLETE only if the
expected files exist on disk") did not hold in production. That is why 15 of 48 benchmark
tasks created an EMPTY `.txt`, verified its existence, and passed every internal check
while failing the actual objective.

The fix is structural, not exhortative. `success` items are now typed objects whose `check`
field is an enum, and every plan is decoded under a GBNF grammar compiled from this schema.
An uncheckable criterion is no longer something the model is asked not to write — it is
something the decoder cannot emit.

Two design constraints, both load-bearing:

  1. Every check is PURE: it reads the filesystem or PATH and executes nothing. A
     verification step that runs a command can have side effects, and a verifier with side
     effects cannot be trusted to report on the thing it changed. Anything requiring
     execution stays with the LLM verifier, which is explicitly fallible and is treated as
     such.
  2. `file_has_content` — not `exists` — is the default for a produced artifact. An empty
     file is not an artifact; it is a placeholder that satisfies `exists`. This single
     distinction is what invariant #9 was missing.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# Byte-order marks, longest first: UTF-32's BOM starts with UTF-16LE's, so order matters.
_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)


def read_text(path: Path) -> str:
    """Decode a text file whatever its encoding, by sniffing the BOM.

    Not a nicety. PowerShell 5.1 writes `Out-File` and `>` as UTF-16LE with a BOM, so an
    agent that reports "OS: Windows" into a file produces bytes that, read as UTF-8, look
    like `\\xff\\xfeO\\x00S\\x00`. `file_contains(os_info.txt, "OS")` then fails on a file
    that plainly contains `OS`, and the runtime declares a correct step failed.

    A BOM is a Unicode convention, not product knowledge — sniffing it is exactly the kind
    of OS-neutral reasoning this agent is supposed to do instead of special-casing a shell.
    Files without a BOM are decoded as UTF-8, replacing undecodable bytes.
    """
    raw = path.read_bytes()
    for bom, encoding in _BOMS:
        if raw.startswith(bom):
            # The BOM survives a codec-specific decode as U+FEFF; strip it, or a caller
            # asking `startswith("OS")` on a correct file gets False.
            return raw.decode(encoding, errors="replace").lstrip("﻿")
    return raw.decode("utf-8", errors="replace")


# The vocabulary. Adding a check means adding it HERE and nowhere else: the schema, the
# evaluator and the prompt text all derive from this table.
CHECKS: dict[str, str] = {
    "file_has_content": "the file exists and is not empty — use this for any artifact a step produces",
    "path_exists": "the file or directory exists (use only when emptiness is a legitimate outcome)",
    "path_absent": "the file or directory does not exist",
    "dir_not_empty": "the directory exists and contains at least one entry",
    "file_contains": "the file exists and its text contains `text`",
    "tool_on_path": "an executable named `path` is resolvable on PATH",
}

# JSON-schema fragment. Consumed by `model_router` to build the GBNF grammar, so the enum
# below is the same object the decoder is constrained by. There is no second copy.
SCHEMA: dict = {
    "type": "object",
    "properties": {
        "check": {"enum": sorted(CHECKS)},
        "path": {"type": "string"},
        "text": {"type": "string"},
    },
    "required": ["check", "path"],
}


def prompt_reference() -> str:
    """The DSL as the model should read it. Injected into every prompt from this table, so
    the vocabulary the model sees and the vocabulary the runtime evaluates cannot drift
    apart again — which is exactly how they drifted to zero overlap before."""
    lines = []
    for name, doc in sorted(CHECKS.items()):
        extra = ',"text":"<substring>"' if name == "file_contains" else ""
        lines.append(f'  {{"check":"{name}","path":"<path>"{extra}}}  — {doc}')
    return "\n".join(lines)


# Predicates that assert something about the WORKSPACE. `tool_on_path` is a CAPABILITY check:
# it says a program exists on this host, never that the work is done. The pre-execution gate
# must ignore it, or a goal whose only declared criterion is "bun is on PATH" is reported
# COMPLETE in thirteen seconds against an empty workspace. Observed exactly that, on the
# `bun_frontend` scaffold. Vacuous success, entering through a new door: not a broken evaluator
# this time, but a predicate that says nothing about the thing the goal asked for.
FILESYSTEM_CHECKS = frozenset(
    {"file_has_content", "path_exists", "path_absent", "dir_not_empty", "file_contains"}
)


def filesystem_criteria(criteria: list) -> list:
    """Only the predicates that can establish that work was actually done."""
    return [
        c for c in (criteria or []) if isinstance(c, dict) and c.get("check") in FILESYSTEM_CHECKS
    ]


def render(criteria: list) -> list[str]:
    """Human-readable form, for prompts, telemetry and the decision graph."""
    out = []
    for c in criteria or []:
        if not isinstance(c, dict):
            out.append(str(c))
            continue
        check, path, text = c.get("check", "?"), c.get("path", ""), c.get("text")
        out.append(f"{check}({path}, {text!r})" if text else f"{check}({path})")
    return out


def evaluate(criteria: list, cwd: str | Path) -> tuple[bool, str]:
    """Evaluate every predicate against the filesystem. Returns (all_passed, reason).

    An unknown check is a FAILURE, not a skip. Silently ignoring a criterion the model
    invented is precisely how invariant #9 came to be vacuous.
    """
    base = Path(cwd)
    failures: list[str] = []

    for c in criteria or []:
        if not isinstance(c, dict):
            failures.append(f"criterion is not a predicate object: {str(c)[:60]!r}")
            continue

        check = str(c.get("check", "")).strip()
        raw = str(c.get("path", "")).strip()
        if not check or not raw:
            failures.append(f"malformed predicate: {c!r}")
            continue

        if check == "tool_on_path":
            if not shutil.which(raw):
                failures.append(f"tool_on_path({raw}) — not resolvable on PATH")
            continue

        p = (base / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()

        if check == "file_has_content":
            if not p.is_file():
                failures.append(f"file_has_content({raw}) — not a file")
            elif p.stat().st_size == 0:
                failures.append(f"file_has_content({raw}) — file is empty")
        elif check == "path_exists":
            if not p.exists():
                failures.append(f"path_exists({raw}) — not found")
        elif check == "path_absent":
            if p.exists():
                failures.append(f"path_absent({raw}) — still present")
        elif check == "dir_not_empty":
            if not p.is_dir():
                failures.append(f"dir_not_empty({raw}) — not a directory")
            elif not any(p.iterdir()):
                failures.append(f"dir_not_empty({raw}) — directory is empty")
        elif check == "file_contains":
            needle = str(c.get("text") or "")
            if not p.is_file():
                failures.append(f"file_contains({raw}) — not a file")
            elif not needle:
                failures.append(f"file_contains({raw}) — no text given")
            else:
                try:
                    if needle not in read_text(p):
                        failures.append(f"file_contains({raw}) — {needle!r} not present")
                except OSError as exc:
                    failures.append(f"file_contains({raw}) — unreadable: {exc}")
        else:
            failures.append(f"unknown check {check!r} — not evaluable, treated as failed")

    return (not failures), "; ".join(failures)
