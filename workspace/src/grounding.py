"""Web search as a structural defence against model obsolescence.

A model's memory of how to invoke a CLI is frozen at its training cutoff. Ecosystems move:
initializers get renamed, flags disappear, the modern way to run a one-shot tool stops being
"install it globally". The model cannot know this, and it does not know that it does not know.

Observed on a live React + Vite scaffold with the 8B planner:

    step 1  `vite create --template react-ts $P`      -> a command that has never existed
    recover `npm install -g vite`                      -> EPERM into C:\\Program Files
    recover `npm install -g vite`                      -> EPERM again

`supervisor.jinja` already instructs the planner to `web_search` whenever it is unsure of the
current method. It did not. This project has now learned the same lesson three times: a rule
that lives only in a prompt is a suggestion. A rule that lives in the runtime is a rule.

So the runtime enforces it, deterministically and without naming any product:

    A command whose leading executable cannot be resolved is a GUESS, not a plan.
    Before anything is installed, the current invocation is looked up on the web,
    and the answer is fed back to the author of the command.

Nothing here knows what `vite`, `npm` or `npx` are. It knows that a name which the operating
system cannot resolve is a name the model invented, and that the web — not the weights — is
where the current answer lives. Each tool is grounded at most once per run.
"""

from __future__ import annotations

import re
import shutil

from .tools.web_search import search

# A launcher's leading executable: skip env assignments and the shell's own call operators.
_LEAD = re.compile(r"^\s*(?:&\s*)?(?:[\"']?)([A-Za-z][\w.+-]*)")

# Shell builtins and control words are resolvable by definition; they are never a guess.
_NEVER_A_TOOL = {
    "cd",
    "set",
    "echo",
    "exit",
    "if",
    "for",
    "while",
    "do",
    "then",
    "else",
    "fi",
    "export",
    "source",
    "test",
    "true",
    "false",
    "read",
    "printf",
    "eval",
    "exec",
}


def leading_executable(command: str) -> str:
    """The name the operating system would have to resolve to run this command."""
    m = _LEAD.match(command or "")
    if not m:
        return ""
    name = m.group(1)
    return "" if name.lower() in _NEVER_A_TOOL else name


def _fact_key(tool: str) -> str:
    return f"grounding:{tool.lower()}"


def already_grounded(sysstate, tool: str) -> bool:
    return bool(sysstate) and _fact_key(tool) in getattr(sysstate, "facts", {})


def ground_tool(sysstate, tool: str, cwd=None) -> tuple[bool, str]:
    """Look up the CURRENT way to invoke `tool`, once per run, and record it as a fact.

    The query is deliberately short and free of quotes, versions, OS names and years — the
    same shape `supervisor.jinja` prescribes, because a narrow query returns a stale page.
    """
    if not tool or already_grounded(sysstate, tool):
        return False, ""
    ok, text = search(f"{tool} latest cli usage", cwd=cwd)
    if not ok or not text.strip():
        return False, ""
    if sysstate is not None:
        sysstate.add_fact(_fact_key(tool), text[:1500], source="grounding:missing_tool")
    return True, text


# A tool that EXISTS but rejects the invocation. The model's memory of this CLI is older than
# the CLI: a subcommand was renamed, a flag was dropped, the initializer moved. Universal shell
# and CLI vocabulary — no tool is named here.
_STALE_INVOCATION = re.compile(
    r"unknown (?:option|command|argument|flag|switch)"
    r"|unrecognized (?:option|command|argument)"
    r"|is not a[n]? .{0,20}(?:command|subcommand)"
    r"|invalid (?:option|command|argument|choice)"
    r"|no such (?:command|subcommand)"
    r"|did you mean",
    re.IGNORECASE,
)


# Every shell names the thing it could not find, and each names it the same way every time.
_NAMED_IN_ERROR = (
    re.compile(r"[Tt]he term ['\"]([^'\"]+)['\"] is not recognized"),  # PowerShell
    # bash/sh prefix the shell's own name: `bash: ng: command not found`.
    re.compile(r"(?:^|:\s*)([\w.+-]+)\s*:\s*command not found", re.MULTILINE),
    re.compile(r"['\"]?([\w.+-]+)['\"]? is not recognized as an internal"),  # cmd.exe
    re.compile(r"[Cc]ommand not found:\s*([\w.+-]+)"),  # zsh
)


def _missing_tool_name(stderr: str) -> str:
    """The executable the shell says it could not resolve, taken from the error itself."""
    for pat in _NAMED_IN_ERROR:
        m = pat.search(stderr or "")
        if m:
            return m.group(1)
    return ""


def should_ground(stderr: str, command: str, sysstate) -> str:
    """Return the tool to look up, or "" when grounding is not warranted.

    Two warrants, and they are the same defect seen from two sides:

      * the shell cannot resolve the executable        -> the model invented the tool;
      * the executable exists and rejects the call     -> the model's memory of its CLI is
                                                          older than the CLI.

    Observed live: `vite create --template react-ts` (first case, `vite` absent) and then
    `npm init vite@latest <name> --template react-ts` (second case, `npm` present). A model
    cannot know that an ecosystem moved after its cutoff, and it does not know that it does
    not know. The web does.

    An EPERM, a dependency conflict or a network failure are different failures with different
    recoveries. Grounding them would be noise, and this module refuses to guess for the model.
    """
    from .error_classifier import is_missing_tool_signal

    text = stderr or ""
    stale = bool(_STALE_INVOCATION.search(text))
    if not stale and not is_missing_tool_signal(text, command or ""):
        return ""

    # The tool to look up is the one the ERROR names, not the one the caller is about to run.
    # Observed: `vite create ...` failed with "The term 'vite' is not recognized"; the coder,
    # correctly grounded, re-authored an `npm ...` command; and the next pass handed this
    # function the OLD stderr with the NEW command, so it "discovered" that `npm` — which is on
    # PATH — was unresolvable, and searched the web for it. A stale pairing of an error with a
    # command that never produced it.
    if stale:
        # The tool exists and rejected the call; it is exactly the one to look up.
        tool = leading_executable(command)
    else:
        tool = _missing_tool_name(text)
        if not tool:
            # The error named nothing. Fall back to the command's own executable — but only if
            # the operating system agrees it is missing. `npx` was once grounded because a text
            # heuristic saw "is not recognized" in an error really about an empty argument, and
            # npx is on PATH. The OS is authoritative about what it can resolve; a regex is not.
            candidate = leading_executable(command)
            if candidate and shutil.which(candidate) is None:
                tool = candidate

    if not tool or already_grounded(sysstate, tool):
        return ""
    return tool
