"""A re-plan that repeats the plan it replaced must be visible in the trace.

Re-planning is the single most expensive thing the runtime does: on the 48-task baseline,
`supervisor.jinja` accounted for 870s of 1493s of model time, and 53 of its 101 calls were
re-plans, each regenerating the WHOLE plan rather than repairing it. Whether that spend buys
anything is decided by one question — does the new plan differ from the old one? — and the
trace could not answer it: the raw `output` field caps at 1200 characters and 82 of 86
planner outputs exceeded it.

The fingerprint is the instrument. These tests pin what it must and must not distinguish,
because a digest that changes on cosmetic edits would make every re-plan look productive.
"""

import json

import pytest
from src import config, model_router, trace


def _plan(*launchers, mode="direct", reason="because"):
    return {
        "mode": mode,
        "goal": "g",
        "reason": reason,
        "plan": [
            {"launcher": ln, "step_type": "MODIFY", "objective": f"do {ln}"} for ln in launchers
        ],
    }


def test_same_steps_hash_the_same_despite_different_prose():
    a = _plan("echo one", "echo two", reason="first attempt")
    b = _plan("echo one", "echo two", reason="a completely different explanation")
    assert model_router._plan_fingerprint(a) == model_router._plan_fingerprint(b)


def test_different_commands_hash_differently():
    a = _plan("echo one", "echo two")
    b = _plan("echo one", "echo THREE")
    assert model_router._plan_fingerprint(a) != model_router._plan_fingerprint(b)


def test_a_dropped_step_changes_the_fingerprint():
    assert model_router._plan_fingerprint(_plan("a", "b")) != model_router._plan_fingerprint(
        _plan("a")
    )


def test_step_type_is_part_of_the_identity():
    a = _plan("probe.exe")
    b = json.loads(json.dumps(a))
    b["plan"][0]["step_type"] = "DISCOVERY"
    assert model_router._plan_fingerprint(a) != model_router._plan_fingerprint(b)


def test_a_non_plan_object_has_no_fingerprint():
    assert model_router._plan_fingerprint({"achieved": True, "reason": "ok"}) == ""


@pytest.fixture
def trail(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VAR", tmp_path)
    monkeypatch.delenv("SISTEMISTA_TRACE_DIR", raising=False)
    path = trace.begin("run_fingerprint")
    yield path
    trace.end()


def _records(path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln]


def test_an_identical_replan_is_detectable_from_the_trace_alone(trail):
    """The end-to-end point: two planner calls, same steps — the trace must show it."""
    model_router._traced("supervisor.jinja", _plan("echo one", reason="attempt 1"))
    model_router._traced("supervisor.jinja", _plan("echo one", reason="attempt 2, re-planned"))

    plans = [r for r in _records(trail) if r["kind"] == "plan"]
    assert len(plans) == 2
    assert plans[0]["fingerprint"] == plans[1]["fingerprint"], (
        "a re-plan that proposes the same steps must be recognisable as such"
    )
    assert plans[0]["n_steps"] == 1


def test_a_verify_result_emits_no_plan_record(trail):
    model_router._traced("verify.jinja", {"achieved": True, "reason": "ok", "action": ""})
    assert [r for r in _records(trail) if r["kind"] == "plan"] == []
