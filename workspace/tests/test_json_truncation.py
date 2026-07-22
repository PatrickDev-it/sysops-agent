"""GBNF constrains every token it emits, so a COMPLETED generation is well-formed JSON.
It cannot close an object that ran out of budget. These tests pin that boundary — found in
the wild on T43, where the planner looped enumerating event IDs until it hit 4096 tokens."""

import pytest
from src import model_router as mr
from src.llm_backend import Completion


class _StubProvider:
    """Returns a scripted Completion per call, recording the requested budgets."""

    name = "stub"

    def __init__(self, *completions):
        self._queue = list(completions)
        self.budgets = []

    def complete(self, prompt, *, n_predict, stop=None, json_schema=None, **sampler):
        self.budgets.append(n_predict)
        return self._queue.pop(0)


SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}}


def test_complete_generation_parses(monkeypatch):
    p = _StubProvider(Completion(text='{"a": "ok"}', stop_type="eos"))
    monkeypatch.setattr(mr, "_render", lambda *_a, **_k: "prompt")
    assert mr._json_call(p, "t.jinja", {}, n_predict=512, schema=SCHEMA, sampler={}) == {"a": "ok"}
    assert p.budgets == [512]


def test_truncation_retries_once_with_double_budget(monkeypatch):
    p = _StubProvider(
        Completion(text='{"a": "trunc', stop_type="limit"),
        Completion(text='{"a": "ok"}', stop_type="eos"),
    )
    monkeypatch.setattr(mr, "_render", lambda *_a, **_k: "prompt")
    assert mr._json_call(p, "t.jinja", {}, n_predict=512, schema=SCHEMA, sampler={}) == {"a": "ok"}
    assert p.budgets == [512, 1024], "the retry must widen the budget, not repeat it"


def test_truncation_twice_fails_loudly(monkeypatch):
    """A model that truncates twice is looping, not planning. Returning a stub here would
    hide the loop behind an empty plan — the failure mode this whole trace exists to expose."""
    p = _StubProvider(
        Completion(text='{"a": "trunc', stop_type="limit"),
        Completion(text='{"a": "still trunc', stop_type="limit"),
    )
    monkeypatch.setattr(mr, "_render", lambda *_a, **_k: "prompt")
    with pytest.raises(RuntimeError, match="looping, not planning"):
        mr._json_call(p, "t.jinja", {}, n_predict=512, schema=SCHEMA, sampler={})


def test_retry_budget_is_capped(monkeypatch):
    p = _StubProvider(
        Completion(text="{", stop_type="limit"),
        Completion(text='{"a": "ok"}', stop_type="eos"),
    )
    monkeypatch.setattr(mr, "_render", lambda *_a, **_k: "prompt")
    mr._json_call(p, "t.jinja", {}, n_predict=6144, schema=SCHEMA, sampler={})
    assert p.budgets == [6144, 8192], "must not double past the ctx budget"


def test_truncated_property_keys_on_stop_type():
    assert Completion(text="", stop_type="limit").truncated
    assert not Completion(text="", stop_type="eos").truncated
    assert not Completion(text="", stop_type="word").truncated
