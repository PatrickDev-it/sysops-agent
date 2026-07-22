"""
terminal_runtime — Universal PTY interaction pipeline.

Pipeline:
  PTY bytes → VirtualScreen (pyte) → PromptDetector → Driver → PTY input

Public API:
  TerminalSession  — the main event loop
  detect           — PromptDetector (for testing)
  decide           — Driver (for testing)
  VirtualScreen    — pyte-backed terminal emulator (for testing)
"""

from .driver import PTYAction, decide
from .prompt_detector import detect
from .prompts import (
    CheckboxPrompt,
    ConfirmPrompt,
    ErrorPrompt,
    SelectPrompt,
    ShellPrompt,
    SpinnerPrompt,
    TextPrompt,
)
from .session import TerminalSession
from .virtual_screen import VirtualScreen

__all__ = [
    "VirtualScreen",
    "detect",
    "decide",
    "PTYAction",
    "TerminalSession",
    "SelectPrompt",
    "ConfirmPrompt",
    "TextPrompt",
    "CheckboxPrompt",
    "SpinnerPrompt",
    "ShellPrompt",
    "ErrorPrompt",
]
