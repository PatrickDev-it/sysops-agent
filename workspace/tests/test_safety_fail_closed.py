import pytest
from src import model_router
from src.tools import safety_gate


def test_router_failure_is_not_reported_safe(monkeypatch):
    monkeypatch.setattr(model_router, "_nav", lambda: object())
    monkeypatch.setattr(
        model_router,
        "_json_call",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    result = model_router.safety_call({"goal": "change the host"})

    assert result["risk"] != safety_gate.SAFE


def test_classifier_exception_fails_closed(monkeypatch):
    monkeypatch.setattr(
        safety_gate.model_router,
        "safety_call",
        lambda ctx: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    risk, reason = safety_gate.classify("change the host")

    assert risk == safety_gate.RECOVERABLE
    assert "unavailable" in reason


@pytest.mark.parametrize("risk", ["", "UNKNOWN", "safe-ish"])
def test_malformed_classifier_output_never_opens_the_gate(monkeypatch, risk):
    monkeypatch.setattr(
        safety_gate.model_router,
        "safety_call",
        lambda ctx: {"risk": risk, "reason": "bad output"},
    )

    classified, _ = safety_gate.classify("change the host")

    assert classified == safety_gate.RECOVERABLE
