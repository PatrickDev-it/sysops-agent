"""
Level 4 — Driver.

Maps structured Prompt objects to PTY actions. This is the state machine.

SelectPrompt   → ARROW keys to reach target index, then ENTER
ConfirmPrompt  → WRITE(y) or WRITE(n), then ENTER
TextPrompt     → WRITE(answer), then ENTER
CheckboxPrompt → navigate + SPACE toggle + ENTER
SpinnerPrompt  → WAIT
ShellPrompt    → DONE (process finished)
ErrorPrompt    → DONE (signal failure to caller)

The driver does NOT call the LLM. It receives structured prompts and emits
structured actions. LLM is invoked only by the caller when detect() returns
SpinnerPrompt with no progress for an extended period.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

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


@dataclass
class PTYAction:
    kind: Literal["WRITE", "KEY", "WAIT", "DONE"]
    value: str = ""

    def __str__(self) -> str:
        return f"{self.kind}({self.value!r})"


def decide(
    prompt: AnyPrompt,
    objective: str,
    constraints: list[str],
    goal: str,
    answered: dict[str, int] | None = None,
) -> PTYAction:
    """
    Given a detected Prompt, return the next PTY action.

    answered: dict of {prompt_key → times_answered} for dedup.
    """
    if answered is None:
        answered = {}

    match prompt:
        case ShellPrompt():
            return PTYAction("DONE")

        case ErrorPrompt():
            return PTYAction("DONE", "error")

        case SpinnerPrompt():
            return PTYAction("WAIT", "1500")

        case ConfirmPrompt(question=q, default=default):
            answer = _decide_confirm(q, default, objective, goal)
            return PTYAction("WRITE", f"{answer}\r")

        case TextPrompt(question=q, current_value=cur):
            answer = _decide_text(q, cur, objective, goal, constraints)
            return PTYAction("WRITE", f"{answer}\r")

        case SelectPrompt(choices=choices, selected=current_idx):
            target = _decide_select(prompt.title, choices, objective, goal)
            return _navigate_to(current_idx, target)

        case CheckboxPrompt(choices=choices, checked=checked, selected=cursor):
            return _handle_checkbox(choices, checked, cursor, objective, goal)

        case _:
            return PTYAction("WAIT", "1000")


# ── Decision logic ─────────────────────────────────────────────────────────────


def _decide_confirm(question: str, default: bool, objective: str, goal: str) -> str:
    """
    Decide yes/no for a confirmation prompt.

    Rules (in priority order):
    1. Destructive operations → No  (safety gate)
    2. Overwrite existing → No      (idempotency)
    3. Proceed/continue/install → Yes
    4. Default
    """
    q_lower = question.lower()
    obj_lower = (objective + " " + goal).lower()

    # Safety: hard destructive operations are always No
    if any(kw in q_lower for kw in ("delete", "remove", "wipe", "destroy", "format", "drop")):
        return "N"

    # Overwrite / already-exists prompts: context-sensitive
    # If the objective is to initialize/setup/configure, overwriting config files is correct.
    # If the objective is to add/install on top of existing setup, don't overwrite.
    if "already exists" in q_lower or "overwrite" in q_lower:
        _init_intent = any(
            kw in obj_lower
            for kw in (
                "init",
                "initialize",
                "setup",
                "configure",
                "reset",
                "reinitialize",
            )
        )
        return "Y" if _init_intent else "N"

    # Proceed / install / continue → Yes
    if any(
        kw in q_lower
        for kw in ("proceed", "continue", "install", "create", "initialize", "confirm", "accept")
    ):
        return "Y"

    return "Y" if default else "N"


def _decide_text(
    question: str,
    current: str,
    objective: str,
    goal: str,
    constraints: list[str],
) -> str:
    """
    Decide the text answer for a text input prompt.

    Rules:
    - "project name" / "name" → use "." (scaffold in place) or extract from goal
    - "directory" / "path" / "where" → "." (current dir)
    - "author" / "email" / "version" → empty (accept default)
    - Current value present → accept it (Enter with no change)
    """
    q = question.lower()

    # Scaffold-in-place semantics
    if any(kw in q for kw in ("project name", "app name", "project called", "name your project")):
        return "."

    if any(kw in q for kw in ("directory", "folder", "where", "path", "install to")):
        return "."

    # Accept current/default for metadata fields
    if any(kw in q for kw in ("author", "email", "version", "license", "description")):
        return current or ""

    # If there's already a value typed, accept it
    if current:
        return current

    # Generic: empty string = accept default
    return ""


# Words that carry no discriminating information in a menu question.
_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "in",
        "on",
        "with",
        "and",
        "or",
        "to",
        "for",
        "use",
        "using",
        "new",
        "project",
        "app",
        "application",
        "create",
        "init",
        "setup",
        "please",
        "would",
        "you",
        "like",
        "select",
        "choose",
        "which",
        "your",
    }
)


def _tokens(text: str) -> set[str]:
    """Lowercase alphanumeric tokens, minus stopwords. `c++`/`c#` survive as tokens."""
    return {
        t
        for t in re.findall(r"[a-z0-9+#]+", (text or "").lower())
        if t not in _STOPWORDS and len(t) > 1
    }


def _decide_select(title: str, choices: list[str], objective: str, goal: str) -> int:
    """Choose the menu item the objective actually asks for.

    THE DEFECT THIS REPLACES. There was no rule comparing an option's TEXT to the goal. The
    table scored npm-over-yarn, TypeScript, and next.js router names — memorised product
    knowledge, which `AGENTS.md` forbids outright ("VIETATO: casi speciali per singolo tool")
    — and nothing else. So for the goal "progetto React con Vite in TypeScript", the option
    "React" scored ZERO; the only rule that fired at all was `i == 0` (+1), and `score >
    best_score` being strict meant ties resolved to the lowest index. The target was
    deterministically index 0 for any menu of plain framework names.

    Combined with a cursor read off log noise (see prompt_detector) and open-loop arrow keys
    into a list that WRAPS, two blind ARROW_UPs from the top of vite's 11-item framework list
    land exactly on `Marko ↗` — which is what the agent scaffolded.

    Now: token overlap between the option and the objective, normalised by the option's own
    length so a fully-covered short option ("React") beats a long one that merely shares a
    word. Generic; it knows nothing about any framework.
    """
    if not choices:
        return 0

    wanted = _tokens(objective) | _tokens(goal)

    best_idx, best_score = 0, -1.0
    for i, choice in enumerate(choices):
        ctok = _tokens(choice)
        if not ctok:
            continue
        score = 2.0 * len(ctok & wanted) / len(ctok)

        # The wizard's own hint, when the goal expresses no preference. Deliberately weaker
        # than a real match: "(recommended)" must never outrank what the user asked for.
        if any(mark in choice.lower() for mark in ("(recommended)", "(default)")):
            score += 0.5

        # Tie-break only. This used to be the single rule that could fire.
        if i == 0:
            score += 0.25

        if score > best_score:
            best_score, best_idx = score, i

    return best_idx


def _navigate_to(current: int, target: int) -> PTYAction:
    """Generate arrow key action to move from current to target index."""
    if current == target:
        return PTYAction("KEY", "ENTER")
    if target > current:
        return PTYAction("KEY", "ARROW_DOWN")
    return PTYAction("KEY", "ARROW_UP")


def _handle_checkbox(
    choices: list[str],
    checked: list[bool],
    cursor: int,
    objective: str,
    goal: str,
) -> PTYAction:
    """Navigate checkbox list, toggle items per goal, then confirm."""
    goal_lower = (objective + " " + goal).lower()

    # Determine which items should be checked
    desired = []
    for choice in choices:
        c = choice.lower()
        # Default: check nothing unless goal mentions it
        should = any(kw in goal_lower for kw in c.split())
        desired.append(should)

    # If no item matches goal keywords, accept defaults (just ENTER)
    if not any(desired) and not any(checked):
        return PTYAction("KEY", "ENTER")

    # Find first item that needs toggling
    for i, (want, have) in enumerate(zip(desired, checked)):
        if want != have:
            # Navigate to it first
            if cursor != i:
                return PTYAction("KEY", "ARROW_DOWN" if i > cursor else "ARROW_UP")
            return PTYAction("KEY", "SPACE")

    # All items in desired state → confirm
    return PTYAction("KEY", "ENTER")
