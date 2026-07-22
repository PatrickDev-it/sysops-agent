"""Main orchestration loop.

Philosophy: reach TARGET STATE, not execute steps mechanically.
- A step is NOT complete until its success criteria all pass.
- On failure: analyse, find a different approach, retry. Never advance.
- Only the supervisor/reflection decides what to try next when stuck.
- MAX_RETRIES_PER_STEP hard-caps infinite loops on a single step.
"""

import re
import sys
import time
from pathlib import Path

# NOTE: these imports used to sit ~1000 lines below, after every module-level helper in
# this file. That works only because nothing is called at import time — a single
# module-level call, doctest or `if __name__` block above them would raise NameError on a
# name the reader can plainly see is imported. Moving them here is behaviour-preserving
# and makes the file's dependencies legible from its first screen.
from rich.console import Console
from rich.panel import Panel

from . import grounding, memory, model_router, telemetry, trace, workspace_paths
from .config import ARTIFACT_CAPTURE, EXECUTOR_AUTHORED_FIX, EXECUTOR_AUTHORS_ACTIONS
from .config import ROOT as PROJECT_ROOT
from .error_classifier import ErrorClass
from .error_classifier import classify as _classify_error
from .knowledge.ocke import OCKE
from .state import ActionResult, SystemState
from .supervisor import Supervisor
from .tools import artifact_capture, confinement, predicates, workspace_shape
from .tools.fileops import dispatch as fileops_dispatch
from .tools.observer import judge as observe_judge
from .tools.observer import observe
from .tools.session import Session, recover_sessions
from .tools.template_guard import (
    TemplateLeakDetector,
    only_creates_a_directory,
    self_truncating_redirect,
    unresolved_placeholder,
)

# TOOLS
from .tools.terminal import Terminal
from .tools.wizard_driver import is_interactive, normalize_launcher, resolve_cwd
from .verdict import RunVerdict


def _intercept_content_cmd(tool: str, cwd: Path) -> tuple[bool, str] | None:
    """
    Intercept Set-Content / Add-Content / Out-File shell commands and execute
    them natively via fileops to avoid PowerShell quoting/encoding issues.

    Returns (ok, msg) if intercepted, None if not a content-write command.
    """
    import re as _re

    from .tools.fileops import append_file, write_file

    t = tool.strip()

    # Set-Content [-Path] <path> [-Value] <value>
    m = _re.match(
        r'Set-Content\s+(?:-Path\s+)?["\']?(\S+?)["\']?\s+(?:-Value\s+)?["\'](.+)["\']?\s*$',
        t,
        _re.IGNORECASE | _re.DOTALL,
    )
    if m:
        path, content = m.group(1), m.group(2)
        content = (
            content.replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace("`n", "\n")
            .replace("`t", "\t")
        )
        return write_file(path, content, cwd)

    # Add-Content [-Path] <path> [-Value] <value>
    m = _re.match(
        r'Add-Content\s+(?:-Path\s+)?["\']?(\S+?)["\']?\s+(?:-Value\s+)?["\'](.+)["\']?\s*$',
        t,
        _re.IGNORECASE | _re.DOTALL,
    )
    if m:
        path, content = m.group(1), m.group(2)
        content = (
            content.replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace("`n", "\n")
            .replace("`t", "\t")
        )
        return append_file(path, content, cwd)

    # New-Item [-ItemType File] -Path <path> -Value "<content>"  → native write_file.
    # A multi-line -Value sent to PowerShell over the PTY breaks: the first physical line ends
    # with an unterminated string, so the file is never written (measured on node_backend: the
    # coder authored a 4-line `New-Item ... -Value "const http = ...` and server.js came out
    # "not a file"). Only when -Value is present (content) and it is NOT a Directory: a bare
    # `New-Item -ItemType File X` with no -Value is a legitimate empty-file touch, left alone.
    m = _re.match(
        r"New-Item\b(?=.*-Value)(?!.*-ItemType\s+Directory).*?"
        r'-Path\s+(?:"([^"]+)"|\'([^\']+)\'|(\S+)).*?'
        r'-Value\s+["\'](.*)["\']\s*$',
        t,
        _re.IGNORECASE | _re.DOTALL,
    )
    if m:
        path = m.group(1) or m.group(2) or m.group(3)
        content = m.group(4)
        content = (
            content.replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace("`n", "\n")
            .replace("`t", "\t")
        )
        return write_file(path, content, cwd)

    # Out-File -FilePath <path> -InputObject <content> [-Encoding ...]
    # Handles compound ';'-separated commands — each Out-File is dispatched through
    # write_file which auto-creates parent directories (unlike Out-File itself).
    if _re.search(r"\bOut-File\b", t, _re.IGNORECASE):
        parts = _re.split(r"\s*;\s*", t)
        results: list[str] = []
        all_ok = True
        for part in parts:
            part = part.strip()
            if not part:
                continue
            mo = _re.match(
                r'Out-File\s+-FilePath\s+["\']?([^\s\'"]+)["\']?\s+'
                r'-InputObject\s+["\'](.+?)["\']'
                r"(?:\s+-Encoding\s+\S+)?\s*$",
                part,
                _re.IGNORECASE | _re.DOTALL,
            )
            if mo:
                path, content = mo.group(1), mo.group(2)
                ok, msg = write_file(path, content, cwd)
                results.append(msg)
                if not ok:
                    all_ok = False
            else:
                # Part not parseable — fall through to PowerShell
                return None
        if results:
            return all_ok, "; ".join(results)

    return None


def _intercept_new_item_file(tool: str, cwd: Path) -> tuple[bool, str] | None:
    """
    Intercept 'New-Item <path> -ItemType File' commands (including compound ones)
    and route them through write_file so parent directories are created automatically
    and the operation is idempotent.

    Returns (ok, msg) if intercepted, None if not a New-Item File command.
    """
    import re as _re

    from .tools.fileops import write_file

    t = tool.strip()
    # Only intercept if ALL parts of a compound command are New-Item File ops
    # (or unrelated skippable whitespace). Mixed commands fall through to PowerShell.
    parts = [p.strip() for p in _re.split(r"\s*;\s*", t) if p.strip()]
    new_item_pat = _re.compile(
        r'^New-Item\s+["\']?([^"\';\s]+)["\']?\s+-ItemType\s+File\b',
        _re.IGNORECASE,
    )
    intercepted = []
    for part in parts:
        m = new_item_pat.match(part)
        if m:
            # PowerShell accepts comma-separated path lists: New-Item a,b -ItemType File
            for raw_path in m.group(1).split(","):
                p = raw_path.strip().strip("'\"")
                if p:
                    intercepted.append(p)
        else:
            return None  # mixed command — let PowerShell handle it

    if not intercepted:
        return None

    results = []
    all_ok = True
    for path in intercepted:
        # Don't clobber existing files that already have content.
        # New-Item is idempotent for empty files but must not destroy prior work.
        target = (cwd / path).resolve()
        if target.exists() and target.is_file() and target.stat().st_size > 0:
            msg = f"[OK] {path} already has content — skipped"
        else:
            ok, msg = write_file(path, "", cwd)
            if not ok:
                all_ok = False
        results.append(msg)
    return all_ok, "; ".join(results)


def _is_fileops(tool: str) -> bool:
    """True if the launcher is a native fileops call (write_file|path|content etc.)"""
    from .tools.fileops import TOOLS

    first = tool.split("|")[0].strip()
    return first in TOOLS


def _is_fabrication_fix(orig_tool: str, fix: str) -> bool:
    """Enforce FORBIDDEN_ALWAYS 'create_fake_output': True when `fix` hand-writes
    an artifact that a failed EXTERNAL tool (scaffolder/installer) was supposed
    to generate. Framework-neutral — keys only on fileop-vs-external origin and
    the write verb, never on tool/OS names. A fileop step recovering with another
    fileop is legitimate; a failed `npx create-next-app` "recovered" by
    write_file|package.json is fabrication that poisons every dependent step."""
    if not orig_tool or not fix:
        return False
    if _is_fileops(orig_tool):
        return False
    return bool(re.match(r"\s*(write_file|append_file)\|", fix))


def _repair_unsatisfiable_predicates(step: dict) -> list[str]:
    """A step cannot assert a predicate its own launcher makes false.

    Observed on the `react` scaffold: the launcher was `New-Item -Path .\\react -ItemType
    Directory` and the success predicate was `dir_not_empty(react)`. A directory that was just
    created is empty by definition, so the step could never pass. It retried three times, the
    initializer never ran, and the plan spent its whole budget building a folder.

    This is plan hygiene, not product knowledge: no tool is named, and the only judgement is
    arithmetic — a launcher that does nothing but create `X` cannot leave `X` non-empty. The
    predicate is downgraded to `path_exists`, which is exactly what the step does achieve, and
    the repair is reported so a planner that keeps doing this is visible in the trace.
    """
    launcher = str(step.get("launcher") or "")
    if not only_creates_a_directory(launcher):
        return []
    repaired = []
    for crit in step.get("success") or []:
        if isinstance(crit, dict) and crit.get("check") == "dir_not_empty":
            crit["check"] = "path_exists"
            repaired.append(str(crit.get("path", "")))
    if repaired:
        trace.emit(
            "plan_repair",
            rule="dir_not_empty_on_fresh_mkdir",
            paths=repaired,
            launcher=launcher[:120],
        )
    return repaired


def _artifact_check(
    tool: str, step_desc: str, cwd: str, step_success: list | None = None
) -> tuple[bool, str]:
    """Post-action artifact verification — invariant #9.

    Thin by design: the predicate vocabulary, its evaluation and its schema all live in
    `tools.predicates`, which is the same table the plan grammar is compiled from. This
    function used to own a private regex dialect that overlapped the model's advertised
    vocabulary in exactly one token (`exists`), so 0 of 19 real criteria ever matched and
    the check silently passed everything. It is now impossible for a plan to declare a
    criterion this function cannot evaluate.

    A MODIFY step that declares no predicate at all is not an error, but it IS unverifiable
    by the runtime, and we record that rather than pretend otherwise.
    """
    if not step_success:
        trace.emit(
            "unverifiable_step",
            step=str(step_desc)[:120],
            tool=str(tool)[:80],
            reason="no success predicate declared",
        )
        return True, ""
    return predicates.evaluate(step_success, cwd)


_REDIRECT_PIPE_RE = re.compile(r"\|\s*(?:Out-File|Set-Content|Tee-Object)\b", re.IGNORECASE)


def _redirect_split(command: str) -> int:
    """Index of the redirect that captures this command's stdout, or -1.

    Quote-aware: `echo "a > b"` redirects nothing. Only the LAST top-level redirect counts,
    since that is the one that writes the artifact.
    """
    quote = ""
    last = -1
    i = 0
    while i < len(command):
        ch = command[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == ">":
            # `2>`, `1>` and `*>` already name a stream; `>>` is an append of stdout.
            if i and command[i - 1] in "12*&":
                pass
            else:
                last = i
        elif ch == "|":
            m = _REDIRECT_PIPE_RE.match(command, i)
            if m:
                last = i
        i += 1
    return last


def _stderr_only_output(command: str, cwd: Path) -> str:
    """Repair a command that exited 0 and wrote its output to the WRONG stream.

    `ssh -V`, `java -version`, `gcc --version` and a long tail of others print to stderr, so
    `... > file` exits 0 and leaves the file EMPTY. Measured on T40, which fails in every
    archived run of the suite: seven commands, exit 0 every time, `ssh_client.txt` 0 bytes,
    and the coder — told the command succeeded — re-authored the same redirect.

    The runtime can settle this without asking a model: it knows the exit code, it can parse
    the redirect target, and it can stat the file. Empty target + exit 0 + a stdout-only
    redirect is not ambiguous. Returns the repaired command, or "" when the rule does not
    apply. No tool is named anywhere: the rule is about streams, not about ssh.
    """
    if not command or "2>&1" in command or re.search(r"\*>", command):
        return ""
    cut = _redirect_split(command)
    if cut < 0:
        return ""
    target = command[cut:].lstrip("|> \t")
    target = re.sub(
        r"^(?:Out-File|Set-Content|Tee-Object)\b", "", target, flags=re.IGNORECASE
    ).strip()
    target = re.sub(r"^-(?:FilePath|Path|LiteralPath)\b", "", target, flags=re.IGNORECASE).strip()
    target = target.split()[0].strip("'\"") if target.split() else ""
    if not target:
        return ""
    try:
        path = Path(target) if Path(target).is_absolute() else Path(cwd) / target
        if not (path.exists() and path.stat().st_size == 0):
            return ""
    except OSError:
        return ""
    return f"{command[:cut].rstrip()} 2>&1 {command[cut:]}"


def _split_compound_write_file(tool: str) -> list[tuple[str, str]] | None:
    """
    Split 'write_file|f1|'c1', write_file|f2|'c2'' into [(f1, c1), (f2, c2)].
    The supervisor model sometimes emits multiple file operations in one launcher,
    separated by \"', write_file|\". Returns None if not a compound write_file.
    """
    import re as _re

    if not tool.startswith("write_file|"):
        return None
    if "', write_file|" not in tool:
        return None

    raw_parts = _re.split(r"',\s*write_file\|", tool)
    results = []
    for i, part in enumerate(raw_parts):
        if i == 0:
            m = _re.match(r"write_file\|([^|]+)\|(.*)", part, _re.DOTALL)
            if not m:
                continue
            path, content = m.group(1).strip(), m.group(2)
        else:
            m = _re.match(r"([^|]+)\|(.*)", part, _re.DOTALL)
            if not m:
                continue
            path, content = m.group(1).strip(), m.group(2)

        if content.startswith("'"):
            content = content[1:]

        if i == len(raw_parts) - 1:
            # Strip trailing garbage: ', delegation=..., trailing quote, etc.
            content = _re.sub(r"'\s*,\s*\w+=.*$", "", content, flags=_re.DOTALL)
            content = content.rstrip("'")

        content = (
            content.replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace("`n", "\n")
            .replace("`t", "\t")
        )
        results.append((path, content))

    return results if results else None


def _is_mkdir_existing(tool: str, cwd: Path, workspace: Path) -> bool:
    """
    True if the command is a mkdir/New-Item Directory whose target already exists.
    Catches the common supervisor mistake of trying to create the workspace itself.
    Works for any directory, any OS — not specific to any framework.
    """
    import re as _re

    t = tool.strip()
    # Extract directory path from various mkdir forms
    patterns = [
        r"^mkdir\s+(?:-p\s+)?['\"]?(.+?)['\"]?\s*$",
        r"New-Item\s+.*-ItemType\s+Directory\s+.*-Path\s+['\"]?(.+?)['\"]?(?:\s|$)",
        r"New-Item\s+['\"]?(.+?)['\"]?\s+-ItemType\s+Directory",
    ]
    for pat in patterns:
        m = _re.search(pat, t, _re.IGNORECASE)
        if m:
            target = m.group(1).strip().strip("'\"")
            # Resolve relative to cwd
            p = Path(target) if Path(target).is_absolute() else cwd / target
            try:
                p = p.resolve()
                return p.exists() and p.is_dir()
            except Exception:
                return False
    return False


_PROSE_SIGNALS = (
    "is not recognized",
    "the term",
    "cannot find",
    "check the spelling",
    "or if a path",
    "function, script",
    "operable program",
    "not recognized as",
    "before creating",
    "the existing",
    "already exists",
)


def _backtick_is_markdown(text: str) -> bool:
    """True when a backtick reads as markdown inline code, not a PowerShell escape.

    A bare "`" used to be a prose signal, but in PowerShell the backtick is the ESCAPE
    character: `` `n `` inside a quoted string is a newline. Classifying every
    `not_a_command_or_echoes_hint` rejection in the cap_off2/cap_on2 ledgers found zero
    markdown and 16 valid PowerShell commands refused for their escapes — and a rejection
    here aborts the whole step. The shapes are separable: an escape is a backtick glued to
    one alphanumeric; a markdown span always closes with a backtick followed by a space,
    punctuation, or the end of the line.
    """
    import re as _re

    return any(not m.group(1).isalnum() for m in _re.finditer(r"`(.?)", text))


def _looks_like_command(text: str) -> bool:
    """
    Reject executor_fix output that is prose or an echoed error message.
    A valid command is a single line that starts with a path, executable,
    shell verb, or a PowerShell variable assignment — not a sentence fragment
    from an error message.
    """
    if "\n" in text:
        return False
    lower = text.lower()
    if any(sig in lower for sig in _PROSE_SIGNALS):
        return False
    if "`" in text and _backtick_is_markdown(text):
        return False
    # Must look like an invocation: starts with path chars, &, a word, or `$var =`
    import re as _re

    return bool(_re.match(r'^[a-zA-Z&.\\/"\'$]', text.strip()))


def _research_notes(sysstate, limit_chars: int = 1500) -> str:
    """Collect what prior DISCOVERY steps (web_search, probes) actually found.

    These are stored as `discovery::<objective>` facts. They are the bridge that
    lets a downstream action be authored from what was learned — the missing
    DISCOVERY→ACTION channel. Framework-neutral: just the raw findings text.
    """
    if sysstate is None:
        return ""
    notes: list[str] = []
    for key, fact in sysstate.facts.items():
        if key.startswith("discovery::") and fact.value.strip():
            notes.append(fact.value.strip())
    return "\n".join(notes)[:limit_chars]


def _resolve_discovery_refs(launcher: str, sysstate) -> str:
    """
    Substitute <PLACEHOLDER> tokens in a shell launcher with values from prior
    DISCOVERY step outputs. Invariant: when the supervisor cannot know a value
    at plan time it emits <TOKEN> — the DISCOVERY step that ran first is the
    source of truth. Any token whose name contains PATH/DISCOVERED/LOCATION/
    EXE/BIN/DIR is resolved to the path extracted from the most recent
    locate()-style output ("name -> /actual/path").
    """
    if "<" not in launcher or sysstate is None:
        return launcher
    import re as _re

    tokens = _re.findall(r"<([A-Z_][A-Z0-9_]*)>", launcher)
    if not tokens:
        return launcher
    discovery_vals = [f.value for k, f in sysstate.facts.items() if k.startswith("discovery::")]
    if not discovery_vals:
        return launcher
    result = launcher
    for token in tokens:
        if any(kw in token for kw in ("PATH", "DISCOVERED", "LOCATION", "EXE", "BIN", "DIR")):
            for val in reversed(discovery_vals):
                for line in val.splitlines():
                    if " -> " in line:
                        candidate = line.split(" -> ", 1)[1].strip()
                        if candidate:
                            result = result.replace(f"<{token}>", candidate)
                            break
                else:
                    continue
                break
    if result != launcher:
        console.print(f"  [dim]resolved placeholder(s): {launcher[:60]} → {result[:60]}[/]")
    return result


def _extract_goal_intent(goal: str) -> str:
    """
    Sanitize a goal text for supervisor.verify() calls by stripping error
    stack traces and error context. When users submit a shell error as the
    goal, the PLANNER needs the full context (to understand what failed), but
    the VERIFIER must see only the intent (what should be true after success).
    Invariant: stops at the first line that looks like an error marker.
    """
    _error_markers = (
        "error:",
        "failed to build",
        "failed building",
        "cmake error",
        "traceback ",
        "exception:",
        " errno",
        "error at ",
        "could not find",
    )
    lines = goal.strip().splitlines()
    intent_lines = []
    for line in lines:
        lc = line.strip().lower()
        if any(m in lc for m in _error_markers):
            break
        if line.strip():
            intent_lines.append(line.strip())
    result = "\n".join(intent_lines) if intent_lines else (lines[0] if lines else goal)
    # Only use the stripped version if it's meaningfully shorter
    return result if (len(result) > 10 and len(result) < len(goal) - 20) else goal


# A "run" is 3+ bare, single-word items chained by comma and/or a conjunction
# (any mixture, any language among these four — extend if needed): this is
# the language-neutral GRAMMATICAL PATTERN of an explicit enumeration ("with
# X, Y, Z" / "con X, Y e Z" / "X, Y, and Z"), not a technology catalog. Used
# to deterministically verify plan coverage of everything the user actually
# named — a small model can silently drop one item from a long list.
_REQ_ITEM = r"[a-zA-Z][\w\-]{1,29}"
_REQ_SEP = r"(?:\s*,\s*(?:(?:e|and|o|or)\s+)?|\s+(?:e|and|o|or)\s+)"
_REQ_RUN_RE = re.compile(rf"{_REQ_ITEM}(?:{_REQ_SEP}{_REQ_ITEM}){{2,}}")
_REQ_STOPWORDS = frozenset({"e", "and", "o", "or", "con", "with"})


def _extract_named_requirements(goal: str) -> list[str]:
    """Extract items the user explicitly enumerated in the goal (>=3-item
    comma/conjunction list). Purely structural — no knowledge of what any
    item IS, just that it was named as part of an explicit list.
    """
    items: list[str] = []
    for run in _REQ_RUN_RE.finditer(goal):
        items.extend(p.strip(". ") for p in re.split(_REQ_SEP, run.group(0)) if p.strip())
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        low = it.lower()
        if low in _REQ_STOPWORDS or low in seen:
            continue
        seen.add(low)
        out.append(it)
    return out


def _uncovered_requirements(
    goal: str,
    plan: list,
    constraints: list[str],
    success: list[str],
) -> list[str]:
    """Which explicitly-named goal items does the CURRENT plan never mention?

    Case-insensitive substring match against every piece of planner-authored
    text (constraints, plan-level success, each step's objective/launcher/
    success) — pure text coverage, no technology knowledge. Catches the
    observed failure mode: a goal names 5 things, the plan only covers 4.
    """
    reqs = _extract_named_requirements(goal)
    if not reqs or not plan:
        return []
    # Plan-level `success` is a list of predicate objects, like every step's.
    parts = list(constraints) + predicates.render(success)
    for item in plan:
        if isinstance(item, dict):
            parts.append(str(item.get("objective", "")))
            parts.append(str(item.get("launcher", "")))
            # `success` items are predicate objects; render them through their owner.
            parts.extend(predicates.render(item.get("success") or []))
        else:
            parts.append(str(item))
    blob = " ".join(parts).lower()
    return [r for r in reqs if r.lower() not in blob]


def _fix_powershell_relative_path(command: str) -> str:
    r"""
    On Windows PowerShell, a command whose first token starts with .LETTER
    (e.g. '.venv\Scripts\python.exe') is parsed as dot-sourcing, not a path.
    Prepend '.\ ' to produce the explicit relative-path form '.\.venv\...'.
    Invariant: applies to any .name\ prefix, not venv-specific.
    Does NOT trigger for '.\' (already has explicit .\ prefix) or '$env:...' prefixes.
    """
    if sys.platform != "win32":
        return command
    import re as _re

    # Match .LETTER at start (dot + alphabetical) but NOT .\ (already explicit rel path)
    if _re.match(r"^\.[a-zA-Z]", command):
        return ".\\" + command
    return command


def _quote_ps_literal_args(command: str) -> str:
    r"""Make argument literals safe for the PowerShell parser.

    Category (not a single case): a bare, unquoted argument token that begins
    with a character PowerShell treats as an operator is misparsed as syntax.
    The clearest always-literal member is '@' (splat/array): `--import-alias @/*`
    dies with a parse error, yet the command is semantically perfect. The model
    should not need to be a PowerShell-quoting expert — the runtime quotes it.

    Rules (conservative, zero-regression):
      - only a token preceded by start-or-whitespace (real arg position) and NOT
        already quoted (the `"@/*"` the model sometimes emits is left untouched);
      - '@' followed by '(' '{' '"' ''' '$' is a real PS construct
        (array/hashtable/here-string/var-splat) — left untouched;
      - otherwise single-quote the whole token.
    Extensible: add other always-literal operator prefixes here if observed.
    """
    if sys.platform != "win32":
        return command
    import re as _re

    # (^|\s) real-arg boundary; @ then ≥1 char none of which starts a PS construct.
    return _re.sub(r'(^|\s)(@[^\s\'"()${}]+)', r"\1'\2'", command)


def _translate_bash_env_prefix(cmd: str, shell: str) -> str:
    """
    Translate bash 'VAR=value cmd' inline env var syntax to shell-native form.

    On PowerShell: VAR=value cmd  →  $env:VAR="value"; cmd
    On bash/sh: no change needed — syntax is already valid.

    Invariant: works for any number of VAR=value prefixes, any variable name.
    This is a structural transformation, not a PowerShell-specific hack:
    the pattern 'KEY=VALUE rest' is an ambiguous shell construct that must
    be resolved to the target shell's native env-var assignment form.
    """
    if shell not in ("powershell", "pwsh"):
        return cmd
    import re as _re

    # Match one or more VAR=value pairs at the start, optionally quoted
    env_prefix_pat = _re.compile(
        r'^((?:[A-Z_][A-Z0-9_]*=(?:"[^"]*"|\'[^\']*\'|[^\s;]+)\s+)+)(.*)',
        _re.DOTALL | _re.IGNORECASE,
    )
    m = env_prefix_pat.match(cmd.strip())
    if not m:
        return cmd
    env_part, rest = m.group(1).strip(), m.group(2).strip()
    if not rest:
        return cmd  # bare VAR=value with no command after — not a bash prefix
    pair_pat = _re.compile(
        r'([A-Z_][A-Z0-9_]*)=("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|[^\s]+)', _re.IGNORECASE
    )
    assignments = []
    for var, val in pair_pat.findall(env_part):
        # Strip outer quotes, then re-wrap in double-quotes for PowerShell
        if len(val) >= 2 and val[0] in ('"', "'") and val[-1] == val[0]:
            inner = val[1:-1]
        else:
            inner = val
        assignments.append(f'$env:{var}="{inner}"')
    if not assignments:
        return cmd
    return "; ".join(assignments) + "; " + rest


def _fix_dotless_venv_path(command: str, cwd: Path) -> str:
    r"""
    Correct .\venv\ → .\.venv\ when the directory is named .venv (with dot).
    The supervisor sometimes emits the venv path without the leading dot.
    Filesystem-authoritative: only applies when .venv exists and venv does not.
    """
    if ".venv" in command:
        return command  # already references .venv correctly
    if "venv" not in command.lower():
        return command
    if (cwd / ".venv").exists() and not (cwd / "venv").exists():
        command = command.replace(".\\venv\\", ".\\.venv\\")
        command = command.replace("./venv/", "./.venv/")
        # Also handle bare venv\ without .\ prefix — use lambda to avoid
        # regex replacement string escape issues.
        import re as _re

        command = _re.sub(
            r"(?<![./\\])venv([/\\])",
            lambda m: ".venv" + m.group(1),
            command,
        )
    return command


def _flatten_strings(items: list) -> list[str]:
    """
    Normalize a list that may contain strings or dicts (model schema drift).
    Extracts the most useful string from whatever the model produced.
    """
    result = []
    for item in items:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            # {type: ..., check: ...} or {constraint: ...} or any dict — take first value
            for key in ("check", "constraint", "description", "value"):
                if key in item:
                    result.append(str(item[key]))
                    break
            else:
                result.append(str(next(iter(item.values()), item)))
    return result


def _classify_job_command(tool: str) -> str:
    """
    Classify a PowerShell background-job command structurally.
    Returns "launch" (Start-Job ...), "stop" (Stop-Job/Remove-Job), or "".

    Invariant: detects the job-control grammar, not any specific dev server or
    framework. The point is that job handle variables ($job) cannot survive the
    fresh-shell-per-step model, so launches must be made self-terminating and
    stops must be neutralised.
    """
    import re as _re

    t = tool.strip()
    # stop: command is (mostly) Stop-Job / Remove-Job, with no Start-Job present
    if _re.search(r"\b(Stop-Job|Remove-Job)\b", t, _re.IGNORECASE) and not _re.search(
        r"\bStart-Job\b", t, _re.IGNORECASE
    ):
        return "stop"
    # launch: Start-Job with an inner script block
    if _re.search(r"\bStart-Job\b", t, _re.IGNORECASE):
        return "launch"
    return ""


def _extract_startjob_inner(tool: str) -> str:
    r"""
    Extract the inner command from "$j = Start-Job { <inner> }; ...".
    Strips any leading Set-Location/cd inside the block (the session already
    runs in the correct cwd). Returns "" if no script block is found.
    """
    import re as _re

    m = _re.search(r"Start-Job\s*(?:-ScriptBlock\s*)?\{(.+?)\}", tool, _re.DOTALL | _re.IGNORECASE)
    if not m:
        return ""
    inner = m.group(1).strip()
    # Drop a leading cd / Set-Location segment — session.run runs in the right cwd
    inner = _re.sub(r"^\s*(?:Set-Location|cd)\s+[^;]+;\s*", "", inner, flags=_re.IGNORECASE)
    return inner.strip()


def _is_scaffold_init(tool: str) -> bool:
    """
    True if the launcher is a project scaffolding/init command.
    Invariant: detects the structural pattern (create/init/new/scaffold + a path
    argument) — never checks for specific framework names.
    """
    import re as _re

    _SCAFFOLD_RE = _re.compile(r"\b(create|init|new|scaffold|generate|setup)\b", _re.IGNORECASE)
    # Must match the structural verb AND look like an invocation, not a shell comment
    return bool(_SCAFFOLD_RE.search(tool)) and not tool.strip().startswith("#")


# Package-runner prefixes: mechanisms for invoking a package's binary without
# installing it globally. Category-level (how packages are RUN), not a
# technology catalog — same status as _SHELL_BUILTINS elsewhere in this file.
_PACKAGE_RUNNERS = frozenset({"npx", "npm", "pnpm", "bunx", "uvx", "pipx", "yarn", "dlx"})


def _content_write_target(step_success: list, tool: str) -> str | None:
    """The single file a step must FILL WITH CONTENT, when the step is a plain file write
    rather than a scaffolder/package-runner that produces the file via tooling.

    Control experiment (seed 42): asked for "one shell command" the coder emits an empty
    `New-Item -ItemType File server.js`; asked for the file CONTENT it emits a correct server.
    So for a `file_has_content(X)` step whose launcher is a bare create/replace file write, the
    runtime authors X's content (executor_content.jinja) and writes it natively — instead of
    forcing a whole file body through one shell command. Returns X, else None.
    """
    import re as _re

    targets = [
        c.get("path")
        for c in (step_success or [])
        if isinstance(c, dict) and c.get("check") == "file_has_content" and c.get("path")
    ]
    if len(targets) != 1:
        return None  # zero or many targets → not a single-file write
    t = (tool or "").strip()
    _low = t.lower()
    if not t or "-itemtype directory" in _low:
        return None  # a directory, not a file body
    if ">>" in t or "add-content" in _low or "-append" in _low:
        return None  # an APPEND — never rewrite the whole file
    # WHITELIST the bare create/replace file writes. A real scaffolder (`npm create`, `ng
    # new`, `npm init`, `django-admin`) does NOT match and produces the file via its own
    # tooling — safer than blacklisting scaffolders (`_is_scaffold_init` false-matches the
    # "new" in "New-Item"). `New-Item -ItemType File`, Set-Content, Out-File, touch, echo>,
    # and native write_file are the writes a coder answers with an empty file today.
    is_write = (
        _is_fileops(t)
        or bool(_re.search(r"\b(New-Item|Set-Content|Out-File|touch|printf)\b", t, _re.I))
        or bool(_re.search(r"(^|\s)echo\b.*>", t))
    )
    return targets[0] if is_write else None


def _discovery_query_from_interactive(tool: str) -> str:
    """Turn an interactive/scaffold launcher into a web_search query about its
    current non-interactive invocation.

    Generic: strips flags, a leading package-runner prefix, and any @version
    pin from the remaining tool name — no framework/tool catalog. Returns ""
    if nothing nameable remains.
    """
    words = [w for w in tool.split() if not w.startswith("-")]
    while words and words[0].lower() in _PACKAGE_RUNNERS:
        words = words[1:]
    if not words:
        return ""
    words[0] = re.sub(r"@[\w.\-]+$", "", words[0])
    return " ".join(words + ["latest", "non-interactive", "flags"])


_PATH_BOUNDARIES = frozenset(" \t\r\n\"';|&<>")


def _is_within(path: str, root: str) -> bool:
    """True if `path` names `root` or something under it, compared component-wise.

    Separator- and case-insensitive: a model handed `C:\\a\\b` frequently echoes it
    back as `C:/a/b`. Comparing on component boundaries (rather than raw string
    prefixes) is what keeps `.../ws_old` from counting as inside `.../ws`.
    """

    def norm(p: str) -> str:
        return p.replace("\\", "/").rstrip("/").casefold()

    p, r = norm(path), norm(root)
    return p == r or p.startswith(r + "/")


def _normalise_path_text(path: str | Path) -> str:
    return str(path).replace("\\", "/").rstrip("/").casefold()


def _starts_path_reference(text: str, path: str, *, descendants: bool) -> bool:
    """Whether text starts with a component-bounded reference to path.

    Shell tokenisation cannot answer this safely: an unquoted absolute path may contain
    spaces and parentheses, which is precisely the malformed model output this guard must
    reject before execution. Compare the known project/workspace paths directly instead.
    """
    if not text.startswith(path):
        return False
    if len(text) == len(path):
        return True
    following = text[len(path)]
    return (descendants and following == "/") or following in _PATH_BOUNDARIES


def _has_fabricated_workspace_path(command: str, real_workspace: Path) -> bool:
    """True if `command` hardcodes an absolute path into this project's own tree that
    does NOT match the real workspace — i.e. the model invented a plausible-but-wrong
    sibling path instead of using the exact one already given to it in context
    (observed: an authored Remove-Item targeted '...\\_try\\src' while the real
    workspace was '...\\_sandbox\\_try').

    Suspicion is anchored to `PROJECT_ROOT`, not to a directory *name*. The previous
    version matched a literal `.workspace` path segment, which made the guard a hostage
    to what this checkout happens to be called: rename the directory and the regex stops
    matching, silently disabling the check. Paths outside our own tree are none of this
    guard's business — the model may legitimately name any path on the machine.
    """
    real_path = Path(real_workspace).resolve()
    real = _normalise_path_text(real_path)
    project = _normalise_path_text(PROJECT_ROOT)
    command_text = _normalise_path_text(command)

    # Exact ancestors are legitimate observations (for example ls PROJECT_ROOT), but
    # descendants of those ancestors are legitimate only when they remain under the real
    # workspace. This preserves component boundaries: workspace_old is not workspace.
    exact_ancestors = {project}
    for parent in real_path.parents:
        parent_text = _normalise_path_text(parent)
        if _is_within(parent_text, project):
            exact_ancestors.add(parent_text)

    start = 0
    while (found := command_text.find(project, start)) >= 0:
        tail = command_text[found:]
        start = found + len(project)
        if not _starts_path_reference(tail, project, descendants=True):
            continue  # merely a string prefix of another checkout name
        if _starts_path_reference(tail, real, descendants=True):
            continue
        if any(
            _starts_path_reference(tail, ancestor, descendants=False)
            for ancestor in exact_ancestors
        ):
            continue
        return True
    return False


class _WorkspaceStash:
    """
    Move non-project files out of the workspace before a scaffold command runs,
    then restore them afterward.  This solves the universal problem where scaffold
    tools (npm create, cargo init, go mod init, …) refuse to write into a
    non-empty directory.

    Invariant: only stashes files whose names do NOT look like project roots
    (.git is never stashed). Node/package project roots are detected generically
    by the presence of any recognised manifest.
    """

    _MANIFEST_NAMES = {
        "package.json",
        "cargo.toml",
        "pyproject.toml",
        "setup.py",
        "go.mod",
        "composer.json",
        "gemfile",
        "build.gradle",
    }
    _NEVER_STASH = {".git", ".gitignore", "node_modules"}

    def __init__(self, workspace: Path) -> None:
        self._ws = workspace
        self._stash = workspace / ".sistemista_stash"
        self._stashed: list[str] = []

    def _has_project(self) -> bool:
        for e in self._ws.iterdir():
            if e.name.lower() in self._MANIFEST_NAMES:
                return True
        return False

    def stash(self) -> tuple[bool, str]:
        """Move loose files/dirs into stash. Returns (did_stash, reason)."""
        if self._has_project():
            return False, "workspace already has a project manifest — no stash needed"
        victims = [
            e
            for e in self._ws.iterdir()
            if e.name not in self._NEVER_STASH and e.name != self._stash.name
        ]
        if not victims:
            return False, "workspace is already clean"
        self._stash.mkdir(exist_ok=True)
        moved = []
        for item in victims:
            dest = self._stash / item.name
            try:
                item.rename(dest)
                moved.append(item.name)
            except Exception:
                pass
        self._stashed = moved
        return bool(moved), f"stashed {len(moved)} item(s): {', '.join(moved)}"

    def restore(self) -> tuple[bool, str]:
        """Move stashed items back, merge if destination already exists."""
        import shutil

        if not self._stash.exists():
            return True, "nothing to restore"
        restored = []
        for item in list(self._stash.iterdir()):
            dest = self._ws / item.name
            try:
                if dest.exists():
                    if dest.is_dir() and item.is_dir():
                        shutil.copytree(str(item), str(dest), dirs_exist_ok=True)
                        shutil.rmtree(str(item))
                    # file collision: keep the new scaffold file, drop stash
                    else:
                        item.unlink(missing_ok=True)
                else:
                    item.rename(dest)
                restored.append(item.name)
            except Exception:
                pass
        try:
            self._stash.rmdir()
        except Exception:
            pass
        return True, f"restored {len(restored)} item(s)"


def _shallow_fingerprint(root: Path) -> frozenset[str]:
    """Bounded, one-level workspace snapshot: name + kind + size/child-count.

    No recursion (skips node_modules/.git — dependency caches and VCS internals
    are never the artifact a scaffold command is judged on). Comparing this
    before/after a scaffold command is a cheap, deterministic way to tell
    whether it actually created anything — used when the plan declared no
    explicit success predicate to check the step against (invariant #9 still
    applies even when the planner forgot to name a predicate).
    """
    try:
        entries = []
        for e in root.iterdir():
            if e.name in ("node_modules", ".git"):
                continue
            if e.is_dir():
                try:
                    n = sum(1 for _ in e.iterdir())
                except OSError:
                    n = -1
                entries.append(f"d:{e.name}:{n}")
            else:
                try:
                    sz = e.stat().st_size
                except OSError:
                    sz = -1
                entries.append(f"f:{e.name}:{sz}")
        return frozenset(entries)
    except OSError:
        return frozenset()


def _move_subdir_to_root(workspace: Path) -> tuple[bool, str]:
    """
    When a scaffold tool creates a single child directory instead of populating
    the workspace root directly, move all its contents up one level.

    This is an invariant operation — it applies to any tool on any OS that
    ignores the cwd and creates a named subdirectory.
    """
    import shutil

    try:
        real = [
            e
            for e in workspace.iterdir()
            if not e.name.startswith(".") and e.name != "node_modules"
        ]
        if len(real) != 1 or not real[0].is_dir():
            return False, f"expected exactly one subdir, found: {[e.name for e in real]}"
        subdir = real[0]
        moved = []
        for item in subdir.iterdir():
            dest = workspace / item.name
            if dest.exists():
                if dest.is_dir():
                    shutil.copytree(str(item), str(dest), dirs_exist_ok=True)
                    shutil.rmtree(str(item))
                else:
                    item.replace(dest)
            else:
                item.rename(dest)
            moved.append(item.name)
        subdir.rmdir()
        return True, f"moved {len(moved)} items from {subdir.name}/ to root"
    except Exception as exc:
        return False, str(exc)


_UNRESOLVED_ANGLE_RE = re.compile(r"<[A-Za-z][A-Za-z0-9_]*>")
# A $VAR the runtime does NOT substitute. $WORKSPACE_PATH is substituted in
# _run_batch; anything else uppercase-ish reaching the shell is an unresolved leak.
_UNRESOLVED_VAR_RE = re.compile(r"\$(?!WORKSPACE_PATH\b)[A-Z][A-Z0-9_]{2,}\b")


def _has_unresolved_placeholder(command: str) -> bool:
    """True if the command still carries an <ANGLE_TOKEN> or a non-substituted $UPPER_VAR.

    Delegates to , the single owner.  enforces the same
    predicate at the point of execution, so this early rejection is an optimisation (keep
    the planner hint instead of authoring a doomed command), not the guarantee."""
    return bool(unresolved_placeholder(command))


def _is_shell_balanced(command: str) -> bool:
    """Deterministic balance check for quotes, braces, brackets, parens — catches
    the authored fragments that produce 'Missing closing }' parse errors. Quote-
    aware: brackets inside a quoted string are ignored."""
    stack: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    opens = set(pairs.values())
    quote = ""
    escape = False
    dq = command.count('"')
    sq = command.count("'")
    if dq % 2 or sq % 2:
        return False
    for ch in command:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if quote:
            if ch == quote:
                quote = ""
            continue
        if ch in ('"', "'"):
            quote = ch
            continue
        if ch in opens:
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack[-1] != pairs[ch]:
                return False
            stack.pop()
    return not stack


def _delatest_scaffold_pins(command: str) -> str:
    """B1: in a scaffold/create command, replace a hard-pinned package version
    (`pkg@1.2.3`) with `@latest`. These tasks want the current version, and a
    small model routinely hallucinates a non-existent pin (`@angular/cli@18.22.3`
    → ERR_PNPM_NO_MATCHING_VERSION). Generic: only full X.Y.Z semver pins in a
    scaffold context; install commands (which may legitimately pin) are untouched."""
    if not _is_scaffold_init(command):
        return command
    return re.sub(r"@\d+\.\d+\.\d+(?:[-.][\w.]+)?", "@latest", command)


def _cleanup_flag_named_artifacts(workspace: Path) -> list[str]:
    """Remove or flatten any top-level entry whose name starts with '-'.

    A name starting with '-' is never a legitimate project/directory name in
    ANY ecosystem — it is the deterministic signature of a CLI scaffold tool
    swallowing an unrecognized flag as its positional project-name argument
    (observed twice: a malformed --src flag produced a '--src' directory
    holding the whole project; a malformed --tailwindcss-version flag
    produced an empty '--tailwindcss-version' directory). Generic filesystem-
    naming invariant, no tool/framework knowledge. Empty entries are removed;
    non-empty ones are flattened into the workspace root (merging on
    collision) before removal, so no generated content is lost.

    Returns the list of cleaned-up names, for logging. Never raises.
    """
    import shutil

    cleaned: list[str] = []
    try:
        entries = list(workspace.iterdir())
    except OSError:
        return cleaned
    for e in entries:
        if not e.name.startswith("-"):
            continue
        try:
            if e.is_dir():
                children = list(e.iterdir())
                for child in children:
                    dest = workspace / child.name
                    if dest.exists():
                        if dest.is_dir() and child.is_dir():
                            shutil.copytree(str(child), str(dest), dirs_exist_ok=True)
                            shutil.rmtree(str(child))
                        else:
                            child.unlink(missing_ok=True)
                    else:
                        child.rename(dest)
                e.rmdir()
            else:
                e.unlink()
            cleaned.append(e.name)
        except OSError:
            continue
    return cleaned


def _is_name_invalid_error(output: str) -> bool:
    """True when a scaffolder rejected the project name it derived from the
    target directory (ecosystem naming rules, e.g. npm: name cannot start with
    '_'). Error-driven and framework-neutral — keys on the observed message,
    never on a tool/OS catalogue (invariant: recovery derives from the error)."""
    return bool(
        re.search(
            r"name cannot|naming restriction|can only contain|name must"
            r"|invalid project name|not a valid name|name can only",
            output or "",
            re.IGNORECASE,
        )
    )


def _sanitize_project_name(dirname: str) -> str:
    """Deterministic valid project name from a directory name: drop leading
    '._-', lowercase, map non-alnum to '-'. Empty result → 'app'."""
    s = re.sub(r"[^a-z0-9-]", "-", re.sub(r"^[._-]+", "", (dirname or "").lower()))
    return s.strip("-") or "app"


def _rewrite_scaffold_target(tool: str, safe: str) -> str:
    """Replace the lone '.' target (scaffold in current dir) with a valid subdir
    name, so the scaffolder writes into ./<safe>/ (flattened to root afterwards)."""
    return re.sub(r"(^|\s)\.(\s|$)", rf"\g<1>{safe}\g<2>", tool, count=1)


def _extract_tool_suggestion(output: str) -> str:
    """
    When a CLI tool deprecates itself it often prints its replacement command.
    Read the output and extract the first npx/npm/cargo/pip/etc. command it suggests.

    This is the most reliable signal available — the tool is a live source of truth,
    not training data.

    Examples caught:
      "To create a new React Router project, run:\n  npx create-react-router@latest"
      "Please use: npx create-react-router@latest"
      "Run `npx create-vue@latest` instead"
    """
    if not output:
        return ""
    # Look for explicit "run:" / "use:" / "try:" followed by a command on the next line or same line
    patterns = [
        r"(?:run|use|try|instead(?:\s+use)?|please\s+use|switch\s+to)[:\s]+[`'\"]?(npx\s+\S+|npm\s+(?:create|init)\s+\S+|cargo\s+\S+|pip\s+\S+|uv\s+\S+)",
        r"[`'\"]?(npx\s+create-[\w@/.-]+)[`'\"]",  # any npx create-* mentioned
    ]
    for pat in patterns:
        m = re.search(pat, output, re.IGNORECASE)
        if m:
            cmd = m.group(1).strip().strip("`'\"")
            # Sanity: must look like a real command
            if len(cmd) > 4 and " " in cmd:
                return cmd
    return ""


console = Console()

_RING = 4096
MAX_RETRIES_PER_STEP = 5  # how many times we re-attempt a failed step before asking reflection


def _resolve_step_vars(command: str, vars_dict: dict, sysstate=None) -> tuple[str, list[str]]:
    """
    Resolve $VAR tokens in a command using the step's `vars` dict.
    Falls back to sysstate.facts for vars that are empty in the dict.

    Invariant: executor NEVER sees unresolved $VAR tokens.
    Returns (resolved_command, list_of_still_unresolved_var_names).
    """
    import re as _re

    if not vars_dict and "$" not in command:
        return command, []

    # Normalize \$VAR → $VAR: some models escape dollar signs with backslash
    # inside double-quoted strings. In PowerShell (and as var tokens) the
    # backslash is wrong — strip it so resolution works correctly.
    command = _re.sub(r"\\(\$[A-Z][A-Z0-9_]*)", r"\1", command)

    resolved = command
    unresolved: list[str] = []

    # Collect all $VAR references in the command
    tokens = _re.findall(r"\$([A-Z_][A-Z0-9_]*)", resolved)
    for var in tokens:
        value = vars_dict.get(var, "")
        if not value and sysstate is not None:
            # Fallback 1: exact fact-key match (deterministic, no fuzziness).
            for key, fact in sysstate.facts.items():
                if key.lower().replace("::", "_") == var.lower():
                    value = fact.value.splitlines()[0].strip()
                    break
            # Fallback 2: path-type vars ($DISCOVERED_PATH, $EXE_PATH, …) resolve
            # from the world graph — the most recently observed node with a real
            # filesystem path. Replaces the old blind grep of discovery facts
            # for "name -> path" arrows (raw-text re-parsing at decision time).
            if not value:
                _path_kw = ("PATH", "DISCOVERED", "LOCATION", "EXE", "BIN", "DIR")
                if any(kw in var.upper() for kw in _path_kw):
                    value = sysstate.world.latest_path()
        if value:
            resolved = resolved.replace(f"${var}", value)
        else:
            unresolved.append(var)

    return resolved, unresolved


class Orchestrator:
    def __init__(self, workspace: str | None = None):
        if not workspace:
            # This used to default to Path.home(), and the pre-flight block below it ran
            # `session.clear_workspace()` — iterdir() plus a forced recursive remove of every
            # entry — whenever the goal contained one of delete/clean/empty/remove/wipe/clear
            # and the directory did not look like a project. So `sistemista "clean up my PATH"`
            # with no --workspace enumerated the user's home directory and deleted it, before
            # the first model call and before the safety gate, with no confirmation and no
            # dry-run. A destructive default is not a default.
            raise ValueError(
                "--workspace is required. Refusing to operate on the home directory: "
                "an implicit workspace makes the blast radius of a wrong plan unbounded."
            )
        self._workspace = Path(workspace).resolve()
        if not self._workspace.is_dir():
            raise ValueError(f"--workspace is not a directory: {self._workspace}")
        # The confinement filter, the cwd guard and `_has_fabricated_workspace_path` all
        # compare against this path. A quote or a shell metacharacter in it would break the
        # comparison and, worse, survive into a command string.
        if any(ch in str(self._workspace) for ch in "'\"`$"):
            raise ValueError(f"workspace path contains a shell metacharacter: {self._workspace}")

        # The workspace root is never shown to a model: it is the source of the JSON escape
        # sequences that made the 0.6B planner loop on backslashes. See workspace_paths.
        workspace_paths.set_root(self._workspace)
        # The same path, for a different owner: writes are scoped to it. Set once per run, so
        # that `fileops` — which only ever receives a cwd — resolves against the workspace
        # rather than against whatever directory the current step happens to run in.
        confinement.set_root(self._workspace)

    def run(self, goal: str) -> RunVerdict:
        memory.init_db()
        memory.prune_old_events()
        # `clear_session_events()` used to run here. It executes `DELETE FROM events`, and that
        # table is the ONLY per-command record of what the agent did to the host — cwd, command,
        # stdout, exit code. Every run therefore destroyed its predecessor's, and combined with
        # a trace that was inert outside the benchmark harness (see trace.py) the result was an
        # agent that executed shell commands on a live machine and kept no record of any of it.
        # Scoping reads to the current run is a query concern, not a reason to delete history.
        memory.set_objective(goal)

        console.print(Panel(f"[bold cyan]GOAL[/] {goal}", title="Sistemista"))

        recover_sessions()

        session = Session(workspace=self._workspace)
        terminal = Terminal(
            shell="powershell" if sys.platform == "win32" else "bash",
            cwd=str(self._workspace),
        )
        supervisor = Supervisor()
        sysstate = SystemState(session.workspace)

        # The audit trail starts before the first action and ends after the last, including the
        # ones that raise. It defaults to var/trace/ now; it used to disable itself unless an
        # environment variable set only by the benchmark harness was present.
        trace.begin(sysstate.run_id)
        trace.emit("run_start", goal=goal, workspace=str(self._workspace))

        verdict, note = RunVerdict.ERROR, ""
        try:
            verdict, note = self._run_loop(goal, session, terminal, supervisor, sysstate)
        except KeyboardInterrupt:
            verdict, note = RunVerdict.ABORTED, "operator interrupt"
            console.print("\n[yellow]Aborted by operator.[/]")
        except Exception as exc:
            # There was no `except` here at all. An unreachable llama-server, an oracle timeout
            # or a sqlite error from any of the unguarded save_event calls propagated as a
            # traceback: telemetry never ran, so the run left no record whatsoever — precisely
            # the runs whose record matters most.
            verdict, note = RunVerdict.ERROR, f"{type(exc).__name__}: {exc}"
            trace.emit("run_error", error=type(exc).__name__, message=str(exc)[:500])
            console.print(f"[bold red]RUN FAILED:[/] {note}")
            raise
        finally:
            # One owner for the run record. Each terminal path used to write its own, which is
            # why the non-terminal paths wrote none.
            trace.emit("run_end", verdict=verdict.value, note=note[:500])
            telemetry.record_run(sysstate, goal, verdict=verdict.value, note=note)
            trace.end()
            session.shutdown()
            terminal.close()

        return verdict

    # ── Main loop ────────────────────────────────────────────────────────────

    def _run_loop(self, goal, session, terminal, supervisor, sysstate) -> tuple[RunVerdict, str]:
        console.print(f"[dim]env:[/] {sysstate.environment.os_name} / {sysstate.environment.shell}")

        # OCKE: build the OS knowledge engine from the already-probed environment.
        # Detects platform, loads ONLY the matching knowledge slice, builds the
        # command registry, and readies the validator for plan filtering.
        ocke = OCKE.from_state(sysstate)
        console.print(
            f"[dim]ocke:[/] {len(ocke._registry.all_entries())} entries loaded for {ocke.profile.os_name}/{ocke.profile.shell}"
        )
        # Seed facts with the environment we already probed deterministically.
        # The agent should not shell out to re-discover what the runtime knows.
        _env = sysstate.environment
        sysstate.add_fact("os_name", _env.os_name, source="environment")
        sysstate.add_fact("os_version", _env.os_version, source="environment")
        sysstate.add_fact("shell", _env.shell, source="environment")
        sysstate.add_fact("home_directory", _env.home, source="environment")
        sysstate.add_fact("user", _env.user, source="environment")
        # Reasoning context — all in-RAM reasoning layers for this run
        sysstate.init_reasoning(goal)

        # A pre-flight `session.clear_workspace()` used to run here, gated on a substring
        # search of the goal for delete/clean/empty/remove/wipe/clear and on the workspace not
        # looking like a project. It executed BEFORE the safety gate (which classifies
        # destructive goals ~20 lines below) and before any model call, so a goal like
        # "clean up my PATH" or "remove the broken pip package" force-deleted every entry of
        # the workspace with no confirmation, no dry-run and no record.
        #
        # Deleting the user's files is an ACTION. Actions belong in the plan, where the safety
        # gate classifies them, the confinement filter scopes them and the trace records them.
        # A keyword reflex that runs ahead of all three is not a shortcut, it is a bypass.

        # Pre-flight: deterministic empty check only.
        # We do NOT call supervisor.verify() here — we have no success criteria yet
        # (those come from planning). A partial workspace (e.g. app/ without package.json)
        # must NOT short-circuit — it gets planned against and verified with real criteria.
        obs = observe(goal, session)
        det_ok, det_reason = observe_judge(goal, obs, session)

        # FASE 7: GoalRiskClassifier — DESTRUCTIVE goals never reach the planner.
        from .tools.safety_gate import DESTRUCTIVE, RECOVERABLE
        from .tools.safety_gate import classify as _classify_risk

        _risk, _risk_reason = _classify_risk(goal)
        sysstate.add_fact("goal_risk", f"{_risk}: {_risk_reason}", source="safety_gate")
        if _risk == DESTRUCTIVE:
            console.print(f"[bold red]REFUSED (DESTRUCTIVE):[/] {_risk_reason}")
            console.print(
                "[dim]Irreversible system-level scope. Propose a bounded diagnostic instead.[/]"
            )
            return RunVerdict.REFUSED, _risk_reason
        if _risk == RECOVERABLE:
            console.print(f"[bold red]REFUSED (REVIEW REQUIRED):[/] {_risk_reason}")
            console.print(
                "[dim]Only goals classified SAFE may reach the planner in this release.[/]"
            )
            return RunVerdict.REFUSED, _risk_reason

        # Inject OCKE platform context into the supervisor's environment snapshot.
        # This tells the LLM what package managers exist, what is forbidden, and
        # which knowledge entries have already been proven or failed on this OS.
        _ocke_block = ocke.prompt_block()
        sysstate.add_fact("ocke_context", _ocke_block, source="ocke")

        # SYSTEM_SPEC: deterministic live-host facts (TODAY's date + real installed
        # tool versions) injected mechanically into every model prompt. Overcomes
        # the model's frozen-era / version-blind priors — it plans for THIS machine
        # today, not its training era. Single owner: knowledge.system_spec.
        from .knowledge.system_spec import build as _build_spec

        _spec_block = _build_spec(sysstate.environment)
        sysstate.add_fact("system_spec", _spec_block, source="system_spec")
        console.print(
            f"[dim]spec:[/] {' | '.join(line.strip() for line in _spec_block.splitlines()[1:4])}"
        )

        # PROMPT ENHANCER: single call, same model as the supervisor (no second
        # GGUF loaded), run ONCE for this objective before any planning. Neither
        # the supervisor nor the executor is framed by the raw user text alone —
        # both are framed by this SPECIALIST_BRIEF first (supervisor.jinja,
        # executor.jinja). Cached for the whole run, including recovery passes —
        # the underlying task doesn't change across a re-plan.
        from .prompt_enhancer import compile_brief as _compile_brief
        from .prompt_enhancer import enhance as _enhance_task

        _brief = _enhance_task(goal, system_spec=_spec_block)
        _brief_block = _compile_brief(_brief)
        sysstate.add_fact("task_brief", _brief_block, source="prompt_enhancer")
        console.print(f"[dim]brief:[/] {_brief['specialist_role']}")

        # Build workspace snapshot BEFORE planning so supervisor knows what already exists.
        # This prevents planning steps that scaffold things already present, and avoids
        # false assumptions (e.g., "shadcn not initialized" when components.json is there).
        _ws_snap = self._workspace_snapshot(self._workspace)
        console.print(f"[dim]{_ws_snap}[/]")
        # Inject into sysstate so it persists for recovery passes too
        sysstate.add_fact("workspace_snapshot", _ws_snap, source="pre_flight")

        sv = supervisor.plan(goal, str(session.workspace), self._snap(session), sysstate=sysstate)
        plan: list = sv.get("plan", [])
        constraints: list[str] = _flatten_strings(sv.get("constraints", []))
        # RAW predicate objects. They stay typed all the way to `predicates.evaluate`;
        # only the prompts and the decision graph get the rendered text. Flattening them to
        # strings at the boundary is what left every downstream checker parsing prose.
        global_success: list[dict] = sv.get("success") or []

        # OCKE plan filter: block any steps containing forbidden cross-platform commands.
        if plan:
            plan, _ocke_rejections = ocke.filter_plan(plan)
            for _rej in _ocke_rejections:
                console.print(f"  [bold red]⊘ OCKE:[/] {_rej}")

        # GOAL-COMPLETENESS CHECK (deterministic, no technology knowledge): does
        # the plan address every item the user explicitly enumerated (e.g. "with
        # tailwindcss, shadcn, postcss, nanocss, autoprefixer")? A small model can
        # silently drop one item from a long list. If anything named is missing
        # from the plan entirely, force ONE corrective re-plan before executing
        # anything — never silently proceed on a gap the runtime can detect.
        if plan:
            _uncovered = _uncovered_requirements(goal, plan, constraints, global_success)
            if _uncovered:
                console.print(
                    f"[yellow]⚠ goal names {', '.join(_uncovered)} but no step "
                    f"addresses {'it' if len(_uncovered) == 1 else 'them'} — "
                    f"requesting a corrective plan[/]"
                )
                _cov_reason = (
                    f"The goal explicitly names: {', '.join(_uncovered)}. No step in "
                    f"the current plan addresses {'this' if len(_uncovered) == 1 else 'these'}. "
                    f"Revise the plan to cover every explicitly named item."
                )
                _cov_sv = supervisor.plan(
                    goal,
                    str(session.workspace),
                    self._snap(session),
                    failure_reason=_cov_reason,
                    sysstate=sysstate,
                )
                _cov_plan = _cov_sv.get("plan", [])
                if _cov_plan:
                    plan = _cov_plan
                    constraints = _flatten_strings(_cov_sv.get("constraints", [])) or constraints
                    global_success = (_cov_sv.get("success") or []) or global_success
                    plan, _ocke_rej2 = ocke.filter_plan(plan)
                    for _rej in _ocke_rej2:
                        console.print(f"  [bold red]⊘ OCKE:[/] {_rej}")
                _still_uncovered = _uncovered_requirements(goal, plan, constraints, global_success)
                if _still_uncovered:
                    console.print(
                        f"[dim]still not covered after corrective plan: "
                        f"{', '.join(_still_uncovered)} — proceeding anyway[/]"
                    )

        # Store the plan's success criteria as the desired operational state.
        # This is the ground truth for all verify() calls from here on.
        sysstate.set_desired_state(global_success)

        # DecisionGraph: the plan itself is a decision (kind=PLAN).
        from .decisions import DecisionKind as _DK

        _dplan = sysstate.decisions.propose_control(
            _DK.PLAN,
            command=f"plan[{len(plan)} steps]",
            success_criteria=predicates.render(global_success),
        )
        sysstate.decisions.close(
            _dplan,
            run_ok=True,
            achieved=bool(plan),
            reason=f"{len(plan)} steps after OCKE filter",
        )

        # Pre-execution check: does the workspace ALREADY satisfy the goal's predicates?
        #
        # This is decided by the filesystem alone. It used to consult the LLM verifier once
        # `artifacts_satisfied()` said yes — but that function returned yes vacuously
        # whenever its prose regex matched no criterion, and the model, handed criteria it
        # could not evaluate, confirmed. Ten of ten pilot tasks were declared COMPLETE
        # against an empty workspace, artifacts absent.
        #
        # A predicate that the runtime can evaluate is never delegated to a model. The LLM
        # verifier still runs, but AFTER execution and only where judgement is genuinely
        # required — never to grant an early exit.
        # And only FILESYSTEM predicates may grant it. `tool_on_path` says a program exists on
        # this host; it can never establish that the work is done. The `bun_frontend` scaffold
        # declared `tool_on_path(bun)` as its only goal criterion and was reported COMPLETE in
        # thirteen seconds against an empty workspace. A goal with no filesystem criterion has
        # nothing to prove already-done, so it proceeds.
        _fs_success = predicates.filesystem_criteria(global_success)
        if _fs_success and plan:
            arts_ok, missing_arts = predicates.evaluate(_fs_success, session.workspace)
            if arts_ok:
                reason = "; ".join(predicates.render(_fs_success))
                console.print(
                    f"[dim]pre-execution: all success predicates already hold — {reason}[/]"
                )
                console.print(Panel("[bold green]TASK COMPLETE[/]", title="Sistemista"))
                return RunVerdict.COMPLETE, reason
            missing_arts = [r.strip() for r in (missing_arts or "").split(";") if r.strip()]
            console.print(
                f"[dim]pre-execution: {len(missing_arts)} predicate(s) unmet "
                f"({'; '.join(missing_arts)[:160]}) — proceeding[/]"
            )

        console.print(f"[dim]Steps:[/] {len(plan)}")
        for i, s in enumerate(plan, 1):
            label = s.get("objective") or s.get("step") or str(s) if isinstance(s, dict) else str(s)
            console.print(f"  [dim]{i}.[/] {label}")
        if constraints:
            console.print(f"[dim]Constraints:[/] {', '.join(constraints)}")

        step_index = 0
        failed_steps: list[str] = []
        _last_verify_output: str = ""  # latest successful VERIFY step stdout

        # Every filesystem artifact the plan DECLARES it will produce — accumulated as each
        # step is processed, seeded with the goal-level criteria. The final verdict is vetoed
        # against this union, not just `global_success`: `node_backend` was reported COMPLETE
        # with `server.js` missing because the server-file predicate lived only in step 4's
        # `success`, never in the goal criteria, so the goal-level veto had nothing to check.
        # A requirement any step declared is a requirement the finished workspace must meet.
        _declared_success: list = list(global_success or [])

        while plan:
            item = plan[0]
            if isinstance(item, dict):
                current_step = item.get("objective") or item.get("step") or str(item)
                current_tool = item.get("launcher") or item.get("tool") or ""
                # Kept as raw predicate objects: `_artifact_check` evaluates them, and only
                # the prompts/telemetry render them to text. Flattening them to strings here
                # is what made the runtime check unable to read its own criteria.
                for _p in _repair_unsatisfiable_predicates(item):
                    console.print(
                        f"  [yellow]plan repair:[/] dir_not_empty({_p}) on a step that "
                        f"only creates it — downgraded to path_exists"
                    )
                step_success = item.get("success") or []
                if isinstance(step_success, list):
                    _declared_success.extend(step_success)
                step_capture = str(item.get("capture_stdout_to") or "")
                current_step_type = (item.get("step_type") or "MODIFY").upper()
                step_vars = item.get("vars") or {}
                if not isinstance(step_vars, dict):
                    step_vars = {}
            else:
                current_step = str(item)
                current_tool = ""
                step_success = []
                step_capture = ""
                current_step_type = "MODIFY"
                step_vars = {}

            if current_step_type not in ("DISCOVERY", "MODIFY", "VERIFY", "RECOVER"):
                current_step_type = "MODIFY"

            if current_tool:
                current_tool = normalize_launcher(current_tool, current_step)

            console.print(f"\n[bold yellow]►[/] {current_step}")
            if current_tool:
                console.print(f"  [dim]tool:[/] {current_tool}")
            if current_step_type != "MODIFY":
                console.print(f"  [dim]type:[/] {current_step_type}")

            step_passed = self._execute_step(
                goal,
                current_step,
                current_tool,
                step_success,
                constraints,
                session,
                terminal,
                step_index,
                supervisor,
                step_type=current_step_type,
                sysstate=sysstate,
                step_vars=step_vars,
                ocke=ocke,
                capture_stdout_to=step_capture,
            )

            # Always advance — never block the plan on a single step failure.
            # The final verify catches gaps and re-plans precisely.
            plan.pop(0)
            step_index += 1

            if step_passed:
                failed_steps.clear()
                # OCKE learning: record success for knowledge base confidence update.
                if sysstate.desired_state.success_criteria:
                    curr_dist = sysstate.update_distance(session.workspace)
                    if not curr_dist.is_zero():
                        trend = sysstate.distance_trend()
                        trend_str = f" [{trend}]" if trend not in ("unknown", "improving") else ""
                        console.print(f"  [dim]{curr_dist.summary()}{trend_str}[/]")
            else:
                failed_steps.append(current_step)
                # OCKE learning: record failure.
                # Effect-gate (linearity): a failed MODIFY step is a broken
                # prerequisite. Do NOT march through dependent steps on a broken
                # foundation (observed: scaffold fails → 8 doomed steps → replan).
                # Halt now and let the recovery loop replan on the REAL observed
                # state. DISCOVERY/VERIFY failures stay non-fatal (exploratory).
                if current_step_type == "MODIFY":
                    console.print(
                        "  [yellow]⚠ prerequisite (MODIFY) step failed — halting plan, "
                        "replanning on real state[/]"
                    )
                    break
                console.print("  [yellow]⚠ step failed — continuing[/]")

        # ── Final verify + recovery loop ──────────────────────────────────────
        # After all steps complete, verify the goal. If not achieved, re-plan
        # and execute a recovery pass (up to MAX_RECOVERY_PASSES times).
        MAX_RECOVERY_PASSES = 2
        _incomplete_reason = ""
        _recovery_obs = ""

        for _recovery_pass in range(MAX_RECOVERY_PASSES + 1):
            obs = observe(goal, session)
            det_ok, det_reason = observe_judge(goal, obs, session)
            if not det_ok:
                # For sysops goals (e.g. install globally, set env var) the workspace
                # will always be empty — success is on PATH/registry, not in workspace.
                # Detect this: no artifact criteria in success_criteria AND workspace empty
                # → bypass the workspace-empty failure and proceed to LLM verify.
                _arts_ok, _arts_missing = sysstate.desired_state.artifacts_satisfied(
                    session.workspace
                )
                if _arts_ok and not _arts_missing and "empty" in det_reason:
                    console.print("[dim]sysops goal detected — bypassing workspace-empty check[/]")
                    det_ok = True
                    det_reason = "system-level goal: no workspace artifacts required"
                else:
                    _incomplete_reason = det_reason
                    _recovery_obs = obs
                    # Deterministic final verify failed — record the decision
                    # so recovery-pass steps can link RECOVERS to it.
                    _dv = sysstate.decisions.propose_control(
                        _DK.FINAL_VERIFY,
                        success_criteria=predicates.render(global_success),
                        source="deterministic",
                    )
                    sysstate.decisions.close(_dv, run_ok=True, achieved=False, reason=det_reason)
            if det_ok:
                # Behavioral check
                from .tools.behavior_verifier import classify_workspace_state

                ws_op = classify_workspace_state(session.workspace, sysstate, run_smoke_test=True)
                sysstate.add_fact(
                    "operational_state", ws_op.to_summary(), source="behavior_verifier"
                )
                if not ws_op.behavioral_ok and ws_op.entry_command:
                    if ws_op.is_wrong_completion_assumption():
                        console.print(
                            "[yellow]⚠ state misunderstanding:[/] structural checks passed "
                            "but the system is not operational"
                        )
                        console.print(f"  [dim]entry: {ws_op.entry_command}[/]")
                        console.print(f"  [dim]issue: {ws_op.behavioral_issue}[/]")
                    elif ws_op.failure_class == "runtime_missing":
                        console.print(f"[yellow]⚠ runtime missing:[/] {ws_op.behavioral_issue}")
                    elif ws_op.failure_class == "execution_failed":
                        console.print(f"[yellow]⚠ smoke test failed:[/] {ws_op.behavioral_issue}")

                # Pass the INTENT to verify, not the full error context.
                # The planner needs the error trace; the verifier needs only
                # what was intended (the command/desired state).
                _verify_objective = _extract_goal_intent(goal)
                achieved, reason, _ = supervisor.verify(
                    _verify_objective,
                    session,
                    success_criteria=global_success or None,
                    command_output=_last_verify_output or None,
                )
                _dv = sysstate.decisions.propose_control(
                    _DK.FINAL_VERIFY,
                    success_criteria=predicates.render(global_success),
                )
                sysstate.decisions.close(
                    _dv, run_ok=True, achieved=bool(achieved), reason=str(reason or "")
                )
                # The LLM verifier may say the goal is met. The filesystem has the last word.
                # Observed on the `django` scaffold: `TASK COMPLETE` with no `manage.py`
                # anywhere, because the goal's own `file_has_content(manage.py)` predicate was
                # never consulted at the moment the verdict was issued. A verifier that evidence
                # can overrule is a verifier; one that it cannot is an opinion.
                # The veto is over EVERY declared filesystem artifact (goal + steps), not just
                # the goal criteria: `node_backend` passed with `server.js` missing because the
                # server predicate lived only in a step's `success`.
                if achieved:
                    _fs = predicates.filesystem_criteria(_declared_success)
                    _fs_ok, _fs_why = (
                        predicates.evaluate(_fs, session.workspace) if _fs else (True, "")
                    )
                    if not _fs_ok:
                        console.print(
                            "  [yellow]⚠ verifier said achieved, filesystem "
                            f"disagrees:[/] {_fs_why}"
                        )
                        trace.emit(
                            "verdict_override",
                            rule="filesystem_beats_verifier",
                            verifier_reason=str(reason)[:200],
                            failures=_fs_why[:300],
                        )
                        achieved, reason = False, _fs_why

                if achieved:
                    console.print(f"[dim]Goal verified: {reason}[/]")
                    console.print(Panel("[bold green]TASK COMPLETE[/]", title="Sistemista"))
                    return RunVerdict.COMPLETE, reason
                    return
                _incomplete_reason = reason
                _recovery_obs = obs

            if _recovery_pass >= MAX_RECOVERY_PASSES:
                break

            # Goal not yet achieved — re-plan and execute a recovery pass
            console.print(
                f"[yellow]⚠ incomplete[/] (pass {_recovery_pass + 1}/{MAX_RECOVERY_PASSES}): "
                f"{_incomplete_reason} — re-planning"
            )
            _rsnap = self._snap(session)
            # Sanitize the failure reason: if it starts with '{' it is a raw
            # JSON string from a failed verify_call parse, not a human-readable
            # message. Extract the inner "reason" field or fall back to a generic
            # description so the re-planner gets a useful signal, not raw JSON.
            _freason = _incomplete_reason
            if _freason.strip().startswith("{"):
                import json as _json

                try:
                    _parsed_fr = _json.loads(_freason)
                    _freason = str(_parsed_fr.get("reason", ""))
                except Exception:
                    from .model_router import _extract_json_object as _exjson

                    _pobj = _exjson(_freason)
                    _freason = str(_pobj.get("reason", "")) if _pobj else ""
                if not _freason:
                    _freason = "verification failed — one or more required artifacts may be missing"
            _rsv = supervisor.plan(
                goal, str(session.workspace), _rsnap, failure_reason=_freason, sysstate=sysstate
            )
            plan = _rsv.get("plan", [])
            _drp = sysstate.decisions.propose_control(
                _DK.REPLAN,
                command=f"replan[pass {_recovery_pass + 1}]",
            )
            sysstate.decisions.close(_drp, run_ok=True, achieved=bool(plan), reason=_freason[:200])
            if not plan:
                break
            _rconstr = _flatten_strings(_rsv.get("constraints", [])) or constraints
            _rsuccess = (_rsv.get("success") or []) or global_success
            global_success = _rsuccess
            sysstate.set_desired_state(_rsuccess)
            console.print(f"[dim]Recovery plan: {len(plan)} step(s)[/]")
            for _ri, _rs in enumerate(plan, 1):
                _rl = (
                    _rs.get("objective") or _rs.get("step") or str(_rs)
                    if isinstance(_rs, dict)
                    else str(_rs)
                )
                console.print(f"  [dim]{_ri}.[/] {_rl}")

            _ridx = step_index
            while plan:
                _ritem = plan[0]
                if isinstance(_ritem, dict):
                    _rstep = _ritem.get("objective") or _ritem.get("step") or str(_ritem)
                    _rtool = normalize_launcher(_ritem.get("launcher") or "", _rstep)
                    # RAW predicate objects, like the main plan. `_flatten_strings` collapses
                    # {"check":"file_has_content","path":"package.json"} to the bare string
                    # "file_has_content", which `predicates.evaluate` then rejects as "not a
                    # predicate object" — so every RECOVERY step silently lost its artifact
                    # check. Observed on a live React scaffold: two recovery passes, both
                    # unverifiable.
                    _rssc = _ritem.get("success") or []
                    _rstype = (_ritem.get("step_type") or "MODIFY").upper()
                    _rvars = _ritem.get("vars") or {}
                    if not isinstance(_rvars, dict):
                        _rvars = {}
                else:
                    _rstep, _rtool, _rssc, _rstype, _rvars = str(_ritem), "", [], "MODIFY", {}
                if _rstype not in ("DISCOVERY", "MODIFY", "VERIFY", "RECOVER"):
                    _rstype = "MODIFY"
                console.print(f"\n[bold yellow]►[/] {_rstep}")
                if _rtool:
                    console.print(f"  [dim]tool:[/] {_rtool}")
                _rok = self._execute_step(
                    goal,
                    _rstep,
                    _rtool,
                    _rssc,
                    _rconstr,
                    session,
                    terminal,
                    _ridx,
                    supervisor,
                    step_type=_rstype,
                    sysstate=sysstate,
                    step_vars=_rvars,
                    ocke=ocke,
                    recovery_pass=True,
                )
                plan.pop(0)
                _ridx += 1
                # Same effect-gate as the main loop: a failed MODIFY prerequisite
                # halts this recovery pass so the NEXT pass replans on real state
                # instead of marching dependent steps on a broken foundation.
                if not _rok and _rstype == "MODIFY":
                    console.print(
                        "  [yellow]⚠ prerequisite (MODIFY) step failed — halting "
                        "recovery pass, will replan on real state[/]"
                    )
                    break

        console.print(f"[bold red]TASK INCOMPLETE:[/] {_incomplete_reason}")
        console.print(f"[dim]Filesystem state:\n{_recovery_obs}[/]")
        return RunVerdict.INCOMPLETE, _incomplete_reason

    # ── Step executor ────────────────────────────────────────────────────────

    def _execute_step(
        self,
        goal,
        current_step,
        current_tool,
        step_success,
        constraints,
        session,
        terminal,
        step_index,
        supervisor,
        step_type: str = "MODIFY",
        sysstate: "SystemState | None" = None,
        step_vars: dict | None = None,
        ocke=None,
        recovery_pass: bool = False,
        capture_stdout_to: str = "",
    ) -> bool:
        """
        Try to reach the step's target state up to MAX_RETRIES_PER_STEP times.
        Returns True only when all step_success criteria pass.
        Routes verification through step_type: DISCOVERY/MODIFY/VERIFY/RECOVER.
        Every attempt is reified as a Decision node (Predict→Observe→Compare→Update).
        """
        tool = current_tool
        step_vars = step_vars or {}

        # ── The step's postcondition already holds: there is nothing to do ──────
        #
        # A step DECLARES what "done" means, as typed predicates the runtime evaluates without
        # executing anything. If that condition is already true, running the command cannot
        # make it truer — it can only cost a shell round-trip, and on a re-plan it re-does work
        # the previous plan already completed.
        #
        # MEASURED on two isolated 48-task runs: 41 and 47 re-plans, discarding 55 and 65
        # commands that had ALREADY SUCCEEDED — ~1.35 per re-plan, ~22% of all successful work.
        # The planner regenerates a genuinely different plan almost every time (only 2% of
        # re-plans repeat a fingerprint), so the waste is not duplicate inference: it is valid
        # work thrown away because the new plan cannot inherit the old one's progress.
        #
        # This is the same `predicates.evaluate` that `_artifact_check` runs AFTER the step —
        # the symmetric question, asked before. No model, no subprocess (enforced by
        # tests/test_predicates.py).
        #
        # MODIFY only. DISCOVERY exists to populate facts other steps consume, and its value is
        # the knowledge, not an artifact — skipping it would silently starve the DISCOVERY→
        # ACTION channel. VERIFY produces the output the loop reads back. RECOVER must run.
        if step_type == "MODIFY" and step_success:
            _already, _why = predicates.evaluate(step_success, session._cwd)
            if _already:
                console.print(f"  [dim]skipped:[/] postcondition already holds — {_why[:100]}")
                trace.emit(
                    "step_skipped",
                    rule="postcondition_already_holds",
                    step=str(current_step)[:120],
                    criteria=predicates.render(step_success),
                )
                return True

        # ── Vars resolution (invariant: executor never sees $VAR placeholders) ──
        if step_vars and tool and sysstate is not None:
            tool, unresolved_vars = _resolve_step_vars(tool, step_vars, sysstate)
            if unresolved_vars:
                # Some vars are empty — try to fill from existing facts first
                # (the DISCOVERY step that ran earlier is the source of truth)
                if sysstate.facts:
                    tool, unresolved_vars = _resolve_step_vars(tool, step_vars, sysstate)
                if unresolved_vars:
                    msg = (
                        f"ABORT: unresolved vars {unresolved_vars} in command — "
                        "run a DISCOVERY step first to fill these values"
                    )
                    console.print(f"  [bold red]✗ {msg}[/]")
                    return False

        # Resolve <PLACEHOLDER> forward-references from prior discovery outputs
        # before any attempt so the resolved command is also what gets tracked.
        if tool and sysstate is not None and not _is_fileops(tool):
            tool = _resolve_discovery_refs(tool, sysstate)
        attempt_failures: list[str] = []
        tried_tools: list[str] = []  # all commands attempted this step, in order

        _next_source = "plan"  # who proposed the current command (fix engines update it)

        # ── Close DISCOVERY→ACTION: author the shell command from research NOW ──
        # The plan-time launcher was frozen before any DISCOVERY step ran, so it
        # cannot use what was learned. When research exists, let the executor coder
        # author the concrete command from it (the launcher becomes a hint). Scope:
        # executor-delegated shell MODIFY actions only — NOT VERIFY (a verify checks
        # state, it must never be re-authored into a create/build; observed: a
        # "verify routing present" step got authored into `ng new && ng build`,
        # re-scaffolding the whole project), not fileops, not interactive PTY
        # wizards. Fallback to the planner launcher on any empty/invalid result, so
        # this never regresses below the frozen-launcher baseline.
        if (
            EXECUTOR_AUTHORS_ACTIONS
            and tool
            and sysstate is not None
            and step_type == "MODIFY"
            and not _is_fileops(tool)
            and not is_interactive(tool)
        ):
            _notes = _research_notes(sysstate)
            if _notes:
                _authored = self._author_command(
                    goal=goal,
                    step=current_step,
                    tool_hint=tool,
                    stderr="",
                    checkpoint=predicates.render(step_success),
                    session=session,
                    sysstate=sysstate,
                    tried_commands=[],
                    research_notes=_notes,
                    ocke=ocke,
                )
                if _authored:
                    console.print(f"  [dim]authored from research:[/] {_authored}")
                    tool = _authored
                    _next_source = "executor_authored"

        # ── DecisionGraph: reify this attempt BEFORE anything runs (Predict) ──
        _dlog = getattr(sysstate, "decisions", None) if sysstate is not None else None
        _decision = None
        if _dlog is not None:
            _decision = _dlog.propose_step(
                step_id=f"step_{step_index}",
                step_type=step_type,
                command=tool or "(no-op)",
                success_criteria=predicates.render(step_success),
                attempt=0,
                source="plan",
                recovery_pass=recovery_pass,
            )

        # ── Reasoning: pre-execute policy gate ──────────────────────────────
        _reasoning = getattr(sysstate, "reasoning", None) if sysstate is not None else None
        if _reasoning is not None and tool:
            _allow, _policy_reason = _reasoning.pre_execute_check(
                tool, f"step_{step_index}", step_type
            )
            if not _allow:
                console.print(f"  [bold yellow]⊘ POLICY:[/] {_policy_reason}")
                if _dlog is not None and _decision is not None:
                    _dlog.block(_decision, _policy_reason)
                return False

        # ── Content-authoring fast path (architectural fix; seed-42 control experiment) ──
        # A "write file X with content" step is authored as FILE CONTENT, not a shell command:
        # asked for "one shell command" the coder makes an empty `New-Item -ItemType File`;
        # asked for the file body it writes a correct file. This bypasses the shell (and its
        # multi-line quoting) entirely and, on any empty/unsatisfying result, falls through to
        # the shell/retry path below — so it can never regress below the shell baseline.
        if sysstate is not None and step_type == "MODIFY":
            _ctarget = _content_write_target(step_success, tool)
            if _ctarget and self._author_and_write_content(
                goal, current_step, _ctarget, step_success, session, sysstate, step_index
            ):
                if _dlog is not None and _decision is not None:
                    _dlog.close(
                        _decision,
                        run_ok=True,
                        achieved=True,
                        reason=f"authored file content → {_ctarget}",
                    )
                return True

        for attempt in range(MAX_RETRIES_PER_STEP):
            if attempt > 0:
                console.print(f"  [dim]retry {attempt}/{MAX_RETRIES_PER_STEP - 1}[/]")
                # Each attempt is its own decision node (RETRY_OF/REPLACES edge).
                if _dlog is not None:
                    _decision = _dlog.propose_step(
                        step_id=f"step_{step_index}",
                        step_type=step_type,
                        command=tool or "",
                        success_criteria=predicates.render(step_success),
                        attempt=attempt,
                        source=_next_source,
                    )
                # The policy gate applies to replacement commands too: a fix
                # must not resurrect a blocked or already-failed decision
                # (recovery that repeats a failed decision is a bug).
                if _reasoning is not None and tool:
                    _allow_fix, _fix_reason = _reasoning.pre_execute_check(
                        tool, f"step_{step_index}", step_type
                    )
                    if not _allow_fix:
                        console.print(f"  [bold yellow]⊘ POLICY (fix):[/] {_fix_reason}")
                        if _dlog is not None and _decision is not None:
                            _dlog.block(_decision, _fix_reason)
                        break
            if tool:
                tried_tools.append(tool)

            # A scaffold/init command with no declared success predicate is the
            # one class of step _artifact_check cannot police (empty criteria =
            # no-op there). Snapshot the workspace now so a no-op run (exit 0,
            # nothing created) can be caught below instead of auto-passing.
            _fp_gate = (
                step_type == "MODIFY"
                and not step_success
                and tool
                and not _is_fileops(tool)
                and _is_scaffold_init(tool)
            )
            _pre_fp = _shallow_fingerprint(self._workspace) if _fp_gate else None

            # ── Run the action ──
            _t0 = time.time()
            # Track whether run_out is a raw PTY transcript. A PTY transcript is
            # a truncated screen buffer — it must NEVER be used as evidence for
            # structural verification (path/placement), because the verifier will
            # read truncated path strings and hallucinate "created in wrong dir".
            # Structural truth comes ONLY from the filesystem (observe snapshot).
            is_pty_output = False
            if not tool:
                run_ok, run_out = True, "(no-op)"
            elif _is_fileops(tool):
                run_ok, run_out = self._run_fileops(
                    tool, session, goal, step_index, sysstate=sysstate
                )
            elif not is_interactive(tool):
                run_ok, run_out = self._run_batch(
                    tool, goal, session, step_index, current_step, ocke=ocke
                )
            elif step_type == "DISCOVERY":
                # A DISCOVERY step must NOT launch a stateful interactive wizard
                # (no structured output, gets stuck in prompt loops). Rather than
                # silently doing nothing — which starves the DISCOVERY→ACTION
                # research channel and forces the executor to author the next
                # command with zero grounding — auto-convert the attempt into the
                # real research it should have been: a web_search for the same
                # tool's current non-interactive invocation.
                _query = _discovery_query_from_interactive(tool)
                if _query:
                    console.print(
                        f"  [yellow]⊘ interactive tool — auto-converting DISCOVERY to research:[/] {_query}"
                    )
                    from .tools.web_search import search as _wsearch

                    _sok, _sout = _wsearch(_query, session._cwd)
                    run_ok, run_out = True, (_sout if _sok else f"(web_search failed: {_sout})")
                else:
                    console.print(
                        "  [yellow]⊘ DISCOVERY step tried to launch interactive tool — skipping PTY[/]"
                    )
                    run_ok, run_out = True, "(DISCOVERY skip: no nameable tool to research)"
            elif step_type == "VERIFY":
                # A VERIFY step must NOT launch a stateful interactive wizard either
                # (observed: a VERIFY step ran `shadcn init` 4× via PTY, navigating
                # menus, doing nothing). Unlike DISCOVERY, VERIFY has nothing to
                # research — it is meant to check state, not gather it — so this
                # stays a no-op; the real verification (artifact_check /
                # observe_judge) still runs on the workspace regardless.
                console.print(
                    "  [yellow]⊘ VERIFY step tried to launch interactive tool — skipping PTY[/]"
                )
                _tool_exe = tool.split()[0] if tool else tool
                run_ok, run_out = (
                    True,
                    (
                        f"(VERIFY skip: '{_tool_exe}' is an interactive wizard — "
                        f"read-only steps never drive wizards. "
                        f"'{_tool_exe}' is available; invoke it in a MODIFY step with inline flags.)"
                    ),
                )
            else:
                run_ok, run_out = self._run_interactive(
                    tool,
                    goal,
                    current_step,
                    step_success,
                    constraints,
                    session,
                    terminal,
                    step_index,
                )
                is_pty_output = True

            # The runtime performs the redirection the model kept forgetting. Placed BEFORE
            # verification so `_artifact_check` and `observe` see the file that now exists.
            # PTY transcripts are excluded: they carry ANSI and screen state, not an answer.
            if ARTIFACT_CAPTURE and capture_stdout_to and not is_pty_output:
                _cap = artifact_capture.capture(
                    capture_stdout_to,
                    run_out or "",
                    session._cwd,
                    exit_code=0 if run_ok else 1,
                )
                if _cap.written:
                    console.print(
                        f"  [dim]captured stdout → {capture_stdout_to} ({_cap.bytes_written} B)[/]"
                    )
                elif _cap.reason not in ("artifact already has content — command wrote it",):
                    console.print(f"  [yellow]⚠ capture skipped:[/] {_cap.reason}")

            # Normalize the workspace shape before anything judges it. Initializers create
            # the project directory themselves, and several ecosystems have no way to say
            # "here" — `ng new .` is invalid. So the runtime lets them nest and hoists after,
            # rather than demanding the model produce a shape half the ecosystems cannot.
            if step_type in ("MODIFY", "RECOVER") and run_ok:
                _h = workspace_shape.hoist_nested_project(session.workspace)
                if _h.hoisted:
                    console.print(
                        f"  [dim]workspace shape:[/] hoisted {_h.entries} entries out "
                        f"of '{_h.source}/' — the workspace IS the project root"
                    )

            # FASE 2+3: record the action result; learn capabilities from it.
            if sysstate is not None and tool:
                result = ActionResult(
                    command=tool,
                    success=bool(run_ok),
                    stdout=run_out or "",
                    exit_code=0 if run_ok else 1,
                    duration=round(time.time() - _t0, 3),
                    side_effects=[f"step_type={step_type}"],
                )
                sysstate.record(result)

            # ── Verify: route on step_type ──────────────────────────────────
            obs = observe(current_step, session)
            det_ok, det_reason = observe_judge(
                current_step,
                obs,
                session,
                step_type=step_type,
                stdout=run_out or "",
                exit_code=0 if run_ok else 1,
            )

            if not det_ok:
                # Check if this is the "scaffolded into subdir" case — fix it natively.
                if "instead of workspace root" in det_reason:
                    ok, msg = _move_subdir_to_root(session.workspace)
                    console.print(f"  [dim]{'✓' if ok else '✗'} flatten subdir:[/] {msg}")
                    attempt_failures.append(f"not achieved: {det_reason}")
                    memory.save_event(
                        goal=goal,
                        cwd=str(session._cwd),
                        command="flatten_subdir",
                        stdout=msg,
                        exit_code=0 if ok else 1,
                        outcome="success" if ok else "failure",
                        step_index=step_index,
                    )
                    continue
                achieved, reason = False, det_reason
            else:
                if step_type == "DISCOVERY":
                    # Judge already checked stdout quality; trust it.
                    achieved, reason = True, det_reason
                elif step_type == "VERIFY":
                    # The command IS the verification — a non-zero exit means the
                    # verified thing is broken, not just "workspace empty".
                    if not run_ok:
                        achieved = False
                        reason = (run_out or "verify command failed")[:200]
                    else:
                        achieved, reason = True, det_reason
                        if run_out:
                            _last_verify_output = run_out
                elif not run_ok:
                    # Tool exited non-zero — fail immediately; skip LLM call.
                    # Workspace may still have content from prior steps, so
                    # observe_judge passed, but the command itself failed.
                    achieved = False
                    reason = (run_out or "command failed")[:200]
                elif _is_fileops(tool):
                    # Fileops (write_file, append_file, etc.) are deterministic.
                    # run_ok=True + det_ok=True is sufficient — no LLM needed.
                    achieved, reason = True, det_reason
                elif step_success:
                    # Plan provided explicit per-step success criteria.
                    # If the command succeeded and the observer already confirms the
                    # workspace looks correct, skip LLM verify — it hallucinates failure
                    # on steps like "python -m venv venv" where there's no stdout to inspect.
                    # Call LLM only when stdout needs interpretation (e.g. pip install output).
                    # Only call LLM when output signals ambiguity or failure.
                    # "successfully installed" and "requirement already satisfied" are
                    # deterministic pip success — LLM would hallucinate failure by looking
                    # at the workspace .venv (which won't have a system-install tool).
                    # A PTY transcript is a truncated screen buffer, not clean
                    # stdout: its "error/warning" keywords (e.g. "2 moderate
                    # severity vulnerabilities") are noise, and its truncated paths
                    # mislead the verifier. For PTY steps, rely on the filesystem
                    # snapshot + step criteria only — never feed the transcript in.
                    _needs_output_check = (
                        (not is_pty_output)
                        and run_out
                        and any(kw in run_out.lower() for kw in ("error", "warning", "failed"))
                    )
                    if run_ok and not _needs_output_check:
                        achieved, reason = True, det_reason
                    else:
                        achieved, reason, _ = supervisor.verify(
                            current_step,
                            session,
                            success_criteria=step_success,
                            command_output=None if is_pty_output else run_out,
                        )
                else:
                    # No explicit criteria: trust run_ok=True + observe_judge.
                    # LLM verify on intermediate steps without criteria applies project-level
                    # completeness rules to single-step outcomes, causing false negatives
                    # (e.g. "only .venv exists" → fail, even for a "create venv" step).
                    achieved, reason = True, det_reason
                    if _pre_fp is not None and _shallow_fingerprint(self._workspace) == _pre_fp:
                        achieved = False
                        reason = (
                            "scaffold command exited 0 but created nothing in the "
                            "workspace — no declared success predicate to check "
                            "otherwise (invariant #9)"
                        )

            # ── Artifact-based verification (overrides optimistic achieved=True) ──
            # Check that files the tool is expected to produce actually exist.
            # This catches cases where the process exited cleanly but was interrupted.
            # NEVER run on DISCOVERY steps: they intentionally skip execution, so
            # no artifacts will exist by design — absence of file ≠ tool failure.
            if achieved and tool and step_type != "DISCOVERY":
                art_ok, art_reason = _artifact_check(
                    tool, current_step, str(session._cwd), step_success=step_success
                )
                if not art_ok:
                    console.print(f"  [yellow]⚠ artifact check failed:[/] {art_reason}")
                    achieved = False
                    reason = art_reason

            if achieved:
                check_failures = []
            else:
                check_failures = [f"not achieved: {reason}"]

            # ── Reasoning: post-step inference ───────────────────────────────
            _ec_for_reasoning = None
            _r_conclusions: list[str] = []
            if _reasoning is not None and tool:
                if not run_ok and run_out:
                    _ec_for_reasoning = _classify_error(run_out, exit_code=1, command=tool)
                _r_conclusions = _reasoning.post_step_update(
                    step_id=f"step_{step_index}_a{attempt}",
                    command=tool,
                    success=achieved,
                    error_class=_ec_for_reasoning,
                    output=run_out or "",
                    step_type=step_type,
                )
                for _rc in _r_conclusions:
                    console.print(f"  [dim cyan]⟹[/] {_rc}")

            # ── DecisionGraph: Observe + Compare + Update ────────────────────
            # The observation is attached to the decision node; CONFIRMED when
            # it matches the prediction, DIVERGED otherwise. The divergence,
            # with its error class and belief conclusions, is the learning signal.
            if _dlog is not None and _decision is not None:
                _dlog.close(
                    _decision,
                    run_ok=bool(run_ok),
                    achieved=bool(achieved),
                    reason=str(reason or ""),
                    error_class=(_ec_for_reasoning.value if _ec_for_reasoning is not None else ""),
                    latency_s=round(time.time() - _t0, 3),
                    conclusions=_r_conclusions,
                )

            if not check_failures:
                console.print("[green]✓[/] Step complete")
                # FASE 3+4: capture clean discovery output as a fact NOW, while
                # run_out is in scope. (Reading memory later returns the DONE
                # marker with empty stdout — the data would be lost.)
                if sysstate is not None and step_type == "DISCOVERY":
                    from .tools.observer import _strip_error_noise

                    clean = _strip_error_noise(run_out or "")
                    if clean:
                        sysstate.add_discovery(current_step, clean)
                memory.save_event(
                    goal=goal,
                    cwd=str(session._cwd),
                    command=f"DONE:{current_step}",
                    stdout="",
                    exit_code=0,
                    outcome="success",
                    step_index=step_index,
                )
                return True

            # ── Criteria failed — log and decide next action ──
            for f in check_failures:
                console.print(f"  [yellow]⚠[/] {f}")
            attempt_failures.extend(check_failures)

            tool_output = run_out[:300] if run_out else ""
            memory.save_event(
                goal=goal,
                cwd=str(session._cwd),
                command=f"CHECK_FAIL:{tool}",
                stdout=tool_output,
                exit_code=1,
                outcome="failure",
                step_index=step_index,
            )

            if attempt < MAX_RETRIES_PER_STEP - 1:
                # ── Error classification: constrain recovery to allowed actions ──
                if run_out and not run_ok:
                    _err_class = _classify_error(run_out, exit_code=1, command=tool)
                    if _err_class != ErrorClass.UNKNOWN:
                        console.print(f"  [dim]error class:[/] {_err_class.value}")
                        # Forbidden: writing text to a known-executable path
                        _lc_out = run_out.lower()
                        if (
                            "is not a valid" in _lc_out
                            or "bad exe" in _lc_out
                            or "exec format" in _lc_out
                        ):
                            console.print(
                                "  [bold red]✗ corrupt/invalid executable detected — "
                                "only reinstall or delete allowed, NOT file-overwrite[/]"
                            )
                            # Transition the node to DIRTY so locate() does not
                            # re-register it as DISCOVERED on the next pass.
                            # Identity comes from the world graph (alias index),
                            # not from substring-matching store keys.
                            if sysstate is not None:
                                _cmd_bin = tool.strip().split()[0]
                                from .state import EntityState as _ES

                                _node = sysstate.world.resolve(_cmd_bin)
                                if _node is not None:
                                    sysstate.transition_entity(_node.id, _ES.DIRTY)
                                    console.print(f"  [dim]entity → DIRTY:[/] {_node.id}")

                # A repair the runtime can DERIVE outranks one it has to ask for. The stream
                # rule needs the exit code, the redirect target and one stat() — no model.
                _stream_fix = ""
                if run_ok and check_failures:
                    _stream_fix = _stderr_only_output(tool, session._cwd)
                    if _stream_fix in tried_tools:
                        _stream_fix = ""
                if _stream_fix:
                    tool = _stream_fix
                    _next_source = "stderr_redirect_repair"
                    trace.emit("plan_repair", rule="stderr_only_output", command=tool[:200])
                    console.print(
                        "  [dim]runtime repair:[/] exited 0 but the artifact is "
                        "empty — the output went to stderr; merging streams"
                    )
                    memory.save_event(
                        goal=goal,
                        cwd=str(session._cwd),
                        command=f"FIX_ATTEMPT:{tool[:120]}",
                        stdout="",
                        exit_code=0,
                        outcome="pending",
                        step_index=step_index,
                    )
                    continue

                suggested = _extract_tool_suggestion(run_out)
                _norm_suggested = normalize_launcher(suggested, current_step) if suggested else ""
                if _norm_suggested and _norm_suggested not in tried_tools:
                    tool = _norm_suggested
                    _next_source = "tool_suggestion"
                    console.print(f"  [dim]tool self-reported replacement:[/] {tool}")
                    # Record fix attempt in memory so supervisor can learn from it
                    memory.save_event(
                        goal=goal,
                        cwd=str(session._cwd),
                        command=f"FIX_ATTEMPT:{tool[:120]}",
                        stdout="",
                        exit_code=0,
                        outcome="pending",
                        step_index=step_index,
                    )
                else:
                    if EXECUTOR_AUTHORED_FIX:
                        # Executor coder authors the correction from the REAL stderr
                        # + checkpoint (executor.jinja). The planner picked the tool;
                        # the coder owns the exact command and self-corrects on the fly.
                        #
                        # When the command exited 0 but the ARTIFACT check failed — the file
                        # was created EMPTY (`New-Item -ItemType File` with no content) — `run_out`
                        # holds the shell's success message, not the failure. The coder, told the
                        # command succeeded, re-authors the same empty-file command (measured on
                        # `node_backend`/`react`: server.js 0B, package.json empty, looped to
                        # INCOMPLETE). Feed it the artifact failure so it knows the file needs
                        # CONTENT, not merely to exist.
                        _authoring_stderr = run_out or ""
                        if check_failures:
                            _cf = "; ".join(check_failures)
                            _authoring_stderr = (
                                f"{_authoring_stderr}\n{_cf}".strip() if _authoring_stderr else _cf
                            )
                        fix = self._author_command(
                            goal=goal,
                            step=current_step,
                            tool_hint=tool,
                            stderr=_authoring_stderr,
                            checkpoint=predicates.render(step_success),
                            session=session,
                            sysstate=sysstate,
                            tried_commands=tried_tools,
                            research_notes=_research_notes(sysstate),
                            ocke=ocke,
                        )
                    else:
                        fix = self._get_fix(
                            goal=goal,
                            step=current_step,
                            tool=tool,
                            failures=attempt_failures[-5:],
                            session=session,
                            sysstate=sysstate,
                            tried_commands=tried_tools,
                        )
                    # Enforce FORBIDDEN_ALWAYS 'create_fake_output' (was dead
                    # code): don't let a failed external tool be "recovered" by
                    # hand-writing the artifact it was supposed to generate —
                    # that fakes progress and poisons every dependent step.
                    if tried_tools and _is_fabrication_fix(tried_tools[0], fix or ""):
                        from .error_classifier import is_recovery_forbidden

                        _forbidden, _why = is_recovery_forbidden("create_fake_output")
                        console.print(
                            f"  [bold red]✗ fabrication blocked:[/] a failed external "
                            f"tool cannot be recovered by hand-writing its output — {_why}"
                        )
                        break
                    if fix and fix not in tried_tools:
                        tool = fix
                        _next_source = "executor_fix"
                        console.print(f"  [dim]fix:[/] {tool}")
                        # Record what the executor suggested so supervisor can
                        # see the full retry history when recovery is needed.
                        memory.save_event(
                            goal=goal,
                            cwd=str(session._cwd),
                            command=f"FIX_ATTEMPT:{tool[:120]}",
                            stdout="",
                            exit_code=0,
                            outcome="pending",
                            step_index=step_index,
                        )
                    else:
                        # Executor cannot suggest a different command — break
                        # early rather than wasting retries on the same failure.
                        if fix in tried_tools:
                            console.print(
                                f"  [dim]fix already tried — aborting step:[/] {fix[:60]}"
                            )
                        else:
                            console.print("  [dim]no alternative fix available — aborting step[/]")
                        break

        return False

    # ── Batch execution ──────────────────────────────────────────────────────

    def _run_batch(
        self, tool, goal, session, step_index, current_step, ocke=None
    ) -> tuple[bool, str]:
        # OCKE: hard-validate command before execution.
        # This is the last guard — catches any cross-platform command that
        # slipped through the plan-level filter (e.g. from executor fix suggestions).
        if ocke is not None:
            _vr = ocke.validate_command(tool)
            if not _vr.ok:
                console.print(f"  [bold red]⊘ OCKE BLOCK:[/] {_vr.reason}")
                memory.save_event(
                    goal=goal,
                    cwd=str(session._cwd),
                    command=f"OCKE_BLOCK:{tool[:60]}",
                    stdout=_vr.reason,
                    exit_code=1,
                    outcome="failure",
                    step_index=step_index,
                )
                return False, _vr.reason

        # ── Bug D: stateless background-job handling ───────────────────────
        # Each session.run() spawns a fresh shell — PowerShell job variables
        # ($job, $j) do NOT persist across steps. A plan that does
        #   step N:   $j = Start-Job { npm run dev }; ... Receive-Job $j
        #   step N+1: Stop-Job $j; Remove-Job $j        ← $j is null here
        # is structurally broken. Instead of trying to persist shell state, we
        # make long-running launches self-terminating (session.run caps dev
        # servers at a short timeout) and treat the orphaned Stop-Job as a no-op.
        _job_action = _classify_job_command(tool)
        if _job_action == "launch":
            # Rewrite "$j = Start-Job { <inner> }; ...; Receive-Job $j ..." to run
            # <inner> directly. session.run() caps dev-server commands by timeout,
            # so the process self-terminates and we capture startup output.
            _inner = _extract_startjob_inner(tool)
            if _inner:
                console.print(
                    f"  [dim]stateless job: running inline (timeout-capped):[/] {_inner[:60]}"
                )
                tool = _inner
            # fall through to normal execution with the unwrapped command
        elif _job_action == "stop":
            # The job was already terminated by its launch-step timeout. There is
            # no live $job to stop. This is success — the desired post-condition
            # (no running dev server) already holds.
            console.print(
                "  [dim]stateless job: stop is a no-op (job already terminated by timeout)[/]"
            )
            memory.save_event(
                goal=goal,
                cwd=str(session._cwd),
                command=f"JOB_STOP_NOOP:{tool[:60]}",
                stdout="job already terminated",
                exit_code=0,
                outcome="success",
                step_index=step_index,
            )
            return (
                True,
                "background job already terminated (stateless model — no cross-step job handle)",
            )

        # Intercept mkdir/New-Item Directory when target already exists or IS the workspace.
        # The supervisor often tries to create the workspace dir itself — skip silently.
        if _is_mkdir_existing(tool, session._cwd, self._workspace):
            msg = "(directory already exists — skipped)"
            console.print(f"  [dim]skip mkdir:[/] {msg}")
            return True, msg

        # Intercept workspace-clear intent regardless of how the supervisor phrased it
        if self._is_workspace_clear_intent(tool):
            ok, msg = session.clear_workspace()
            console.print(f"  [dim]clear workspace:[/] {msg}")
            memory.save_event(
                goal=goal,
                cwd=str(session._cwd),
                command="clear_workspace",
                stdout=msg,
                exit_code=0 if ok else 1,
                outcome="success" if ok else "failure",
                step_index=step_index,
            )
            return ok, msg

        # Intercept New-Item ... -ItemType File: route through write_file which
        # creates parent directories automatically and is idempotent.
        _ni = _intercept_new_item_file(tool, session._cwd)
        if _ni is not None:
            ok, out = _ni
            console.print(f"  [dim]fileop intercept (new-item):[/] {out[:120]}")
            memory.save_event(
                goal=goal,
                cwd=str(session._cwd),
                command=f"FILEOP_NEWITEM:{tool[:60]}",
                stdout=out[:300],
                exit_code=0 if ok else 1,
                outcome="success" if ok else "failure",
                step_index=step_index,
            )
            return ok, out

        # Intercept Set-Content / Add-Content — parse and route through native fileops
        # to avoid PowerShell quoting issues with multiline content
        _intercepted = _intercept_content_cmd(tool, session._cwd)
        if _intercepted is not None:
            ok, out = _intercepted
            console.print(f"  [dim]fileop intercept:[/] {out[:120]}")
            memory.save_event(
                goal=goal,
                cwd=str(session._cwd),
                command=f"FILEOP:{tool[:60]}",
                stdout=out[:300],
                exit_code=0 if ok else 1,
                outcome="success" if ok else "failure",
                step_index=step_index,
            )
            return ok, out

        _shell = "powershell" if sys.platform == "win32" else "bash"
        tool = _delatest_scaffold_pins(tool)  # B1: hallucinated version pin → @latest
        tool = _translate_bash_env_prefix(tool, _shell)
        tool = _fix_dotless_venv_path(tool, session._cwd)
        tool = _fix_powershell_relative_path(tool)
        tool = _quote_ps_literal_args(tool)  # shell-safe arg quoting (@splat etc.)
        # Resolve $WORKSPACE_PATH token that supervisor injects into Start-Job blocks
        if "$WORKSPACE_PATH" in tool or "${WORKSPACE_PATH}" in tool:
            _ws = str(self._workspace).replace("\\", "\\\\")
            tool = tool.replace("$WORKSPACE_PATH", _ws).replace("${WORKSPACE_PATH}", _ws)
        # The project has no name of its own: it IS the workspace. Planners kept inventing one
        # (`vite create $PROJECT_NAME`, `New-Item -ItemType Directory react-ts-app`) and leaving
        # `vars.PROJECT_NAME` empty, so the placeholder guard refused the command BEFORE the
        # shell could report that `vite` does not exist — and grounding, which fires on that
        # report, never ran. A deadlock built out of two correct guards. The runtime knows the
        # answer, so it supplies it, and initializers that insist on naming their directory are
        # hoisted afterwards by `workspace_shape`.
        if "$PROJECT_NAME" in tool or "${PROJECT_NAME}" in tool:
            _pn = self._workspace.name
            tool = tool.replace("$PROJECT_NAME", _pn).replace("${PROJECT_NAME}", _pn)
        effective_cwd = resolve_cwd(tool, goal, str(self._workspace))
        session._cwd = Path(effective_cwd)
        console.print(f"  [dim]batch cwd:[/] {effective_cwd}")

        # ── Workspace stash: scaffold tools refuse non-empty directories ──
        # (inserted above)
        # If this is a scaffold/init command AND the target directory has loose
        # files, stash them first so the tool sees a clean workspace.
        # Invariant: never stashes if a project manifest already exists (the
        # project is already initialized — stashing would destroy it).
        _stash: _WorkspaceStash | None = None
        if _is_scaffold_init(tool):
            _stash = _WorkspaceStash(Path(effective_cwd))
            _did_stash, _stash_msg = _stash.stash()
            if _did_stash:
                console.print(f"  [dim]workspace stash:[/] {_stash_msg}")

        out, rc = session.run(tool)

        # ── Patch 5: semantic success for delete-on-missing ────────────────
        # A remove/delete command that fails with "cannot find path" or
        # "no such file" is semantically successful — the target is already
        # absent, which is the desired post-condition.
        # Invariant: applies to any shell's delete verb, not just PowerShell.
        if rc != 0 and out:
            _out_lc = out.lower()
            _is_delete_cmd = any(
                kw in tool.lower()
                for kw in ("remove-item", "rm ", "del ", "rmdir", "rd ", "unlink")
            )
            _is_missing = any(
                sig in _out_lc
                for sig in (
                    "cannot find path",
                    "no such file",
                    "does not exist",
                    "path not found",
                    "file_not_found",
                    "itemnotfound",
                )
            )
            if _is_delete_cmd and _is_missing:
                console.print(
                    "  [dim]delete-on-missing: treating as success (target already absent)[/]"
                )
                rc = 0

        # ── Scaffold name-invalid recovery (deterministic, error-driven) ──
        # A scaffolder that derives the project name from the target dir
        # (create-next-app ., npm init, cargo init .) fails when the dir name
        # breaks the ecosystem's naming rules — e.g. workspace "_try": the
        # command is PERFECT, npm just refuses a name starting with "_". A human
        # reruns with a valid name; do it deterministically: scaffold into a
        # valid-named subdir, then flatten to root. Framework-neutral: keys on
        # the observed error + the "." target, never on tool/OS names.
        if (
            rc != 0
            and _is_scaffold_init(tool)
            and _is_name_invalid_error(out)
            and re.search(r"(^|\s)\.(\s|$)", tool)
        ):
            _base = Path(effective_cwd).name
            _safe = _sanitize_project_name(_base)
            _retry = _rewrite_scaffold_target(tool, _safe)
            console.print(
                f"  [yellow]↻ scaffold name-invalid:[/] dir '{_base}' rejected by the "
                f"scaffolder — retrying into ./{_safe}/ then flattening to root"
            )
            _out2, _rc2 = session.run(_retry)
            if _rc2 == 0:
                _fok, _fmsg = _move_subdir_to_root(Path(effective_cwd))
                console.print(f"  [dim]{'✓' if _fok else '✗'} flatten:[/] {_fmsg}")
                if _fok:
                    out, rc = _out2, 0
                else:
                    out, rc = f"scaffolded into {_safe}/ but flatten failed: {_fmsg}", 1
            else:
                out = _out2  # surface the new (real) error, not the naming one

        # Restore stash after scaffold completes (success or failure)
        if _stash is not None:
            _rok, _rmsg = _stash.restore()
            if _rok and "0 item" not in _rmsg:
                console.print(f"  [dim]workspace restore:[/] {_rmsg}")
            _cleaned = _cleanup_flag_named_artifacts(Path(effective_cwd))
            if _cleaned:
                console.print(f"  [dim]cleaned flag-named artifact(s):[/] {', '.join(_cleaned)}")
        console.print(f"  [dim]exit {rc}:[/] {out[:120]}")
        memory.save_event(
            goal=goal,
            cwd=effective_cwd,
            command=tool,
            stdout=out[:256],
            exit_code=rc,
            outcome="success" if rc == 0 else "failure",
            step_index=step_index,
        )
        return rc == 0, out

    def _is_workspace_clear_intent(self, tool: str) -> bool:
        """True if the launcher is trying to clear/delete the workspace contents.
        Returns False if workspace already has any recognized project file.
        Never destroy live work regardless of project type.
        """
        # Never clear if there's already a project of any kind in the workspace
        project_indicators = [
            "package.json",  # JS/TS/Bun
            "Cargo.toml",  # Rust
            "pyproject.toml",  # Python
            "setup.py",  # Python legacy
            "angular.json",  # Angular
            "go.mod",  # Go
        ]
        if any((self._workspace / f).exists() for f in project_indicators):
            return False

        lc = tool.lower().strip()
        ws = str(self._workspace).lower().replace("\\", "/")
        delete_kws = ("rm ", "del ", "rd ", "rmdir ", "cmd")
        if not any(lc.startswith(k) for k in delete_kws):
            return False
        norm = lc.replace("\\", "/")
        return ws in norm or ws.rstrip("/") + "/*" in norm

    # ── Native fileops execution ─────────────────────────────────────────────

    def _run_fileops(
        self, tool: str, session, goal: str, step_index: int, sysstate=None
    ) -> tuple[bool, str]:
        """
        Execute a native fileops call without going through the shell.
        Format: write_file|path|content  or  read_file|path  etc.
        The supervisor emits these; the executor never touches the shell for file ops.
        Supports compound write_file: write_file|f1|'c1', write_file|f2|'c2'
        """
        # Handle compound write_file: write_file|f1|'c1', write_file|f2|'c2'
        compound = _split_compound_write_file(tool)
        if compound:
            all_ok = True
            msgs = []
            for path, content in compound:
                console.print(f"  [dim]fileop:[/] write_file({path!r}, {content[:40]!r})")
                ok, out = fileops_dispatch("write_file", [path, content], session._cwd)
                console.print(f"  [dim]{'✓' if ok else '✗'}[/] {out[:120]}")
                memory.save_event(
                    goal=goal,
                    cwd=str(session._cwd),
                    command="FILEOP:write_file",
                    stdout=out[:300],
                    exit_code=0 if ok else 1,
                    outcome="success" if ok else "failure",
                    step_index=step_index,
                )
                msgs.append(out)
                if not ok:
                    all_ok = False
            return all_ok, "; ".join(msgs)

        parts = tool.split("|", 2)
        name = parts[0].strip()
        args = [p for p in parts[1:]]

        # Unescape \n → newline and \t → tab in file content.
        # The model encodes newlines as literal \n sequences in the pipe-separated
        # tool string. Without this, files get written with literal backslash-n.
        if name in ("write_file", "append_file") and len(args) >= 2:
            args[1] = args[1].replace("\\n", "\n").replace("\\t", "\t")

        # ── Safety: block overwriting a known executable with text content ──
        # This is the "delete → overwrite" bug: locate finds C:\yt-dlp\yt-dlp.exe
        # (registered as EXECUTABLE/DISCOVERED), then a recovery step writes
        # placeholder text into that same path instead of deleting + reinstalling.
        if name in ("write_file", "append_file") and len(args) >= 1 and sysstate is not None:
            _safe, _safe_reason = sysstate.assert_safe_overwrite(args[0])
            if not _safe:
                console.print(f"  [bold red]✗[/] {_safe_reason}")
                memory.save_event(
                    goal=goal,
                    cwd=str(session._cwd),
                    command="FILEOP:write_file:SAFETY_BLOCK",
                    stdout=_safe_reason,
                    exit_code=1,
                    outcome="failure",
                    step_index=step_index,
                )
                return False, _safe_reason

        # FASE 6: block unrendered template placeholders before they hit disk.
        if name in ("write_file", "append_file") and len(args) >= 2:
            leaks = TemplateLeakDetector.scan(args[1])
            if leaks:
                # First, try to fill the slots deterministically from discovered
                # facts (the discover→act loop must not depend on the model
                # re-substituting values it already found).
                if sysstate is not None and sysstate.facts:
                    fact_values = [f.value for f in sysstate.facts.values()]
                    resolved, unresolved = TemplateLeakDetector.resolve(args[1], fact_values)
                    if not unresolved:
                        console.print(f"  [dim]resolved {len(leaks)} placeholder(s) from facts[/]")
                        args[1] = resolved
                        leaks = []
                if leaks:
                    msg = TemplateLeakDetector.reason(args[1])
                    console.print(f"  [bold red]✗[/] {msg}")
                    memory.save_event(
                        goal=goal,
                        cwd=str(session._cwd),
                        command="FILEOP:write_file:TEMPLATE_LEAK",
                        stdout=args[1][:200],
                        exit_code=1,
                        outcome="failure",
                        step_index=step_index,
                    )
                    return False, msg

        console.print(f"  [dim]fileop:[/] {name}({', '.join(repr(a[:40]) for a in args)})")
        ok, out = fileops_dispatch(name, args, session._cwd)
        console.print(f"  [dim]{'✓' if ok else '✗'}[/] {out[:120]}")
        memory.save_event(
            goal=goal,
            cwd=str(session._cwd),
            command=f"FILEOP:{name}",
            stdout=out[:300],
            exit_code=0 if ok else 1,
            outcome="success" if ok else "failure",
            step_index=step_index,
        )

        # ── Entity tracking: register discovered executables in world model ──
        # locate|tool returns: "name -> /path/to/tool\ndirectory: /path/to"
        # We register the found path as EXECUTABLE/DISCOVERED so that any
        # subsequent write_file to that exact path triggers the safety block.
        if name == "locate" and ok and sysstate is not None and args:
            import re as _re

            _m = _re.search(r"\S+\s+->\s+(.+)", out)
            if _m:
                _exe_path = _m.group(1).strip().splitlines()[0].strip()
                if _exe_path:
                    _tool_name = args[0].strip() if args else ""
                    # One ingestion point: world-graph node (identity + aliases)
                    # + the canonical facts later $VAR resolution reads.
                    sysstate.observe_executable(
                        _tool_name, _exe_path, provenance=f"locate:{_tool_name}"
                    )
                    console.print(
                        f"  [dim]entity registered:[/] {_exe_path} (EXECUTABLE/DISCOVERED)"
                    )

        return ok, out

    # ── Interactive PTY execution ────────────────────────────────────────────

    def _run_interactive(
        self,
        tool,
        goal,
        current_step,
        step_success,
        constraints,
        session,
        terminal,
        step_index,
    ) -> tuple[bool, str]:
        from . import model_router as _mr_pty
        from .terminal_runtime import TerminalSession

        effective_cwd = resolve_cwd(tool, goal, str(self._workspace))
        terminal.run_command(f"cd '{effective_cwd}'")
        console.print(f"  [dim]cwd:[/] {effective_cwd}")

        # ── Workspace stash for interactive scaffold tools ──
        _stash_pty: _WorkspaceStash | None = None
        if _is_scaffold_init(tool):
            _stash_pty = _WorkspaceStash(Path(effective_cwd))
            _did_stash_pty, _stash_msg_pty = _stash_pty.stash()
            if _did_stash_pty:
                console.print(f"  [dim]workspace stash (pty):[/] {_stash_msg_pty}")

        # The PTY is an execution owner like any other: a refused command must abort the
        # step, not be typed anyway. `launch` returns the violation instead of raising, so
        # the failure is observable by the same path as any other failed step.
        _violation = terminal.launch(tool)
        if _violation is not None:
            console.print(f"  [bold red]⊘ CONFINEMENT (pty):[/] {_violation}")
            return False, f"CONFINEMENT: refused — {_violation}"

        # ── LLM fallback function ───────────────────────────────────────────
        def _llm_fn(objective: str, constraints_str: str, transcript: str) -> str:
            ctx = {
                "objective": objective,
                "constraints": constraints_str,
                "transcript": transcript[-1500:],
            }
            return _mr_pty.executor_pty_fallback_call(ctx)

        # ── Wire terminal I/O ───────────────────────────────────────────────
        # read_fn: pops new raw PTY bytes (delta mode) for pyte VirtualScreen
        def _read_fn() -> bytes:
            return terminal.pop_raw()

        ts = TerminalSession(
            write_fn=terminal.write,
            read_fn=_read_fn,
            llm_fn=_llm_fn,
            log_fn=lambda msg: console.print(msg),
        )

        success, transcript = ts.run(current_step, constraints, goal)

        # Restore stash after interactive scaffold completes
        if _stash_pty is not None:
            _rok_pty, _rmsg_pty = _stash_pty.restore()
            if _rok_pty and "0 item" not in _rmsg_pty:
                console.print(f"  [dim]workspace restore (pty):[/] {_rmsg_pty}")
            _cleaned_pty = _cleanup_flag_named_artifacts(Path(effective_cwd))
            if _cleaned_pty:
                console.print(
                    f"  [dim]cleaned flag-named artifact(s) (pty):[/] {', '.join(_cleaned_pty)}"
                )

        if success:
            memory.save_event(
                goal=goal,
                cwd=str(session._cwd),
                command=f"PTY_DONE:{tool}",
                stdout=transcript[-300:],
                exit_code=0,
                outcome="success",
                step_index=step_index,
            )
        return success, transcript

    # ── Fix suggestion via executor (fast 1.7B) ──────────────────────────────

    def _author_and_write_content(
        self, goal, step, target, step_success, session, sysstate, step_index
    ) -> bool:
        """Ask the coder for the file's CONTENT (not a shell command) and write it natively.

        Seed-42 control: the same 3B, asked for "one shell command" to create server.js, emits
        an empty `New-Item -ItemType File`; asked for the file CONTENT it emits a correct
        Node.js server. The framing was the bottleneck, not the model. Returns True only when
        the write satisfies the step's file_has_content; False → the caller falls back to the
        shell path, so this never regresses below baseline.
        """
        from .tools.fileops import write_file

        system_spec = ""
        if sysstate is not None:
            _sf = sysstate.facts.get("system_spec")
            if _sf:
                system_spec = _sf.value
        ctx = {
            "path": target,
            "objective": step,
            "research_notes": _research_notes(sysstate),
            "system_spec": system_spec,
        }
        try:
            content = model_router.content_call(ctx)
        except Exception as exc:
            console.print(f"  [dim]content authoring unavailable ({exc}) — shell path[/]")
            return False
        if not content.strip():
            return False
        ok, msg = write_file(target, content, session._cwd)
        console.print(
            f"  [dim]authored file content:[/] {len(content)}B → {target} "
            f"({'ok' if ok else msg[:60]})"
        )
        if not ok:
            return False
        art_ok, art_reason = _artifact_check(
            f"write_file|{target}", step, str(session._cwd), step_success=step_success
        )
        memory.save_event(
            goal=goal,
            cwd=str(session._cwd),
            command=f"CONTENT_WRITE:{target}",
            stdout=msg[:200],
            exit_code=0 if art_ok else 1,
            outcome="success" if art_ok else "failure",
            step_index=step_index,
        )
        if art_ok:
            console.print("[green]✓[/] Step complete")
        else:
            console.print(f"  [yellow]⚠ authored content did not satisfy criteria:[/] {art_reason}")
        return art_ok

    def _author_command(
        self,
        goal,
        step,
        tool_hint,
        stderr,
        checkpoint,
        session,
        sysstate=None,
        tried_commands: list[str] | None = None,
        research_notes: str = "",
        ocke=None,
    ) -> str:
        """Executor coder AUTHORS or CORRECTS the concrete shell command (executor.jinja).

        - Authoring (stderr=""): produce the command for this step from the
          objective + planner hint + RESEARCH NOTES gathered by prior DISCOVERY
          steps. This closes the DISCOVERY→ACTION channel — the command is written
          AFTER the research exists, not frozen before it.
        - Correcting (stderr=<error>): rewrite the failed command from the real error.

        Deterministic shell-grammar hints + research + system_spec are injected so
        the model reasons less (runtime-first). Returns "" if nothing usable, so the
        caller keeps its own command → never worse than the frozen-launcher baseline.
        """
        _env = sysstate.environment if sysstate else None
        shell = _env.shell if _env else ("powershell" if sys.platform == "win32" else "bash")
        os_name = _env.os_name if _env else ("Windows" if sys.platform == "win32" else "Linux")

        grammar_hint = ""
        if shell in ("powershell", "pwsh"):
            from .error_classifier import powershell_grammar_issues

            _issues = powershell_grammar_issues(tool_hint)
            if _issues:
                grammar_hint = "\n".join(f"- {i}" for i in _issues)

        facts = ""
        system_spec = ""
        task_brief = ""
        if sysstate is not None:
            _f = sysstate.facts_summary()
            if _f and "no facts" not in _f:
                facts = _f
            _sf = sysstate.facts.get("system_spec")
            if _sf:
                system_spec = _sf.value
            # SPECIALIST_BRIEF: same one-time framing the supervisor plans
            # with — the coder authors commands as the same specialist, not
            # as a generalist reasoning over the raw objective alone.
            _tb = sysstate.facts.get("task_brief")
            if _tb:
                task_brief = _tb.value

        ctx = {
            "os_name": os_name,
            "shell": shell,
            "workspace": str(session.workspace),
            "system_spec": system_spec,
            "task_brief": task_brief,
            "objective": step,
            "checkpoint": "\n".join(f"- {c}" for c in (checkpoint or [])),
            "command": tool_hint,
            "stderr": (stderr or "")[:600],
            "grammar_hint": grammar_hint,
            "research_notes": research_notes or "",
            "tried_commands": tried_commands or [],
            "facts": facts,
        }
        # Obsolescence defence, owned by the runtime rather than by a prompt. If the shell
        # says the leading executable does not exist, the model invented it — its memory of
        # this ecosystem's CLI is older than the ecosystem. Look the invocation up on the web
        # once per tool, feed the answer back, and only then let the coder re-author.
        # Without this, the observed recovery was `npm install -g <tool>` twice, both EPERM.
        _tool = grounding.should_ground(stderr or "", tool_hint or "", sysstate)
        if _tool:
            _found, _text = grounding.ground_tool(sysstate, _tool, cwd=session.workspace)
            if _found:
                console.print(
                    f"  [dim]grounding:[/] '{_tool}' is not resolvable — searched the "
                    f"web for its current invocation"
                )
                trace.emit("grounding", tool=_tool, chars=len(_text))
                _prior = ctx.get("research_notes") or ""
                ctx["research_notes"] = f"{_text[:1200]}\n{_prior}"[:1800]

        authored = model_router.executor_call(ctx)

        # Step-level speculation: the coder PROPOSES, the runtime ACCEPTS or REJECTS for
        # free. Six deterministic gates below, no model involved. Each rejection is traced
        # so the accept rate per gate is a measurement rather than a guess — before this,
        # only 18% of the coder's commands could be shown to reach the shell verbatim, and
        # nothing distinguished "rejected" from "rewritten by design" (fileops interception).
        def _reject(gate: str) -> str:
            trace.emit(
                "coder_gate",
                verdict="rejected",
                gate=gate,
                command=str(authored)[:200],
                hint=str(tool_hint)[:120],
            )
            return ""

        if not (authored and authored != tool_hint and _looks_like_command(authored)):
            return _reject("not_a_command_or_echoes_hint")
        authored = normalize_launcher(authored, step)
        # Scope guard (speed + correctness): the executor may NOT inflate a narrow
        # step into project creation. If the authored command is a scaffold/init
        # but the planner's HINT was not, the coder turned e.g. "install deps" or
        # "verify X" into "re-create the whole project" (observed: Angular
        # re-scaffolded 3× across steps → 13 min). Reject → keep the hint. A step
        # whose hint IS already a scaffold is allowed to stay one.
        if _is_scaffold_init(authored) and not _is_scaffold_init(tool_hint):
            return _reject("scope_inflation_to_scaffold")
        # C1: no unresolved placeholder may reach the shell. An authored command
        # still carrying <ANGLE_TOKEN> or a bare $UPPER_VAR the runtime won't
        # substitute (only $WORKSPACE_PATH is) is a leak → reject, keep the hint.
        if _has_unresolved_placeholder(authored):
            return _reject("unresolved_placeholder")
        # C3: reject an authored command with unbalanced quotes/braces/parens —
        # it will only produce a shell parse error ("Missing closing '}'").
        if not _is_shell_balanced(authored):
            return _reject("unbalanced_shell_syntax")
        if self_truncating_redirect(authored):
            return _reject("self_truncating_redirect")
        # Path-safety guard: reject a hand-typed absolute path into this project's own
        # tree that doesn't match the REAL workspace — a small model can hallucinate
        # a plausible sibling path even with the real one in context. Caller keeps
        # its own command on rejection (never worse than the frozen-hint baseline).
        if _has_fabricated_workspace_path(authored, self._workspace):
            return _reject("fabricated_workspace_path")
        # OCKE guard: an authored command must still comply with the platform
        # (no forbidden/cross-OS tool). If it doesn't, reject → caller keeps its
        # command. Single owner of platform validity, reused (not duplicated).
        if ocke is not None:
            try:
                _vr = ocke.validate_command(authored)
                if not _vr.ok:
                    return _reject("ocke_platform_violation")
            except Exception:
                pass
        trace.emit("coder_gate", verdict="accepted", gate="", command=authored[:200])
        return authored

    def _get_fix(
        self,
        goal,
        step,
        tool,
        failures,
        session,
        sysstate=None,
        tried_commands: list[str] | None = None,
    ) -> str:
        """Ask executor (1.7B) for a corrected batch command to try next.

        The executor handles single-step command correction; the supervisor
        is reserved for full plan recovery when all retries are exhausted.
        """
        _env = sysstate.environment if sysstate else None
        constraints = []
        if sysstate is not None:
            facts = sysstate.facts_summary()
            if facts and "no facts" not in facts:
                constraints.append(facts)

        ctx = {
            "os_name": (
                _env.os_name if _env else ("Windows" if sys.platform == "win32" else "Linux")
            ),
            "shell": (
                _env.shell if _env else ("powershell" if sys.platform == "win32" else "bash")
            ),
            "workspace": str(session.workspace),
            "objective": step,
            "constraints": constraints,
            "command": tool,
            "failure": "\n".join(failures[-3:])[:400],
            "tried_commands": tried_commands or [],
        }
        fix = model_router.executor_fix_call(ctx)
        if fix and fix != tool and _looks_like_command(fix):
            fix = normalize_launcher(fix, step)
            if _has_fabricated_workspace_path(fix, self._workspace):
                return ""
            return fix
        return ""

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _snap(self, session: Session) -> str:
        """
        Build a terminal snapshot for supervisor/reflection context.
        Includes both main step executions and FIX_ATTEMPT records so the
        supervisor can see the full retry history and avoid repeating failed approaches.
        """
        events = memory.get_recent_events(8)
        lines = [f"cwd: {session._cwd}", "RETRY HISTORY (most recent first):"]
        for ev in reversed(events):
            cmd = ev.get("command", "")
            outcome = ev.get("outcome", "")
            stdout = ev.get("stdout", "")
            if cmd.startswith("FIX_ATTEMPT:"):
                actual_cmd = cmd[len("FIX_ATTEMPT:") :]
                lines.append(f"  [executor suggested fix] {actual_cmd[:80]}")
            elif cmd.startswith(("DONE:", "FILEOP:", "FILEOP_NEWITEM:", "CHECK_FAIL:")):
                tag, _, rest = cmd.partition(":")
                lines.append(f"  [{tag}] {rest[:60]} → {outcome}")
            else:
                lines.append(f"  {cmd[:60]} → {outcome}")
                if stdout and stdout.strip():
                    lines.append(f"    error: {stdout.strip()[:200]}")
        return "\n".join(lines)

    @staticmethod
    def _workspace_snapshot(workspace: Path) -> str:
        """
        Generate a concise visual snapshot of the workspace filesystem state.
        This is shown to the supervisor BEFORE planning so it doesn't make
        assumptions about what already exists or needs to be created.

        Format mirrors what a human would see running `ls -la` + file previews.
        Kept short: max 60 entries, max 200 chars per file content preview.
        """
        lines = ["WORKSPACE SNAPSHOT (current state before planning):"]
        lines.append(f"  path: {workspace}")

        if not workspace.exists():
            lines.append("  [workspace does not exist]")
            return "\n".join(lines)

        # Collect top-level entries
        try:
            entries = sorted(workspace.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            lines.append("  [permission error reading workspace]")
            return "\n".join(lines)

        if not entries:
            lines.append("  [empty workspace]")
            return "\n".join(lines)

        # Key project files to preview content for
        _PREVIEW_FILES = {
            "package.json",
            "package-lock.json",
            "tsconfig.json",
            "next.config.ts",
            "next.config.js",
            "tailwind.config.ts",
            "tailwind.config.js",
            "postcss.config.mjs",
            "postcss.config.js",
            "components.json",
            "pyproject.toml",
            "Cargo.toml",
            "go.mod",
        }

        dirs = []
        files = []
        for entry in entries[:60]:
            if entry.name.startswith(".") and entry.name in (".git",):
                continue  # skip .git noise
            if entry.is_dir():
                # Count immediate children for dirs
                try:
                    n = sum(1 for _ in entry.iterdir())
                except Exception:
                    n = "?"
                dirs.append(f"  dir   {entry.name}/  ({n} items)")
            else:
                size = entry.stat().st_size if entry.exists() else 0
                files.append(f"  file  {entry.name}  ({size}B)")

        lines.extend(dirs)
        lines.extend(files)

        # Preview key files
        previews = []
        for fname in _PREVIEW_FILES:
            fpath = workspace / fname
            if fpath.exists():
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    preview = content.strip()[:200].replace("\n", " ")
                    previews.append(f"  [{fname}] {preview}")
                except Exception:
                    pass

        if previews:
            lines.append("KEY FILE CONTENTS:")
            lines.extend(previews)

        # Check for specific markers relevant to the most common goals
        markers = []
        if (workspace / "package.json").exists():
            markers.append("has package.json (Node project)")
        if (workspace / "node_modules").exists():
            markers.append("node_modules present (deps installed)")
        if (workspace / "components.json").exists():
            markers.append("components.json present (shadcn initialized)")
        if (workspace / "components" / "ui").exists():
            ui_count = sum(1 for _ in (workspace / "components" / "ui").iterdir())
            markers.append(f"components/ui/ present ({ui_count} files)")
        if (workspace / "app").exists():
            markers.append("app/ directory present (Next.js App Router)")
        if (workspace / ".next").exists():
            markers.append(".next/ present (built)")
        if (workspace / "venv").exists() or (workspace / ".venv").exists():
            markers.append("venv present (Python)")

        if markers:
            lines.append("PROJECT MARKERS:")
            for m in markers:
                lines.append(f"  ✓ {m}")

        return "\n".join(lines)
