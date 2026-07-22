"""
Verification tests for the DecisionGraph — every runtime choice as a typed node.

Pins the Predict → Observe → Compare → Update contract:
  - a decision closed with an observation matching its prediction → CONFIRMED
  - contradicting → DIVERGED (with error class + conclusions attached)
  - policy veto → BLOCKED (never executed)
  - retry/fix/recovery attempts are LINKED (typed edges), not listed

Run: python -m pytest tests/test_decisions.py -v
"""

import os

from src.decisions import (
    DecisionKind,
    DecisionLog,
    DecisionState,
    EdgeKind,
)


def _log() -> DecisionLog:
    return DecisionLog("run_test")


# ── FSM: Predict → Observe → Compare ─────────────────────────────────────────


def test_confirmed_when_observation_matches_prediction():
    log = _log()
    d = log.propose_step("step_0", "MODIFY", "pip install yt-dlp", ["yt-dlp installed"], attempt=0)
    assert d.state == DecisionState.PROPOSED
    log.close(d, run_ok=True, achieved=True, reason="installed", latency_s=1.2)
    assert d.state == DecisionState.CONFIRMED
    assert not d.diverged


def test_diverged_when_observation_contradicts_prediction():
    log = _log()
    d = log.propose_step("step_0", "MODIFY", "pip install yt-dlp", ["yt-dlp installed"], attempt=0)
    log.close(
        d,
        run_ok=False,
        achieved=False,
        reason="network unreachable",
        error_class="NETWORK_ERROR",
        conclusions=["CONSTRAINT: network unavailable"],
    )
    assert d.state == DecisionState.DIVERGED
    assert d.observation.error_class == "NETWORK_ERROR"
    assert d.conclusions == ["CONSTRAINT: network unavailable"]


def test_blocked_decision_never_executed():
    log = _log()
    d = log.propose_step("step_0", "MODIFY", "write_file|C:/x.exe|text", [], attempt=0)
    log.block(d, "SAFETY BLOCK: tracked executable")
    assert d.state == DecisionState.BLOCKED
    assert d.observation is None
    assert "SAFETY BLOCK" in d.policy_reason


# ── Graph structure: edges, not lists ─────────────────────────────────────────


def test_retry_chain_links_attempts():
    log = _log()
    d0 = log.propose_step("step_0", "MODIFY", "cmd-a", [], attempt=0)
    log.close(d0, run_ok=False, achieved=False, reason="fail")
    d1 = log.propose_step("step_0", "MODIFY", "cmd-b", [], attempt=1, source="executor_fix")
    assert d1.parent_id == d0.id
    assert d1.edge == EdgeKind.REPLACES.value
    assert d1.kind == DecisionKind.FIX
    chain = log.retry_chain("step_0")
    assert [d.id for d in chain] == [d0.id, d1.id]


def test_plain_retry_gets_retry_of_edge():
    log = _log()
    d0 = log.propose_step("step_3", "MODIFY", "cmd", [], attempt=0)
    d1 = log.propose_step("step_3", "MODIFY", "cmd --flag", [], attempt=1)
    assert d1.edge == EdgeKind.RETRY_OF.value
    assert d1.parent_id == d0.id


def test_recovery_step_links_to_failed_final_verify():
    log = _log()
    dv = log.propose_control(DecisionKind.FINAL_VERIFY, success_criteria=["tool on PATH"])
    log.close(dv, run_ok=True, achieved=False, reason="tool not on PATH")
    dr = log.propose_step("step_7", "RECOVER", "setx PATH ...", [], attempt=0, recovery_pass=True)
    assert dr.parent_id == dv.id
    assert dr.edge == EdgeKind.RECOVERS.value


# ── Stats: the Decision Quality projection ─────────────────────────────────────


def test_stats_first_shot_accuracy_and_divergence_index():
    log = _log()
    d0 = log.propose_step("step_0", "MODIFY", "a", [], attempt=0)
    log.close(d0, run_ok=True, achieved=True)
    d1 = log.propose_step("step_1", "MODIFY", "b", [], attempt=0)
    log.close(d1, run_ok=False, achieved=False, error_class="COMMAND_SYNTAX")
    d2 = log.propose_step("step_2", "MODIFY", "c", [], attempt=0)
    log.block(d2, "policy")
    s = log.stats()
    assert s["n_decisions"] == 3
    assert s["by_state"] == {"confirmed": 1, "diverged": 1, "blocked": 1}
    assert s["first_shot_accuracy"] == 0.5  # 1 confirmed / 2 closed
    assert s["blocked_by_policy"] == 1
    assert s["diverged_by_error_class"] == {"COMMAND_SYNTAX": 1}


def test_to_dict_is_json_serializable():
    import json

    log = _log()
    d = log.propose_step("step_0", "VERIFY", "yt-dlp --version", ["version printed"], attempt=0)
    log.close(d, run_ok=True, achieved=True, reason="yt-dlp 2026.1.1")
    payload = json.dumps(log.to_dict())
    assert "run_test_d1" in payload
    assert "first_shot_accuracy" in payload


# ── Integration: SystemState + telemetry carry the graph ─────────────────────


def test_systemstate_has_decision_log_and_telemetry_emits_it(tmp_path, monkeypatch):
    from src import config, telemetry
    from src.state import SystemState

    ss = SystemState(os.getcwd())
    d = ss.decisions.propose_step("step_0", "MODIFY", "echo hi", [], attempt=0)
    ss.decisions.close(d, run_ok=True, achieved=True)
    # telemetry no longer holds its own copy of the output directory: it reads
    # `config.TELEMETRY_DIR` per call, so config stays the single owner of the layout and a
    # relocated state root takes the telemetry with it. Redirect the owner, not the consumer.
    monkeypatch.setattr(config, "TELEMETRY_DIR", tmp_path)
    out = telemetry.record_run(ss, "test goal", verdict="COMPLETE")
    assert out is not None
    import json

    rec = json.loads(out.read_text(encoding="utf-8"))
    assert rec["decisions"]["stats"]["n_decisions"] == 1
    assert rec["decisions"]["nodes"][0]["state"] == "confirmed"
    assert "world" in rec
