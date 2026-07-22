"""What to do about a running process is a wall-clock decision the runtime owns, never an LLM
guess from one screenshot.

A spinner frame means the child is working. Two deterministic backstops sit in front of the
0.6B navigator, and both were paid for in production:

  * Aborting active work is always wrong. The navigator, asked "what to do at this spinner",
    answered `CTRL_C`.
  * Sending input into active work is almost always wrong. On a live React + Vite scaffold the
    navigator answered every spinner frame with `KEY(ENTER)`; the wizard advanced nothing and
    the run hung until the ten-minute timeout.

The second backstop is BOUNDED, not absolute: some wizards do render a spinner while genuinely
waiting for an answer. After ~30 s of spinner the model's judgement is restored. The bound is
what turns an unbounded hang into a delay of known length.
"""

import pytest
from src import model_router as mr

SPINNER = "⠹ Installing packages..."
IDLE = "? Would you like to use TypeScript? › (Y/n)"


@pytest.fixture(autouse=True)
def _reset_counter():
    mr._consecutive_spinner_waits = 0
    yield
    mr._consecutive_spinner_waits = 0


def _drive(monkeypatch, action: str, transcript: str) -> str:
    # The deterministic backstops are MODEL-INDEPENDENT, so this test must be hermetic — no live
    # server. `_text_call` is mocked to return the action, but `executor_pty_fallback_call` calls
    # `_text_call(_nav(), ...)`, and `_nav()` is evaluated as an argument BEFORE the mock runs — so
    # it must be stubbed too, or it spawns a real llama-server (which broke when the binary path
    # became portable + fail-loud instead of a hardcoded external path that happened to exist here).
    monkeypatch.setattr(mr, "_nav", lambda: None)
    monkeypatch.setattr(mr, "_text_call", lambda *a, **k: action)
    return mr.executor_pty_fallback_call(
        {"objective": "scaffold", "constraints": "", "transcript": transcript}
    )


def test_abort_during_active_work_is_always_overridden(monkeypatch):
    assert _drive(monkeypatch, "KEY(CTRL_C)", SPINNER) == "WAIT(2000)"


def test_abort_is_overridden_even_past_the_wait_budget(monkeypatch):
    mr._consecutive_spinner_waits = mr._MAX_SPINNER_WAITS + 5
    assert _drive(monkeypatch, "KEY(CTRL_C)", SPINNER) == "WAIT(2000)"


@pytest.mark.parametrize("action", ["KEY(ENTER)", "WRITE(y)", "key(enter)"])
def test_input_during_active_work_is_overridden(monkeypatch, action):
    """The ten-minute hang: ENTER into a spinner, forever."""
    assert _drive(monkeypatch, action, SPINNER) == "WAIT(1500)"


def test_the_override_is_bounded_so_a_blocked_wizard_is_not_starved(monkeypatch):
    for i in range(mr._MAX_SPINNER_WAITS):
        assert _drive(monkeypatch, "KEY(ENTER)", SPINNER) == "WAIT(1500)"
        assert mr._consecutive_spinner_waits == i + 1
    # Budget exhausted: the model's judgement is restored rather than the run hanging.
    assert _drive(monkeypatch, "KEY(ENTER)", SPINNER) == "KEY(ENTER)"


def test_a_successful_action_resets_the_budget(monkeypatch):
    _drive(monkeypatch, "KEY(ENTER)", SPINNER)
    assert mr._consecutive_spinner_waits == 1
    assert _drive(monkeypatch, "KEY(ENTER)", IDLE) == "KEY(ENTER)"
    assert mr._consecutive_spinner_waits == 0


def test_input_on_an_idle_prompt_passes_through(monkeypatch):
    assert _drive(monkeypatch, "WRITE(y)", IDLE) == "WRITE(y)"


@pytest.mark.parametrize("action", ["WAIT(1500)", "READ()", "DONE()"])
def test_observing_actions_are_never_overridden(monkeypatch, action):
    assert _drive(monkeypatch, action, SPINNER) == action


def test_active_work_is_recognised_by_idiom_not_by_tool_name():
    assert mr._transcript_shows_active_work("⠋ resolving dependencies")
    assert mr._transcript_shows_active_work("Installing packages")
    assert mr._transcript_shows_active_work("Downloading...")
    assert mr._transcript_shows_active_work("| ")
    assert mr._transcript_shows_active_work("- Installing")
    assert not mr._transcript_shows_active_work("? Select a framework")


@pytest.mark.parametrize(
    "idle",
    [
        "? Would you like to use TypeScript? › (Y/n)",  # `/` inside `(Y/n)`
        "Ok to proceed? (y)",
        "Select a variant: react-ts",  # `-` inside a word
        "Enter project name: my-app",
        "npm WARN deprecated foo@1.0.0",
    ],
)
def test_ordinary_punctuation_is_not_a_spinner(idle):
    r"""`|/-\` are spinner frames AND ordinary punctuation. The predicate used to scan the
    whole transcript for any of them, so `(Y/n)` read as active work and the backstop fired on
    a wizard that was blocked waiting for an answer."""
    assert not mr._transcript_shows_active_work(idle)
