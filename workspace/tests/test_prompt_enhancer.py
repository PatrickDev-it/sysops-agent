"""The enhancer is one unconditional model call per task; the off-switch must be real.

`SISTEMISTA_ENHANCER=0` exists so an A/B run can measure whether the specialist brief
earns its latency. Off must mean NO model call — not a call whose result is discarded —
and the deterministic fallback brief must still be complete, because supervisor.jinja
and executor.jinja are framed with it unconditionally.
"""

from src import config, model_router, prompt_enhancer


def test_enhancer_off_skips_the_model_and_uses_the_fallback(monkeypatch):
    def _must_not_be_called(ctx):
        raise AssertionError("enhance_call must not run with SISTEMISTA_ENHANCER=0")

    monkeypatch.setattr(config, "ENHANCER", False)
    monkeypatch.setattr(model_router, "enhance_call", _must_not_be_called)

    brief = prompt_enhancer.enhance("install ripgrep", system_spec="OS: Windows")
    assert brief["specialist_role"] == prompt_enhancer._FALLBACK_ROLE
    assert brief["refined_objective"] == "install ripgrep"
    assert brief["key_considerations"] == []
    # The compiled block must render from the fallback alone.
    assert "install ripgrep" in prompt_enhancer.compile_brief(brief)


def test_enhancer_on_still_falls_back_when_the_model_fails(monkeypatch):
    monkeypatch.setattr(config, "ENHANCER", True)
    monkeypatch.setattr(
        model_router, "enhance_call", lambda ctx: (_ for _ in ()).throw(RuntimeError("server down"))
    )

    brief = prompt_enhancer.enhance("fix PATH")
    assert brief["specialist_role"] == prompt_enhancer._FALLBACK_ROLE
    assert brief["refined_objective"] == "fix PATH"


def test_enhancer_flag_defaults_on(monkeypatch):
    monkeypatch.delenv("SISTEMISTA_ENHANCER", raising=False)
    assert config._env_flag("SISTEMISTA_ENHANCER", True) is True
