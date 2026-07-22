"""
Level 3 — Prompt Detector.

Analyses the rendered VirtualScreen (clean text rows, no ANSI) and returns
a structured Prompt object. Operates on *structure*, never on symbol identity.

Detection pipeline:
  1. ShellPrompt   — shell prompt at last line means process finished
  2. ErrorPrompt   — hard failure keywords
  3. SpinnerPrompt — screen content identical to previous except spinner chars
  4. CheckboxPrompt — lines with toggle markers ([ ] / [x])
  5. SelectPrompt  — lines with cursor markers (❯ ● ► *) + non-selected lines
  6. ConfirmPrompt — (y/N) / (Y/n) / yes/no pattern anywhere in tail
  7. TextPrompt    — question mark or colon at end of last meaningful line
  8. SpinnerPrompt — fallback if no other structure found

Invariant: no rule references a specific CLI name, framework, or Unicode symbol
by identity. Rules are based on *structural patterns* that hold across all
terminal UI libraries.
"""

from __future__ import annotations

import re
from typing import Optional

from .prompts import (
    AnyPrompt,
    CheckboxPrompt,
    ConfirmPrompt,
    ErrorPrompt,
    SelectPrompt,
    ShellPrompt,
    SpinnerPrompt,
    TextPrompt,
)

# ── Structural patterns ────────────────────────────────────────────────────────

# Shell prompt: PowerShell (PS C:\...>) or bash/zsh (user@host:~$ / ~$)
_SHELL_RE = re.compile(r"(?:PS\s+[A-Za-z]:[^>]*>|[$#%]\s*$|\w+@[\w.-]+[^$]*[$#]\s*$)")

# Hard failure keywords — process is unrecoverable
_FAIL_RE = re.compile(
    r"\b(ENOENT|EACCES|EPERM|cannot find the path|access is denied"
    r"|is not recognized as|no such file|fatal error|npm ERR!"
    r"|invalid package\.json name|command not found)\b",
    re.IGNORECASE,
)

# Confirm patterns: (y/N) (Y/n) [y/N] yes/no etc.
_CONFIRM_RE = re.compile(
    r"\(y[/|]N\)|\(Y[/|]n\)|\[y[/|]N\]|\[Y[/|]n\]"
    r"|(?:yes|no)\s*/\s*(?:yes|no)"
    r"|\bYes\b.*\bNo\b|\bNo\b.*\bYes\b",
    re.IGNORECASE,
)

# The LIVE cursor: the glyph a TUI puts on the row the user is currently on.
#
# This set used to also contain ✔ ✓ * and >, which are COMPLETION markers and shell echo,
# not cursors. Every already-answered wizard line (`✔ Project name: … react-ts`) and every
# npm echo line (`> npx`, `> create-vite …`) therefore matched, was appended to `choices`,
# and — because the loop reassigns on each match — MOVED the reported cursor. The last piece
# of log noise on screen became "the selected option".
_CURSOR_CHARS = frozenset("❯●◆►▶→»")

# Lines a wizard has already answered. Never options, never the cursor.
_DONE_CHARS = frozenset("✔✓√☑")

# Unselected option marker: first non-space char of a line
_UNSEL_CHARS = frozenset("○◯·•–")

# Checkbox markers: [x] [X] [ ] ◉ ◯ ✔ ✗ ☑ ☐
_CHECKBOX_RE = re.compile(r"^\s*(?:[◉◯✔✗☑☐]|\[[xX ]\])\s+\S")

# Lines that are purely spinner noise (braille, ASCII spin chars, dots, pipes)
_SPINNER_LINE_RE = re.compile(r"^[\s⠀-⣿|/\\\-.,·•\xa0⠀-⣿]+$")

# A "question" line ends with ? or : or contains a separator
_QUESTION_RE = re.compile(r"[?]\s*$|:\s*$|[›»]\s")


def detect(
    rows: list[str], prev_rows: list[str] | None = None, highlighted: set[str] | None = None
) -> AnyPrompt:
    """
    Analyse rendered screen rows and return the best matching Prompt.

    Args:
        rows:        current VirtualScreen.rows (clean text, no ANSI)
        prev_rows:   previous frame's rows for spinner diffing (optional)
        highlighted: stripped text of rows the emulator reports in reverse video or on a
                     non-default background — `VirtualScreen.highlighted_rows`. This is the
                     ONLY cursor signal a TUI that draws no cursor glyph emits (clack,
                     BubbleTea, fzf, most Go/Rust CLIs), and it used to be discarded before
                     it reached this function. Passed as TEXT rather than row indices because
                     `nonempty` below re-indexes the screen.
    """
    nonempty = [r for r in rows if r.strip()]

    # 1 — Shell prompt: process returned control
    if nonempty:
        last = nonempty[-1]
        if _SHELL_RE.search(last):
            cwd_m = re.search(r"[A-Za-z]:[/\\][^\s>]*|~[^\s>]*", last)
            return ShellPrompt(cwd=cwd_m.group(0) if cwd_m else "")

    # 2 — Hard failure
    tail_text = "\n".join(nonempty[-10:])
    if _FAIL_RE.search(tail_text):
        return ErrorPrompt(message=tail_text[-300:])

    # 3 — Spinner: screen only differs in spinner chars from previous frame.
    #     BUT a spinner animating NEXT TO a prompt (common in clack/modern CLIs:
    #     a live spinner plus an already-displayed "● Yes ○ No") must NOT be
    #     masked as a spinner — that caused WAIT-forever. Only treat as spinner
    #     when there is no answerable prompt (radio/confirm/question) on screen.
    if prev_rows is not None and nonempty:
        if _is_spinner_only_change(rows, prev_rows) and not _screen_has_prompt(nonempty):
            last_text = nonempty[-1]
            return SpinnerPrompt(text=last_text)

    # 4 — Checkbox
    checkbox = _try_checkbox(nonempty)
    if checkbox:
        return checkbox

    # 5 — Select menu
    select = _try_select(nonempty, highlighted)
    if select:
        return select

    # 6 — Confirm
    confirm = _try_confirm(nonempty)
    if confirm:
        return confirm

    # 7 — Text input
    text = _try_text(nonempty)
    if text:
        return text

    # 8 — Fallback: something is running/printing
    spinner_text = nonempty[-1] if nonempty else ""
    return SpinnerPrompt(text=spinner_text)


def _screen_has_prompt(nonempty: list[str]) -> bool:
    """True if the current screen contains an answerable prompt (radio/list
    cursor line, checkbox, confirm, or a trailing question). Structural — reuses
    the same markers the widget detectors use; no tool/glyph-identity rules."""
    for line in nonempty[-8:]:
        stripped = line.lstrip()
        if not stripped:
            continue
        if stripped[0] in _CURSOR_CHARS or stripped[0] in _UNSEL_CHARS:
            return True
        if _CHECKBOX_RE.match(line) or _CONFIRM_RE.search(line) or _QUESTION_RE.search(line):
            return True
    return False


# ── Spinner diff ───────────────────────────────────────────────────────────────


def _is_spinner_only_change(current: list[str], previous: list[str]) -> bool:
    """
    True if the only difference between frames is spinner characters.

    Strategy: compare rows after stripping all spinner chars. If the
    stripped versions are identical, only spinners changed.
    """

    def strip_spinners(s: str) -> str:
        # Remove braille, ASCII spinner, box-drawing noise
        s = re.sub(r"[⠀-⣿|/\\\-]+", "", s)
        return s.strip()

    # Align by length (pad shorter with empty strings)
    n = max(len(current), len(previous))
    cur_pad = current + [""] * (n - len(current))
    prev_pad = previous + [""] * (n - len(previous))

    for c, p in zip(cur_pad, prev_pad):
        if strip_spinners(c) != strip_spinners(p):
            return False
    return True


# ── Widget detectors ───────────────────────────────────────────────────────────


def _try_checkbox(rows: list[str]) -> Optional[CheckboxPrompt]:
    """Detect multi-select checkbox lists."""
    checkbox_lines = [(i, r) for i, r in enumerate(rows) if _CHECKBOX_RE.match(r)]
    if len(checkbox_lines) < 2:
        return None

    choices = []
    checked = []
    selected = 0
    for idx, (i, line) in enumerate(checkbox_lines):
        # strip the marker prefix
        text = re.sub(r"^\s*(?:[◉◯✔✗☑☐]|\[[xX ]\])\s+", "", line).strip()
        choices.append(text)
        is_checked = bool(re.search(r"[◉✔☑xX]|\[x\]|\[X\]", line[:4]))
        checked.append(is_checked)
        # Selected = line with cursor char or visually distinct indent
        stripped_full = line.lstrip()
        if stripped_full and stripped_full[0] in _CURSOR_CHARS:
            selected = idx

    title = _find_title(rows, checkbox_lines[0][0])
    return CheckboxPrompt(title=title, choices=choices, checked=checked, selected=selected)


def _classify_menu_line(line: str) -> tuple[str, str] | None:
    """Classify one screen row as a menu entry. Returns (kind, text) or None.

    kind is "cursor" (carries a live cursor glyph), or "option" (an unselected entry, marked
    either by an unselected glyph or purely by indentation).
    """
    stripped = line.lstrip()
    if not stripped or stripped[0] in _DONE_CHARS:
        return None
    first = stripped[0]
    if first in _CURSOR_CHARS:
        text = re.sub(r"^[❯●◆►▶→»\s]+", "", stripped).strip()
        return ("cursor", text) if text else None
    if first in _UNSEL_CHARS:
        text = re.sub(r"^[○◯·•–\s]+", "", stripped).strip()
        return ("option", text) if text else None
    if line.startswith("  ") and not _QUESTION_RE.search(stripped):
        return ("option", stripped)
    return None


def _try_select(rows: list[str], highlighted: set[str] | None = None) -> Optional[SelectPrompt]:
    """Detect single-select menus (radio group).

    THE OPTION BLOCK IS FOUND AS A BLOCK. The previous implementation walked the screen top to
    bottom and only accepted an indented line once it had already seen a cursor glyph, so every
    option ABOVE the cursor was silently dropped — a menu sitting on its third entry reported
    the third entry as index 0, and navigation then counted from there. It also accepted any
    indented line once the list had started, so a wrapped npm warning several rows lower joined
    the options.

    A menu is a CONTIGUOUS run of entry-shaped rows, exactly one of which carries the cursor.
    Finding the run first, and the cursor within it second, is both correct and simpler.
    """
    blocks: list[list[tuple[int, str, str]]] = []  # [(row, kind, text), ...]
    current: list[tuple[int, str, str]] = []
    for i, line in enumerate(rows):
        entry = _classify_menu_line(line)
        if entry is None:
            if current:
                blocks.append(current)
                current = []
            continue
        current.append((i, entry[0], entry[1]))
    if current:
        blocks.append(current)

    highlighted = highlighted or set()

    def _score(block: list[tuple[int, str, str]]) -> tuple[int, int]:
        has_cursor = any(kind == "cursor" for _, kind, _ in block)
        has_highlight = any(text in highlighted for _, _, text in block)
        return (int(has_cursor or has_highlight), len(block))

    blocks = [b for b in blocks if len(b) >= 2]
    if not blocks:
        return None
    block = max(blocks, key=_score)
    if len(block) < 2:
        return None

    choices = [text for _, _, text in block]

    selected = -1
    for k, (_, kind, _) in enumerate(block):
        if kind == "cursor":
            selected = k
            break
    if selected < 0 and highlighted:
        # No cursor GLYPH, but the emulator reports a row in reverse video. That is the entire
        # cursor signal for a clack/BubbleTea/fzf-style menu, and it was discarded one layer
        # below this function until the attribute plane was exposed.
        for k, (_, _, text) in enumerate(block):
            if text in highlighted:
                selected = k
                break
    if selected < 0:
        # Neither glyph nor attribute: the cursor is genuinely unobservable on this frame.
        # `max(0, selected_row)` used to turn that into the confident claim "the cursor is on
        # option 0", and navigation then counted keystrokes from a fabricated origin. Returning
        # None is an honest "I do not know" and routes the screen to the fallback.
        return None

    return SelectPrompt(title=_find_title(rows, block[0][0]), choices=choices, selected=selected)


def _try_confirm(rows: list[str]) -> Optional[ConfirmPrompt]:
    """Detect yes/no confirmation prompts."""
    tail = rows[-5:] if len(rows) >= 5 else rows
    for line in reversed(tail):
        m = _CONFIRM_RE.search(line)
        if m:
            # default: lower-case = default option
            default = not bool(re.search(r"\(y/N\)|\[y/N\]", line, re.IGNORECASE))
            question = _strip_confirm_suffix(line)
            return ConfirmPrompt(question=question, default=default)
    return None


def _try_text(rows: list[str]) -> Optional[TextPrompt]:
    """Detect free-text input prompts."""
    # Look at last 5 non-empty rows, prefer lines with ? or :
    tail = [r for r in rows if r.strip()][-5:]
    for line in reversed(tail):
        stripped = line.strip()
        # Skip completed/confirmed lines: start with ✔ √ ✓ or similar
        if stripped and stripped[0] in "✔✓√◉☑":
            continue
        # Skip lines that are checkbox items (already handled)
        if _CHECKBOX_RE.match(line):
            continue
        if _QUESTION_RE.search(line):
            # Extract question text (strip trailing separators/values)
            question = re.sub(r"\s*[›»|◼█▌_│]\s*.*$", "", line).rstrip("?:").strip()
            # Extract current value if present (after separator)
            val_m = re.search(r"[›»|]\s*(.+)$", line)
            value = val_m.group(1).strip() if val_m else ""
            if question and len(question) > 2:
                return TextPrompt(question=question, current_value=value)
    return None


# ── Helpers ────────────────────────────────────────────────────────────────────


def _find_title(rows: list[str], menu_start_row: int) -> str:
    """The question immediately above the menu — searched NEAREST-first.

    This scanned FORWARD from `menu_start_row - 5`, so it returned the row FURTHEST from the
    menu. Measured in a real run (var/benchmark/agent_eval/react.log:58): the title came back
    as `npm warn Unknown cli config "--template"` instead of `Select a framework:`.

    The title is not cosmetic. It is the dedup key in `session.run` (so a wrong one that
    changes as the screen scrolls means dedup never fires) and it is what `_decide_select` and
    the LLM fallback are told the question is.
    """
    for i in range(menu_start_row - 1, max(-1, menu_start_row - 6), -1):
        line = rows[i].strip() if 0 <= i < len(rows) else ""
        if line and not _SPINNER_LINE_RE.match(line):
            return line
    return ""


def _strip_confirm_suffix(line: str) -> str:
    """Remove the (y/N) suffix and return only the question text."""
    cleaned = re.sub(
        r"\s*[\(\[](?:y[/|]N|Y[/|]n|yes[/|]no|no[/|]yes)[\)\]]\s*:?\s*$",
        "",
        line,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned or line.strip()
