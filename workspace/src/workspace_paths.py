"""Single owner of one rule: the model never sees the workspace's absolute path.

Why this exists, measured rather than assumed. `supervisor.jinja` has always instructed
"the executor already runs with cwd=WORKSPACE, use relative paths". The models ignored it —
the 8B emitted an absolute path in 31 of 127 plans — because the *context* contradicted the
instruction: `cwd`, `workspace_state`, `workspace` and every past command in `history` all
showed `C:\\Users\\...`. A model copies what it sees, not what it is told.

The cost is not cosmetic. Inside a JSON string an absolute Windows path must be escaped,
`C:\\\\Users\\\\...`, and a JSON grammar permits an unbounded run of legal `\\\\` pairs. The
0.6B navigator fell into that hole: up to **857 consecutive backslashes** in one string, which
never closed, which made the plan unparsable, which killed 39 of 48 runs. The 8B never looped
(max run: 3). Same grammar, same prompt — only capacity differed.

So the fix is not a bigger model, a repetition penalty, or a tighter grammar. It is removing
the token that seduces the model. Scrub the root out of the prompt and the escape sequence has
no source: relative paths contain no backslash at all.

Applied at exactly one place — `model_router._render`, after rendering — so it covers every
template and every context key, including the ones that feed themselves (`history`).
"""

from __future__ import annotations

import re
from pathlib import Path

_root: Path | None = None
_patterns: list[re.Pattern] = []


def set_root(workspace: str | Path | None) -> None:
    """Called once per run by the orchestrator. `None` disables scrubbing."""
    global _root, _patterns
    if workspace is None:
        _root, _patterns = None, []
        return
    _root = Path(workspace).resolve()
    native = str(_root)
    spellings = {
        native,  # C:\a\b
        native.replace("\\", "/"),  # C:/a/b
        native.replace("\\", "\\\\"),  # C:\\a\\b   (as it appears escaped inside JSON)
    }
    # Longest first: `C:\\a\\b` must be consumed before `C:\a\b` can match a prefix of it.
    _patterns = [
        re.compile(re.escape(s), re.IGNORECASE) for s in sorted(spellings, key=len, reverse=True)
    ]


def root() -> Path | None:
    return _root


def scrub(text: str) -> str:
    """Replace every spelling of the workspace root with `.`, then tidy the separator.

    `C:\\Users\\x\\T01\\out.txt` → `.\\out.txt` → `out.txt`. A bare mention of the root
    becomes `.`, which is what the workspace IS from the executor's cwd.
    """
    if not _patterns or not text:
        return text
    out = text
    for pat in _patterns:
        out = pat.sub(".", out)
    # `.\out.txt`, `./out.txt`, `.\\out.txt` → `out.txt`; a lone `.` survives.
    out = re.sub(r"(?<![\w.])\.(?:\\\\|[\\/])(?=[^\s\\/])", "", out)
    return out
