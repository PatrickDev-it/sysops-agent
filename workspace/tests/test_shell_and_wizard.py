"""
PATCH-018 — two area-generalizations (not single-use fixes):

A) shell-safe argument quoting: any bare '@'-prefixed literal arg is quoted for
   the PowerShell parser (category: arg literals starting with a PS operator),
   so the model needn't be a quoting expert.
B) wizard handling: (B1) read-only step-types never drive interactive wizards;
   (B2) _decide_select follows a wizard's own "(recommended)"/"(default)" mark
   when the goal gives no stronger signal.

Run: python -m pytest tests/test_shell_and_wizard.py -v
"""

import src.orchestrator as orch
from src.terminal_runtime.driver import _decide_select

# ── A. shell-safe arg quoting (@ splat category) ─────────────────────────────


def _q(cmd):
    # force the win32 branch regardless of host so the transform is testable
    _orig = orch.sys.platform
    orch.sys.platform = "win32"
    try:
        return orch._quote_ps_literal_args(cmd)
    finally:
        orch.sys.platform = _orig


def test_bare_at_arg_is_quoted():
    out = _q("npx create-next-app@latest . --import-alias @/* --yes")
    assert "--import-alias '@/*'" in out
    # the package@version token is NOT an arg-position @ (no leading space+@)
    assert "create-next-app@latest" in out


def test_already_quoted_at_arg_untouched():
    cmd = 'npx create-next-app@latest . --import-alias "@/*" --yes'
    assert _q(cmd) == cmd  # the model's correct quoting is preserved


def test_at_prefixed_variants_generalize():
    assert "'@/src/*'" in _q("tool --alias @/src/*")
    assert "'@scope'" in _q("tool --name @scope")


def test_ps_constructs_left_untouched():
    # @( array, @{ hashtable, @" here-string, @$ splat-var — real PS syntax
    for construct in ("@(1,2)", "@{a=1}", "@$vars"):
        assert _q(f"cmd {construct}") == f"cmd {construct}"


def test_no_at_no_change():
    cmd = "npm install -D tailwindcss postcss autoprefixer"
    assert _q(cmd) == cmd


# ── B2. recommended/default menu option preferred ────────────────────────────


def test_select_follows_recommended_when_goal_is_silent():
    # shadcn-style menu: goal says nothing about the component library.
    choices = ["Base (Recommended)", "New York", "Custom"]
    idx = _decide_select(
        "Select a component library", choices, "add shadcn components", "add shadcn components"
    )
    assert choices[idx] == "Base (Recommended)"


def test_select_goal_signal_still_wins_over_recommended():
    # An explicit goal signal must still outweigh the generic recommended boost.
    choices = ["npm (Recommended)", "pnpm"]
    idx = _decide_select(
        "package manager", choices, "use pnpm for everything", "use pnpm for everything"
    )
    assert choices[idx] == "pnpm"


def test_select_empty_choices_safe():
    assert _decide_select("t", [], "g", "g") == 0
