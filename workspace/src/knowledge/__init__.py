"""
OS Capability Knowledge Engine (OCKE).

Public exports:
    OCKE         — main runtime engine
    detect       — build EnvironmentProfile from live host
    validate_command — one-off command validation
"""

from .command_registry import CommandRegistry, intents_from_text
from .environment_detector import EnvironmentProfile, detect
from .knowledge_loader import KnowledgeEntry, load_for_profile
from .knowledge_validator import KnowledgeValidator, ValidationResult, validate_command
from .ocke import OCKE, OCKEContext

__all__ = [
    "OCKE",
    "OCKEContext",
    "detect",
    "EnvironmentProfile",
    "validate_command",
    "KnowledgeValidator",
    "ValidationResult",
    "CommandRegistry",
    "intents_from_text",
    "KnowledgeEntry",
    "load_for_profile",
]
