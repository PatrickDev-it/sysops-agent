r"""The `create-marko` failure, reconstructed from the production log and pinned.

`var/benchmark/agent_eval/react.log:54-79`, goal "progetto React con Vite in TypeScript":

    58  screen: select  npm warn Unknown cli config "--template". This will stop wor
    59  action: KEY('ARROW_UP')
    61  action: KEY('ARROW_UP')
    63   calling LLM with transcript          (x4, never returning to decide())
    64  action: KEY('ENTER')
    79  grounding: 'create-marko' is not resolvable

Five defects in one chain, each verifiable here:

  1. `_find_title` scanned FORWARD from `menu_start_row - 5`, returning the row FURTHEST from
     the menu — an npm warning instead of "Select a framework:".
  2. `_CURSOR_CHARS` contained the completion markers `✔ ✓ * >`, so answered wizard lines and
     npm's own echo became options AND moved the reported cursor (last match wins).
  3. `_decide_select` had no rule comparing an option to the goal, so "React" scored zero and
     the only rule that could fire was `i == 0`. Target was always index 0.
  4. `_navigate_to` fired arrows open-loop into a list that WRAPS. Two ARROW_UPs from the top
     of vite's 11-item list land on `Marko ↗`.
  5. The dedup counter's reset was a stale read, so after two actions the deterministic driver
     was disabled for that prompt permanently and the LLM fallback — whose prompt has no arrow
     key in its vocabulary and instructs it to press ENTER — committed the wrong row.

None of it had a regression test: `grep -r "ARROW\|_try_select\|_decide_select" tests/`
returned nothing.
"""

import pytest
from src.terminal_runtime.driver import _decide_select
from src.terminal_runtime.prompt_detector import _try_select

GOAL = "Inizializza un progetto React con Vite in TypeScript"

# The screen as it appeared, npm noise included.
VITE_FRAMEWORK_SCREEN = [
    'npm warn Unknown cli config "--template". This will stop working in the next',
    'npm warn Unknown cli config "--no-interactive". This will stop working in the',
    "> npx",
    "> create-vite react-ts --template react-ts",
    "",
    "✔ Project name: … react-ts",
    "? Select a framework:",
    "❯   Vanilla",
    "    Vue",
    "    React",
    "    Preact",
    "    Lit",
    "    Svelte",
    "    Solid",
    "    Qwik",
    "    Angular",
    "    Marko ↗",
    "    Others",
]


def test_npm_noise_is_not_a_menu_option():
    p = _try_select(VITE_FRAMEWORK_SCREEN)
    assert p is not None
    assert not any(
        "npm warn" in c or c.startswith("npx") or "create-vite" in c for c in p.choices
    ), p.choices


def test_an_answered_line_is_not_a_menu_option():
    """`✔ Project name: … react-ts` matched _CURSOR_CHARS and became both an option and the
    reported cursor position."""
    p = _try_select(VITE_FRAMEWORK_SCREEN)
    assert not any("Project name" in c for c in p.choices), p.choices


def test_the_cursor_is_the_glyph_row_not_the_last_marker():
    p = _try_select(VITE_FRAMEWORK_SCREEN)
    assert p.choices[p.selected] == "Vanilla", (p.selected, p.choices)


def test_the_title_is_the_nearest_question():
    p = _try_select(VITE_FRAMEWORK_SCREEN)
    assert "Select a framework" in p.title
    assert "npm warn" not in p.title


def test_a_react_goal_never_targets_marko():
    """The reported production failure, as a single assertion."""
    p = _try_select(VITE_FRAMEWORK_SCREEN)
    idx = _decide_select(p.title, p.choices, GOAL, "")
    assert p.choices[idx] == "React", f"selected {p.choices[idx]!r}"


def test_navigation_from_the_cursor_goes_down_not_up():
    """`_navigate_to` emitted ARROW_UP because the cursor was fabricated from log noise. From
    a correct cursor at index 0 toward React, every step is downward — and downward cannot
    wrap past the end of the list."""
    from src.terminal_runtime.driver import _navigate_to

    p = _try_select(VITE_FRAMEWORK_SCREEN)
    target = _decide_select(p.title, p.choices, GOAL, "")
    action = _navigate_to(p.selected, target)
    assert action.value == "ARROW_DOWN", action


@pytest.mark.parametrize(
    "objective,expected",
    [
        ("progetto React con Vite in TypeScript", "React"),
        ("a Vue application", "Vue"),
        ("scaffold something with Svelte", "Svelte"),
        ("set up Qwik", "Qwik"),
    ],
)
def test_the_option_matching_the_goal_wins(objective, expected):
    """Generic lexical matching, no product table: the rule that replaced hardcoded
    npm/TypeScript/app-router knowledge must work for every option equally."""
    p = _try_select(VITE_FRAMEWORK_SCREEN)
    idx = _decide_select(p.title, p.choices, objective, "")
    assert p.choices[idx] == expected


def test_with_no_signal_the_wizards_own_recommendation_wins_over_index_zero():
    screen = ["? Pick a preset:", "❯   Custom", "    Base (Recommended)", "    Minimal"]
    p = _try_select(screen)
    idx = _decide_select(p.title, p.choices, "set it up", "")
    assert p.choices[idx] == "Base (Recommended)"


def test_an_explicit_goal_outranks_the_recommendation():
    screen = ["? Pick a preset:", "❯   Custom", "    Base (Recommended)", "    Minimal"]
    p = _try_select(screen)
    idx = _decide_select(p.title, p.choices, "use the minimal preset", "")
    assert p.choices[idx] == "Minimal"


def test_an_undetectable_cursor_is_not_reported_as_index_zero():
    """`selected=max(0, selected_row)` turned "I cannot see the cursor" into the confident
    claim "the cursor is on option 0", and navigation then counted keystrokes from a
    fabricated origin. Returning None routes the screen to the fallback instead."""
    screen = ["? Select a framework:", "    Vanilla", "    Vue", "    React"]
    assert _try_select(screen) is None


def test_a_wrapped_warning_below_the_menu_does_not_join_the_options():
    """The indent rule accepted ANY 2-space-indented line once options existed, so npm's
    wrapped continuation lines were appended as choices."""
    screen = [
        "? Select a framework:",
        "❯   Vanilla",
        "    Vue",
        "",
        "  npm warn continuation of an earlier warning line",
    ]
    p = _try_select(screen)
    assert p is not None
    assert all("npm warn" not in c for c in p.choices), p.choices
