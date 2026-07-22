"""The audit trail must exist in production, survive a crash, and never carry a credential.

`trace.begin()` used to disable itself unless SISTEMISTA_TRACE_DIR was set, and the only caller
that set it was `benchmarks/run_suite.py`. Every emit in the product — confinement blocks,
refused writes, coder-gate verdicts, oracle degradations, every model call — was therefore a
guaranteed no-op for a real user. An agent that runs shell commands on a live host kept no
record of what it ran.

`memory.clear_session_events()` compounded it: called on every startup, it executed
`DELETE FROM events`, so the one remaining per-command record was wiped by the next run.
"""

import json

import pytest
from src import config, memory, trace
from src.verdict import RunVerdict


@pytest.fixture
def started(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VAR", tmp_path)
    monkeypatch.delenv("SISTEMISTA_TRACE_DIR", raising=False)
    path = trace.begin("run_20260720T101500Z_abcd1234")
    yield path
    trace.end()


def _records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_the_trail_is_on_without_any_environment_variable(started):
    """The whole defect in one assertion: no env var, and the trail must still exist."""
    assert started is not None and started.exists()
    assert trace.active()


def test_it_defaults_under_the_relocatable_state_root(started, tmp_path):
    assert started.parent == tmp_path / "trace"


def test_records_carry_an_absolute_utc_timestamp_and_an_order(started):
    """A float offset from process start cannot be correlated with a syslog line."""
    trace.emit("exec", command="echo one")
    trace.emit("exec", command="echo two")
    recs = _records(started)
    assert [r["seq"] for r in recs] == [0, 1]
    for r in recs:
        assert r["ts"].endswith("+00:00") and r["ts"][:4].isdigit()
        assert r["run_id"] == "run_20260720T101500Z_abcd1234"


def test_credentials_never_reach_the_trail(started):
    """session.run traces the full command line; `git clone https://user:token@host` was
    landing in the record verbatim."""
    trace.emit("exec", command="git clone https://alice:ghp_secretvaluehere123@github.com/o/r")  # gitleaks:allow  # fmt: skip
    trace.emit("llm", output="export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIK7MDENGbPxRfiCY")  # gitleaks:allow  # fmt: skip
    blob = started.read_text(encoding="utf-8")
    assert "ghp_secretvaluehere123" not in blob
    assert "wJalrXUtnFEMI" not in blob
    assert "github.com/o/r" in blob, "redaction must not destroy the operational context"


def test_a_second_begin_never_truncates_an_existing_trail(tmp_path, monkeypatch):
    """`write_text("")` on begin destroyed an existing file for the same run id."""
    monkeypatch.setattr(config, "VAR", tmp_path)
    monkeypatch.delenv("SISTEMISTA_TRACE_DIR", raising=False)
    first = trace.begin("run_dup")
    trace.emit("exec", command="echo original")
    trace.end()

    assert trace.begin("run_dup") is None, "a colliding run id must refuse, not overwrite"
    assert "echo original" in first.read_text(encoding="utf-8")


def test_an_active_trail_cannot_be_stolen_by_a_nested_begin(tmp_path, monkeypatch):
    """The benchmark harness begins the trail per task, then `Orchestrator.run` begins its own.
    Last-wins moved every event to `var/trace/` and left the harness file at 0 bytes — the
    per-call ledger the suite exists to produce. The nested begin must refuse, and the events
    that follow must land in the trail that was already open."""
    monkeypatch.setattr(config, "VAR", tmp_path)
    monkeypatch.delenv("SISTEMISTA_TRACE_DIR", raising=False)
    harness_dir = tmp_path / "bench_traces"
    harness = trace.begin("T01", harness_dir)

    assert trace.begin("run_20260720T073252Z_a088c9d1") is None
    trace.emit("exec", command="echo after-nested-begin")
    trace.end()

    recs = _records(harness)
    assert any(r["kind"] == "trace_begin_ignored" for r in recs), (
        "the refusal must leave a record where the events actually went"
    )
    assert any(r.get("command") == "echo after-nested-begin" for r in recs)
    assert all(r["run_id"] == "T01" for r in recs)
    assert not (tmp_path / "trace").exists(), "no second trail may be created"


def test_emit_is_inert_and_silent_before_begin():
    trace.end()
    trace.emit("exec", command="echo nothing")  # must not raise
    assert not trace.active()


def test_session_events_survive_the_next_run(tmp_path, monkeypatch):
    """`clear_session_events()` ran on every startup and deleted the only per-command record
    of what the agent did to the host."""
    monkeypatch.setattr(config, "MEMORY_DIR", tmp_path / "memory")
    memory.init_db()
    memory.save_event(
        goal="first goal",
        cwd=str(tmp_path),
        command="echo first",
        stdout="ok",
        exit_code=0,
        outcome="success",
    )

    src = (config.SRC / "orchestrator.py").read_text(encoding="utf-8")
    assert "memory.clear_session_events()" not in src, (
        "startup must not delete the event history; scoping reads to the current run is a "
        "query concern, not a reason to destroy the record"
    )

    memory.init_db()  # a second run starts here
    assert any(e["command"] == "echo first" for e in memory.get_recent_events(n=10))


def test_stored_commands_are_redacted(tmp_path, monkeypatch):
    """The events table is read back into the planner prompt as `history`."""
    monkeypatch.setattr(config, "MEMORY_DIR", tmp_path / "memory")
    memory.init_db()
    memory.save_event(
        goal="deploy",
        cwd=str(tmp_path),
        command="curl -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.e30.sig' x",  # gitleaks:allow
        stdout="TOKEN=ghp_abcdefghijklmnopqrstuvwxyz12",  # gitleaks:allow
        exit_code=0,
        outcome="success",
    )
    stored = str(memory.get_recent_events(n=5))
    assert "eyJhbGciOiJIUzI1NiJ9" not in stored
    assert "ghp_abcdefghijklmnop" not in stored


def test_every_verdict_maps_to_a_distinct_exit_code():
    """The process used to exit 0 whether it completed, refused, or gave up."""
    codes = {v: v.exit_code for v in RunVerdict}
    assert codes[RunVerdict.COMPLETE] == 0
    assert len(set(codes.values())) == len(RunVerdict), "verdicts must be distinguishable"
    assert all(c != 0 for v, c in codes.items() if v is not RunVerdict.COMPLETE)
