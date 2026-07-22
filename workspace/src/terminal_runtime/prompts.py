"""
Level 2 — Prompt data model.

These types represent *interaction primitives*, not CLI-specific concepts.
A SelectPrompt is the same whether it came from Inquirer, Clack, BubbleTea,
fzf, dialog, questionary, or any other library.

The PromptDetector produces these; the Driver consumes them.
The LLM only ever sees these when the detector fails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class SelectPrompt:
    """A single-choice selection list (radio group)."""

    title: str
    choices: list[str]
    selected: int = 0  # index of highlighted item

    kind: Literal["select"] = field(default="select", init=False)


@dataclass
class ConfirmPrompt:
    """A yes/no question."""

    question: str
    default: bool = True  # True = yes is default

    kind: Literal["confirm"] = field(default="confirm", init=False)


@dataclass
class TextPrompt:
    """A free-text input field."""

    question: str
    current_value: str = ""  # text already typed (may be a default)
    placeholder: str = ""

    kind: Literal["text"] = field(default="text", init=False)


@dataclass
class CheckboxPrompt:
    """A multi-select list."""

    title: str
    choices: list[str]
    checked: list[bool] = field(default_factory=list)
    selected: int = 0  # cursor position

    kind: Literal["checkbox"] = field(default="checkbox", init=False)


@dataclass
class SpinnerPrompt:
    """Process is busy — no user interaction needed."""

    text: str = ""

    kind: Literal["spinner"] = field(default="spinner", init=False)


@dataclass
class ShellPrompt:
    """Shell prompt visible — process has returned control."""

    cwd: str = ""

    kind: Literal["shell"] = field(default="shell", init=False)


@dataclass
class ErrorPrompt:
    """Unrecoverable error state."""

    message: str = ""

    kind: Literal["error"] = field(default="error", init=False)


# Union type for type-checkers
AnyPrompt = (
    SelectPrompt
    | ConfirmPrompt
    | TextPrompt
    | CheckboxPrompt
    | SpinnerPrompt
    | ShellPrompt
    | ErrorPrompt
)
