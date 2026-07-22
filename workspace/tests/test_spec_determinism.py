"""Wall-clock is a reproducibility leak the seed does not cover.

`system_spec.build()` injects a `TODAY:` line into EVERY model prompt to defeat the model's
frozen-in-time priors. With a live date, two DETERMINISTIC runs on different days are two
different prompts, so a delta between them is not a pure effect — measurement noise dressed as
signal, which is exactly what a benchmark must not have.

The workspace absolute path — the leak the developer flagged — was already closed by
`workspace_paths.scrub` (see test_workspace_paths.py). The DATE is the leak that survived it.
Under DETERMINISTIC the date is pinned via `config.SPEC_DATE`; these tests guard both directions.
"""

import src.config
from src.knowledge import system_spec


class _Env:
    os_name = "TestOS"
    os_version = "1.0"
    shell = "sh"


def test_spec_date_is_pinned_when_configured(monkeypatch):
    """A pinned date is what makes a DETERMINISTIC run reproducible across days."""
    monkeypatch.setattr(system_spec, "_tool_version", lambda t: "")  # fast + host-independent
    monkeypatch.setattr(src.config, "SPEC_DATE", "2020-02-02")
    system_spec.reset()
    out = system_spec.build(_Env(), force=True)
    assert "TODAY: 2020-02-02" in out
    assert "and year 2020" in out  # the derived year must follow the pinned date, not the clock


def test_spec_date_is_live_when_not_pinned(monkeypatch):
    """Production keeps the live date — the grounding-on-reality purpose of system_spec."""
    from datetime import date

    monkeypatch.setattr(system_spec, "_tool_version", lambda t: "")
    monkeypatch.setattr(src.config, "SPEC_DATE", None)
    system_spec.reset()
    out = system_spec.build(_Env(), force=True)
    assert f"TODAY: {date.today().isoformat()}" in out


def test_pin_is_stable_across_two_builds(monkeypatch):
    """Two independent builds (fresh process = fresh cache) with the pin set must agree byte-for-byte."""
    monkeypatch.setattr(system_spec, "_tool_version", lambda t: "")
    monkeypatch.setattr(src.config, "SPEC_DATE", "2026-07-01")
    system_spec.reset()
    first = system_spec.build(_Env(), force=True)
    system_spec.reset()
    second = system_spec.build(_Env(), force=True)
    assert first == second
    assert "TODAY: 2026-07-01" in first
