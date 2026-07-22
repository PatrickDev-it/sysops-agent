r"""Interactive navigation must MEASURE, never assume. Driven against a real byte stream.

The old controller emitted one arrow key per outer iteration, slept 200 ms, and then cleared
`last_content_hash` — which FORCED the next iteration past the screen-diff gate whether or not
the child had redrawn. So it decided again from a possibly stale frame and fired again. Nothing
in the loop ever compared an emitted key against its effect.

With a wrapping list that is not a subtle bug. `create-marko` is exactly two blind ARROW_UPs
from the top of vite's 11-item framework menu.

These tests run the real `TerminalSession` against `FakeMenuPty`, which emits genuine ANSI and
redraws on every keystroke, through pyte. Nothing is mocked: the assertions are about where the
cursor actually ended up.
"""

import pytest
from src.terminal_runtime.session import TerminalSession

from tests.fake_pty import DOWN, UP, DeafMenuPty, FakeClock, FakeMenuPty

VITE_FRAMEWORKS = [
    "Vanilla",
    "Vue",
    "React",
    "Preact",
    "Lit",
    "Svelte",
    "Solid",
    "Qwik",
    "Angular",
    "Marko",
    "Others",
]
NPM_NOISE = [
    'npm warn Unknown cli config "--template". This will stop working',
    "> npx",
    "> create-vite react-ts --template react-ts",
]


def _session(pty, llm=None):
    clock = FakeClock()
    return TerminalSession(write_fn=pty.write, read_fn=pty.read, llm_fn=llm, clock=clock), clock


# ── The production failure ───────────────────────────────────────────────────


def test_a_react_goal_selects_react_not_marko():
    """The reported failure, end to end, against a wrapping menu with npm noise on screen."""
    pty = FakeMenuPty(
        "Select a framework:", VITE_FRAMEWORKS, selected=0, wrap=True, noise=NPM_NOISE
    )
    session, _ = _session(pty)
    session.run("progetto React con Vite in TypeScript", [], "")
    assert pty.committed == "React", f"committed {pty.committed!r}"


def test_it_never_arrows_upward_off_the_top_of_the_list():
    """Upward from index 0 is what wraps onto Marko. A measured controller has no reason to
    go up when its target is below."""
    pty = FakeMenuPty("Select a framework:", VITE_FRAMEWORKS, selected=0, wrap=True)
    session, _ = _session(pty)
    session.run("a React project", [], "")
    assert UP not in pty.keys_received, "navigated upward from the top of the list"
    assert pty.keys_received.count(DOWN) == VITE_FRAMEWORKS.index("React")


def test_it_takes_exactly_as_many_steps_as_the_distance():
    """One key per row, no overshoot, no repeats — the definition of a converging loop."""
    pty = FakeMenuPty("Select a framework:", VITE_FRAMEWORKS, selected=0, wrap=True)
    session, _ = _session(pty)
    session.run("scaffold with Svelte", [], "")
    assert pty.committed == "Svelte"
    assert pty.keys_received.count(DOWN) == VITE_FRAMEWORKS.index("Svelte")


def test_upward_navigation_works_when_the_target_is_above():
    pty = FakeMenuPty("Select a framework:", VITE_FRAMEWORKS, selected=8, wrap=True)
    session, _ = _session(pty)
    session.run("a Vue application", [], "")
    assert pty.committed == "Vue"
    assert DOWN not in pty.keys_received


# ── The attribute plane ──────────────────────────────────────────────────────


def test_a_menu_whose_cursor_is_only_reverse_video_is_navigable():
    """clack / BubbleTea / fzf draw no cursor glyph. Before the attribute plane was exposed,
    this menu's cursor was structurally invisible and `_try_select` reported index 0."""
    pty = FakeMenuPty(
        "Select a framework:", VITE_FRAMEWORKS, selected=0, style="reverse", wrap=True
    )
    session, _ = _session(pty)
    session.run("a Qwik project", [], "")
    assert pty.committed == "Qwik"


def test_reverse_video_cursor_is_tracked_across_moves():
    pty = FakeMenuPty(
        "Pick one:", ["alpha", "beta", "gamma", "delta"], selected=3, style="reverse", wrap=True
    )
    session, _ = _session(pty)
    session.run("choose beta", [], "")
    assert pty.committed == "beta"


# ── Refusing to guess ────────────────────────────────────────────────────────


def test_a_key_that_does_not_move_the_cursor_stops_the_loop():
    """A terminal that ignores input used to be indistinguishable from success: sleep, clear
    the change hash, fire again. The loop must observe the absence of movement and stop."""
    calls = []

    def _llm(objective, constraints, screen):
        calls.append(screen)
        return "KEY(ENTER)"

    pty = DeafMenuPty("Select a framework:", VITE_FRAMEWORKS, selected=0, wrap=True)
    session, _ = _session(pty, llm=_llm)
    session.run("a React project", [], "")

    arrows = [k for k in pty.keys_received if k in (UP, DOWN)]
    assert len(arrows) <= 1, f"fired {len(arrows)} arrows into an unresponsive terminal"
    assert calls, "an unconverged navigation must escalate, not commit silently"


def test_it_does_not_commit_a_selection_it_could_not_verify():
    pty = DeafMenuPty("Select a framework:", VITE_FRAMEWORKS, selected=0, wrap=True)
    session, _ = _session(pty, llm=lambda *a: "KEY(CTRL_C)")
    session.run("a React project", [], "")
    assert pty.committed is None, "committed a row the controller never observed reaching"


def test_a_single_option_menu_commits_without_navigating():
    pty = FakeMenuPty("Confirm target:", ["only-choice", "other"], selected=0, wrap=False)
    session, _ = _session(pty)
    session.run("use only-choice", [], "")
    assert pty.committed == "only-choice"
    assert not [k for k in pty.keys_received if k in (UP, DOWN)]


# ── Determinism ──────────────────────────────────────────────────────────────


def test_the_run_consumes_no_wall_clock():
    """Timing is injected, so the interactive subsystem is testable without waiting. If this
    ever regresses, some path went back to calling `time` directly."""
    import time as real_time

    pty = FakeMenuPty("Select a framework:", VITE_FRAMEWORKS, selected=0, wrap=True)
    session, clock = _session(pty)
    t0 = real_time.perf_counter()
    session.run("a React project", [], "")
    assert real_time.perf_counter() - t0 < 1.0
    assert clock.now > 0, "the controller must still be pacing itself on the injected clock"


@pytest.mark.parametrize("start", range(len(VITE_FRAMEWORKS)))
def test_it_converges_from_every_starting_position(start):
    """A control loop that converges from one position and not another is not a control loop."""
    pty = FakeMenuPty("Select a framework:", VITE_FRAMEWORKS, selected=start, wrap=True)
    session, _ = _session(pty)
    session.run("a React project", [], "")
    assert pty.committed == "React", f"from index {start} committed {pty.committed!r}"
