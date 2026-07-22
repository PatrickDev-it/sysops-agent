"""What the supervisor puts in a prompt — tested without a model.

`supervisor.py` sat at 7% coverage because it "calls a model". It does, through exactly one
seam (`model_router`), and everything on this side of that seam is deterministic string
assembly that decides what leaves the machine. That is the part worth testing: when an oracle
is configured, this context crosses the network.

The workspace listing is the specific exposure. It enumerates every entry with its SIZE, and it
is interpolated into every planning call.
"""

import pytest
from src import supervisor as sup_mod
from src.supervisor import Supervisor, _workspace_context

from tests.fake_agent import FakeRouter


@pytest.fixture
def router(monkeypatch):
    fake = FakeRouter()
    calls = []

    def _supervisor_call(ctx):
        calls.append(ctx)
        return {"mode": "direct", "constraints": [], "success": [], "plan": []}

    def _verify_call(ctx):
        calls.append(ctx)
        return {"achieved": True, "reason": "ok", "next_action": ""}

    monkeypatch.setattr(sup_mod.model_router, "supervisor_call", _supervisor_call)
    monkeypatch.setattr(sup_mod.model_router, "verify_call", _verify_call)
    fake.calls = calls
    return fake


# ── The workspace listing ────────────────────────────────────────────────────


def test_an_empty_workspace_is_stated_explicitly(tmp_path):
    ctx = _workspace_context(str(tmp_path))
    assert "WORKSPACE_STATE: empty" in ctx


def test_a_missing_workspace_is_stated_explicitly(tmp_path):
    ctx = _workspace_context(str(tmp_path / "nope"))
    assert "WORKSPACE_EXISTS: no" in ctx


def test_ordinary_files_are_listed_with_their_size(tmp_path):
    (tmp_path / "main.py").write_text("print(1)")
    ctx = _workspace_context(str(tmp_path))
    assert "FILE main.py (8B)" in ctx


@pytest.mark.parametrize("name", [".env", "prod.env", "id_rsa", "credentials", "server.pem"])
def test_a_credential_store_never_has_its_size_disclosed(tmp_path, name):
    """File length is an information leak about a secret, and this listing reaches the planner
    prompt — and a remote oracle, when one is configured."""
    (tmp_path / name).write_text("SECRET_KEY=hunter2hunter2hunter2")
    ctx = _workspace_context(str(tmp_path))
    assert name in ctx, "the agent still needs to know the file is there in order to plan"
    assert "31B" not in ctx, "the size of a credential store was disclosed"
    assert "never read its contents" in ctx


def test_the_content_of_a_credential_store_never_appears(tmp_path):
    (tmp_path / ".env").write_text("DATABASE_URL=postgres://u:p@host/db")
    ctx = _workspace_context(str(tmp_path))
    assert "postgres://u:p@host/db" not in ctx


# ── The plan seam ────────────────────────────────────────────────────────────


def test_planning_passes_the_goal_and_the_workspace_state(router, tmp_path):
    (tmp_path / "package.json").write_text("{}")
    Supervisor().plan("add a health endpoint", str(tmp_path), "")
    assert router.calls, "the planner was never invoked"
    ctx = router.calls[0]
    assert ctx["goal"] == "add a health endpoint"
    assert "package.json" in ctx["workspace_state"]


def test_planning_never_ships_a_credential_size(router, tmp_path):
    (tmp_path / ".env").write_text("TOKEN=ghp_abcdefghijklmnopqrstuvwxyz1")
    Supervisor().plan("deploy the service", str(tmp_path), "")
    blob = str(router.calls[0])
    assert "ghp_abcdefghijklmnop" not in blob
    assert "(37B)" not in blob


def test_verification_is_given_the_declared_criteria(router, tmp_path):
    class _S:
        workspace = tmp_path

    Supervisor().verify(
        "create the manifest",
        _S(),
        success_criteria=[{"check": "file_has_content", "path": "package.json"}],
    )
    ctx = router.calls[-1]
    assert "package.json" in str(ctx.get("success_criteria", "")), (
        "the verifier was asked whether the goal was met without being told what would meet it"
    )
