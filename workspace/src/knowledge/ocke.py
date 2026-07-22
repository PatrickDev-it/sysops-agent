"""
OS Capability Knowledge Engine — Public Interface.

One object, one call. The orchestrator holds an OCKE instance for the run
and uses it in two places:

  1. Before the supervisor generates a plan:
        block = ocke.prompt_block()
        → inject platform constraints into the supervisor system prompt

  2. After the supervisor returns a plan:
        plan, rejections = ocke.filter_plan(raw_plan)
        → steps with cross-platform violations are annotated/blocked

  3. Before a command reaches the shell:
        ocke.validate_command(cmd)
        → the last platform gate

A third use once existed — resolving a deterministic command for a step from the knowledge
base — together with a per-OS success/failure memory. Both were deleted: nothing in `src/`
called them, the KB covers none of the measured workload, and their template renderer
substituted variables into a shell string with no quoting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from .command_registry import CommandRegistry
from .environment_detector import EnvironmentProfile, detect, from_state
from .knowledge_loader import forbidden_platform_tags
from .knowledge_validator import KnowledgeValidator, ValidationResult

if TYPE_CHECKING:
    from ..state import SystemState


@dataclass
class OCKEContext:
    """Everything the OCKE knows about the current platform, ready for prompt injection."""

    profile_summary: str  # one-line OS/shell fingerprint
    active_intents: list[str]  # intent labels available for this platform
    forbidden_tags: list[str]  # tags that must never appear in commands
    package_managers: list[str]  # confirmed-available pm names
    capabilities: list[str]  # confirmed-available tools

    def to_prompt_block(self) -> str:
        """
        Compact prompt injection. Fits within ~400 characters.
        Never describes what OCKE is — just emits operative constraints.
        """
        lines = [
            f"OS_PROFILE: {self.profile_summary}",
            f"ACTIVE_PACKAGE_MANAGERS: {', '.join(self.package_managers) or 'none'}",
            f"FORBIDDEN_COMMANDS: {', '.join(self.forbidden_tags[:12]) or 'none'}",
        ]
        # KB_RECENT_FAILURES and KB_PROVEN_COMMANDS used to be emitted here. Their source,
        # KnowledgeMemory, was written only by the deleted ranker path — so both lists were
        # ALWAYS empty and neither branch could ever be taken. Two fields of the prompt
        # contract that described a learning loop the runtime did not have.
        return "\n".join(lines)


class OCKE:
    """
    OS Capability Knowledge Engine — runtime instance.

    Lifecycle: one instance per orchestrator.run() call.
    Profile is detected once and cached for the duration of the run.
    """

    def __init__(self, profile: Optional[EnvironmentProfile] = None):
        self.profile: EnvironmentProfile = profile or detect()
        self._registry = CommandRegistry.build(self.profile)
        self._validator = KnowledgeValidator(self.profile)

    @classmethod
    def from_state(cls, state: "SystemState") -> "OCKE":
        """Build an OCKE instance using the SystemState's already-probed environment."""
        profile = from_state(state)
        return cls(profile=profile)

    # ── Core APIs ─────────────────────────────────────────────────────────────

    def validate_command(self, command: str) -> ValidationResult:
        """Hard validate a command before it reaches the shell."""
        return self._validator.validate(command)

    def filter_plan(self, plan: list[dict]) -> tuple[list[dict], list[str]]:
        """
        Filter a supervisor plan for cross-platform violations.
        Returns (annotated_plan, rejection_reasons).
        Steps with hard violations have `_ocke_blocked` set but are NOT removed
        (so the orchestrator can log and skip them explicitly).
        """
        return self._validator.filter_plan(plan)

    def _context_for_prompt(self) -> OCKEContext:
        """
        Build the runtime knowledge context for supervisor prompt injection.
        Called once before planning.
        """
        forbidden = sorted(forbidden_platform_tags(self.profile))
        return OCKEContext(
            profile_summary=self.profile.summary(),
            active_intents=self._registry.intents_available(),
            forbidden_tags=forbidden,
            package_managers=list(self.profile.package_managers),
            capabilities=list(self.profile.capabilities),
        )

    def prompt_block(self) -> str:
        """Shorthand: build context and return the prompt string."""
        return self._context_for_prompt().to_prompt_block()

    def summary(self) -> str:
        lines = [
            "=== OCKE Runtime State ===",
            self.profile.summary(),
            "",
            self._registry.summary(),
        ]
        return "\n".join(lines)
