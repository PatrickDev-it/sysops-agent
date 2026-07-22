"""
TemplateLeakDetector — blocks unrendered template placeholders from being
written to disk, while allowing legitimate content (HTML, XML, code, configs).

The failure it prevents: the planner emits `write_file|f.txt|<RESOLVED CONTENT>`
or content containing `<RESULT>`, `{DIAGNOSIS}`, `<FIX_COMMAND>` — placeholder
slots the model intended to fill but emitted verbatim.

Invariant, not a blacklist:
    A placeholder is an UPPERCASE/snake token inside <...> or {...} that names
    an abstract slot ("RESULT", "FIX_COMMAND", "DIAGNOSIS", "CONTENT"), OR the
    entire content reduced to a single bracketed token.

    Real content is allowed:
      - HTML/XML tags: <div>, <html>, <Project>, </main>   (lowercase or mixed,
        or known markup names)
      - Template engines a USER might legitimately write: only flagged if they
        are the SOLE content (a file that is nothing but "{{ x }}" is suspect,
        but a Jinja template body is not our concern here because the agent
        writes config/report/code, not template files, in these tasks)

We err toward NOT blocking: a false block stalls a legitimate task. We flag only
high-confidence leaks.
"""

from __future__ import annotations

import re
import re as _re

# Tokens like <RESULT>, <FIX_COMMAND>, <RESOLVED CONTENT>, <CONTENT>, <PLACEHOLDER>
# Uppercase words (optionally multi-word with spaces/underscores) inside angle
# brackets. Mixed/lowercase like <div>, <a href> are NOT matched.
_ANGLE_PLACEHOLDER = re.compile(r"<([A-Z][A-Z0-9]*(?:[ _][A-Z0-9]+)*)>")

# Tokens like {DIAGNOSIS}, {RESULT}, {FIX} — single uppercase word in braces.
_BRACE_PLACEHOLDER = re.compile(r"\{([A-Z][A-Z0-9_]{2,})\}")

# Whole-content placeholder: the content stripped is exactly one bracket token,
# regardless of case: <resolved content>, <content>, <fill this in>.
_WHOLE_ANGLE = re.compile(r"^<[A-Za-z0-9 _\-]+>$")
_WHOLE_BRACE = re.compile(r"^\{[A-Za-z0-9 _\-]+\}$")

# A shell-variable token: $var, ${var}, $(cmd), $env:NAME, %VAR% (cmd.exe).
# In a fileops write (no shell runs), these are NEVER expanded — so content made
# ONLY of these is an unexpanded-interpolation leak, the same class as <RESULT>.
_SHELL_VAR_TOKEN = re.compile(r"^(?:\$\([^)]*\)|\$\{[^}]*\}|\$[A-Za-z_][\w:.]*|%[A-Za-z_]\w*%)$")

# Common markup/code tag names that must NEVER be treated as placeholders even
# if somehow uppercase. This is a safety allow-list (not framework detection).
_MARKUP_ALLOW = {
    "HTML",
    "HEAD",
    "BODY",
    "DIV",
    "SPAN",
    "P",
    "A",
    "UL",
    "LI",
    "TABLE",
    "TR",
    "TD",
    "TH",
    "SVG",
    "PATH",
    "G",
    "BR",
    "HR",
    "IMG",
    "FORM",
    "INPUT",
    "DOCTYPE",
    "XML",
    "ROOT",
    "PROJECT",
    "CONFIGURATION",
}

# Lowercase/any-case placeholder slot: <git_directory>, <python_directory>,
# <path>, <your value here>, <resolved content>. These differ from real markup
# tags (<div>, <a href>) by having an underscore, a space, or being a known
# placeholder word. A bare single markup-like word (<div>) is NOT flagged.
_PLACEHOLDER_WORDS = {
    "path",
    "value",
    "content",
    "result",
    "name",
    "directory",
    "dir",
    "here",
    "todo",
    "fill",
    "placeholder",
    "insert",
    "output",
    "command",
    "fix",
    "diagnosis",
    "version",
    "your",
    "filename",
    "file",
    "url",
    "key",
}
# Inside of <...>: only letters/digits/space/underscore/hyphen (no /, =, ", :, .)
_SOFT_ANGLE = re.compile(r"<([A-Za-z][A-Za-z0-9 _\-]*)>")


def _is_soft_placeholder(inner: str) -> bool:
    """True if the <...> inner text looks like a fill-in slot, not a markup tag."""
    s = inner.strip()
    if "_" in s or " " in s:
        return True
    return s.lower() in _PLACEHOLDER_WORDS


_ASPECT_WORDS = {"directory", "dir", "path", "location", "folder"}


def _resolve_one(inner: str, fact_items: list) -> str:
    """
    Resolve a single placeholder's inner text against discovered facts.
    fact_items: list of (key, value) pairs.
    """
    norm_inner = re.sub(r"[ \-]+", "_", inner.strip().lower())
    words = [w for w in re.split(r"[ _\-]+", inner.lower()) if w]
    if not words:
        return ""
    wants_dir = any(w in ("directory", "dir", "folder", "location") for w in words)
    entity_words = [w for w in words if w not in _ASPECT_WORDS]

    # 1) Direct fact-key match (e.g. <home_directory> → fact key "home_directory",
    #    <os_name> → "os_name"). Exact, then containment either direction.
    for key, val in fact_items:
        if not key:
            continue
        nk = key.strip().lower()
        if nk == norm_inner or norm_inner in nk or nk in norm_inner:
            v = val.strip()
            # if the value is the locate format, extract the right part
            if wants_dir:
                m = re.search(r"directory:\s*(.+)", v)
                if m:
                    return m.group(1).strip()
            return v.splitlines()[0].strip() if "\n" in v else v

    # 2) Entity mentioned inside a fact value (locate format facts)
    for key, val in fact_items:
        low = val.lower()
        if entity_words and not any(ew in low for ew in entity_words):
            continue
        if wants_dir:
            m = re.search(r"directory:\s*(.+)", val)
            if m:
                return m.group(1).strip()
        m = re.search(r"->\s*(.+)", val)
        if m:
            return m.group(1).strip()
        if "\n" not in val.strip():
            return val.strip()
    return ""


class TemplateLeakDetector:
    @staticmethod
    def scan(content: str) -> list[str]:
        """
        Return the list of leaked placeholder tokens found in `content`.
        Empty list = clean.
        """
        if content is None:
            return []
        stripped = content.strip()
        leaks: list[str] = []

        # 1) Whole-content is a single bracketed slot → definite leak
        if _WHOLE_ANGLE.match(stripped) or _WHOLE_BRACE.match(stripped):
            leaks.append(stripped)
            return leaks

        # 1b) Content is a single command-substitution / brace expansion that
        # may contain spaces: $(...) or ${...}. fileops never runs a shell.
        if re.fullmatch(r"\$\([^)]*\)", stripped) or re.fullmatch(r"\$\{[^}]*\}", stripped):
            leaks.append(stripped)
            return leaks

        # 1c) Any STANDALONE unexpanded shell variable is a leak. fileops writes
        # content literally — a bare "$git_path" or "$os" token is never intended
        # literal text; the model expected shell interpolation that never happens.
        # Legit cases survive: "API_KEY=$SECRET" (token has a prefix), "$5"
        # (not an identifier), "PATH=$PATH:/x" (token has a prefix) — none of these
        # are a STANDALONE pure variable token.
        tokens = [t for t in re.split(r"[\s|;,]+", stripped) if t]
        var_tokens = [t for t in tokens if _SHELL_VAR_TOKEN.match(t)]
        if var_tokens:
            leaks.extend(var_tokens)

        # 2) Embedded UPPERCASE angle placeholders
        for m in _ANGLE_PLACEHOLDER.finditer(content):
            token = m.group(1)
            if token in _MARKUP_ALLOW:
                continue
            leaks.append(m.group(0))

        # 3) Embedded UPPERCASE brace placeholders
        for m in _BRACE_PLACEHOLDER.finditer(content):
            token = m.group(1)
            if token in _MARKUP_ALLOW:
                continue
            leaks.append(m.group(0))

        # 4) Soft (any-case) angle placeholders: <git_directory>, <path>,
        # <your value here>. Markup tags (<div>, <a href>) are NOT flagged.
        for m in _SOFT_ANGLE.finditer(content):
            if m.group(0) in leaks:
                continue
            if _is_soft_placeholder(m.group(1)):
                leaks.append(m.group(0))

        # Deduplicate, keep order
        seen = set()
        unique = []
        for t in leaks:
            if t not in seen:
                seen.add(t)
                unique.append(t)
        return unique

    @staticmethod
    def is_clean(content: str) -> bool:
        return not TemplateLeakDetector.scan(content)

    @staticmethod
    def resolve(content: str, facts) -> tuple[str, list[str]]:
        """
        Deterministically fill placeholder slots from discovered facts, so the
        discover→act loop does not depend on the model re-substituting values.

        `facts` may be a list of fact value strings, or a dict {key: value}.
        A placeholder <entity_aspect> (e.g. <git_directory>, <home_directory>) is
        resolved by: (1) a direct fact-key match, then (2) matching the entity
        inside a fact value (locate format: "tool -> path\ndirectory: dir").
        Returns (resolved_content, list_of_unresolved_tokens).

        General mechanism — no tool or framework names are hard-coded.
        """
        if isinstance(facts, dict):
            fact_items = list(facts.items())
        else:
            fact_items = [("", v) for v in facts]

        tokens = TemplateLeakDetector.scan(content)
        if not tokens:
            return content, []
        resolved = content
        unresolved: list[str] = []
        for tok in tokens:
            inner = tok.strip("<>{}").strip()
            value = _resolve_one(inner, fact_items)
            if value:
                resolved = resolved.replace(tok, value)
            else:
                unresolved.append(tok)
        return resolved, unresolved

    @staticmethod
    def reason(content: str) -> str:
        leaks = TemplateLeakDetector.scan(content)
        if not leaks:
            return ""
        return (
            f"template placeholders not filled in: {', '.join(leaks[:5])} — "
            "the content must contain the actual literal text, not slot markers"
        )


# ── Placeholder leak in a COMMAND (invariant #2) ─────────────────────────────
# This predicate lived in `orchestrator` and was wired only into `_author_command`, so it
# guarded the coder's output and not the planner's launcher. Measured on T35: the planner
# emitted `& "$DISCOVERED_PATH" --version` and the shell ran it verbatim, four times.
# A guard that exists, is correct, and is not wired to the path that needs it is the same
# failure as no guard at all — the third instance of that pattern found in this tree.
#
# It now lives with the other template-leak logic, and `session.run` consults it at the
# single point where a command becomes a process.

_UNRESOLVED_ANGLE_RE = _re.compile(r"<[A-Za-z][A-Za-z0-9_]*>")
# A $VAR the runtime does NOT substitute. `$WORKSPACE_PATH` is resolved upstream; anything
# else in SCREAMING_CASE reaching the shell is an unresolved slot, not a shell variable.
# Lowercase and `$env:`-prefixed names are real PowerShell variables and are left alone.
# `$WORKSPACE_PATH` and `$PROJECT_NAME` are substituted by the runtime before execution.
# Everything else in SCREAMING_CASE that reaches the shell is an unresolved slot.
# `{2,}` used to demand three characters, so `$P` and `$D` sailed through — and those are
# exactly the names `supervisor.jinja` teaches by example (`"vars":{"P":"..."}`). PowerShell
# expanded them to the empty string, the command failed for a reason nobody had written down,
# and `grounding` then blamed the wrong executable. One character is enough to be a slot.
# Names the SHELL defines. A sysops agent runs on POSIX too, where `$HOME`, `$PATH` and
# `$USER` are real variables and refusing them blocks legitimate commands. Over-blocking is
# not the safe direction: a guard that stops the agent making progress gets loosened by
# whoever is on call, and then it stops guarding anything.
_SHELL_DEFINED = (
    "HOME",
    "PATH",
    "PWD",
    "OLDPWD",
    "USER",
    "USERNAME",
    "SHELL",
    "TMPDIR",
    "TEMP",
    "TMP",
    "HOSTNAME",
    "LANG",
    "LC_ALL",
    "TERM",
    "EDITOR",
    "PAGER",
    "SHLVL",
    "RANDOM",
    "PSScriptRoot",
    "PSVersionTable",
    "LASTEXITCODE",
    "PROFILE",
    "PID",
    "OS",
)
_RESERVED = ("WORKSPACE_PATH", "PROJECT_NAME", *_SHELL_DEFINED)
_RESERVED_ALT = "|".join(_re.escape(name) for name in _RESERVED)

_UNRESOLVED_VAR_RE = _re.compile(rf"\$(?!(?:{_RESERVED_ALT})\b)[A-Z][A-Z0-9_]*\b")

# The invariant as written in AGENTS.md names three syntaxes — `<token>`, `{SLOT}`, `$VAR` —
# and the implementation had NO brace pattern at all. Verified reaching the execution point:
# `{SLOT}` · `${TARGET}` · `{{ path }}` · `%USERNAME%`.
#
# `${TARGET}` is the one that costs real damage: PowerShell expands an undefined variable to
# the EMPTY STRING, so `Remove-Item -Recurse ${TARGET}` arrives at the shell as
# `Remove-Item -Recurse` operating on the current directory. `%VAR%` is expanded the same way
# by cmd.exe inside any `cmd /c` sub-invocation.
_UNRESOLVED_BRACE_RE = _re.compile(
    r"\{\{[^}]{0,120}\}\}"  # {{ jinja }}
    # `${NAME}` is checked by the alternative below, which knows the reserved names. Without
    # the lookbehind this bare-brace arm matched `{WORKSPACE_PATH}` INSIDE `${WORKSPACE_PATH}`
    # and reported a slot the runtime had already substituted.
    rf"|(?<!\$)\{{(?!(?:{_RESERVED_ALT})\}})[A-Za-z_][A-Za-z0-9_]{{0,60}}\}}"  # {SLOT}
    rf"|\$\{{(?!(?:{_RESERVED_ALT})\}})[A-Za-z_][A-Za-z0-9_]{{0,60}}\}}"  # ${TARGET}
    r"|%[A-Za-z_][A-Za-z0-9_]{0,60}%"  # %USERNAME%
)

# Angle-bracket slots may contain spaces: `<path here>` is the shape a model actually emits.
# The original `<[A-Za-z][A-Za-z0-9_]*>` required a single bare word, so the prose form —
# the more common one — passed. Bounded length so a stray `<` in a redirect cannot make this
# scan the rest of the line.
_UNRESOLVED_ANGLE_PROSE_RE = _re.compile(r"<[A-Za-z][A-Za-z0-9_ -]{0,60}>")

_PLACEHOLDER_PATTERNS = (
    _UNRESOLVED_ANGLE_RE,
    _UNRESOLVED_ANGLE_PROSE_RE,
    _UNRESOLVED_BRACE_RE,
    _UNRESOLVED_VAR_RE,
)


def unresolved_placeholder(command: str) -> str:
    """Return the offending token, or "" when the command is fully resolved."""
    text = command or ""
    for pattern in _PLACEHOLDER_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(0)
    return ""


# ── Self-truncating redirection (measured on T01/T20) ────────────────────────
# `Get-Content os_info.txt | Out-File os_info.txt` truncates the file to zero bytes: the
# shell opens the target for writing before the reader produces a byte. Both T01 and T20
# ended a run with a correct artifact replaced by 0 B, and both had been captured correctly
# a moment earlier. A small model will keep emitting this; it is a property of shells, not a
# property of a product, and the runtime can refuse it without asking anyone.

_REDIRECT_TARGET = _re.compile(
    r"(?:(?<![0-9<>])>>?(?!&)|(?:\|\s*(?:Out-File|Set-Content|Tee-Object)\s+(?:-FilePath\s+)?))"
    r"\s*(['\"]?)([^\s'\"|;&]+)\1",
    _re.IGNORECASE,
)


def self_truncating_redirect(command: str) -> str:
    """Return the offending path when a command reads a file it also redirects into."""
    cmd = command or ""
    for m in _REDIRECT_TARGET.finditer(cmd):
        target = m.group(2)
        head = cmd[: m.start()]
        # The same name appearing before the redirection means it is also an input.
        if _re.search(rf"(?<![\w.\/-]){_re.escape(target)}(?![\w.-])", head):
            return target
    return ""


# ── A step whose entire launcher creates a project directory ─────────────────
# Observed on the `react` scaffold: the plan was `New-Item -Path .\react -ItemType Directory`,
# with `dir_not_empty(react)` as its success predicate. A directory that was just created is
# empty by definition, so the step could never pass; it retried three times and the initializer
# never ran. The plan spent its whole budget building a folder.
#
# The workspace IS the project root, and the executor already runs inside it. Initializers that
# insist on naming their own directory are handled AFTER the fact by `workspace_shape`, which
# hoists the result up. Nobody needs to pre-create anything.
#
# Narrow on purpose: `mkdir src`, `mkdir tests`, `New-Item -ItemType File` and any command that
# does more than create one directory all pass. Only a launcher that is nothing but a directory
# creation is refused.

_ONLY_MKDIR = _re.compile(
    r"""^\s*(?:
          (?:mkdir|md)\s+(?:-p\s+)?['"]?[^\s'";|&]+['"]?
        | New-Item\s+(?:-Path\s+)?['"]?[^\s'";|&]+['"]?\s+-ItemType\s+Directory(?:\s+-Force)?
        | New-Item\s+-ItemType\s+Directory\s+(?:-Path\s+)?['"]?[^\s'";|&]+['"]?(?:\s+-Force)?
        )
        \s*(?:\|\s*Out-Null\s*)?[;\s]*$""",
    _re.IGNORECASE | _re.VERBOSE,
)


_BARE_ARG = _re.compile(r"""(?:^|[\s=])(?:-Path\s+)?['"]?([^\s'";|&]+)""")


def only_creates_a_directory(command: str) -> bool:
    """True when the launcher does nothing but create one directory."""
    return bool(_ONLY_MKDIR.match((command or "").strip()))


def recreates_the_workspace_dir(command: str, workspace) -> str:
    """A launcher that does nothing but create a directory named after the workspace.

    Observed on the `react` scaffold, three times in a row: `New-Item react -ItemType
    Directory` inside a workspace called `react`. The plan built an empty folder and stopped;
    the initializer never ran.

    The conjunction is what makes this safe. Refusing every bare `mkdir` would break
    `mkdir src`. Refusing every argument equal to the workspace name would break `ng new
    <name>`, `django-admin startproject <name>` and Laravel's installer — none of which accept
    "here", and all of which `workspace_shape` hoists afterwards. Only the intersection is
    always wrong: the workspace already exists, and the executor already runs inside it.
    """
    from pathlib import Path

    if not only_creates_a_directory(command):
        return ""
    root = Path(workspace).resolve()
    for tok in _BARE_ARG.findall(command or ""):
        if tok.startswith("-"):
            continue
        name = Path(tok.lstrip(".").lstrip(chr(92) + chr(47))).name
        if name.lower() == root.name.lower():
            return tok
    return ""
