"""The oracle URL decides where everything the agent knows is sent, and what comes back is executed.

The prompts crossing this boundary carry the goal, the workspace listing, the terminal
transcript, the OS username and home directory, and the raw stdout of DISCOVERY steps — which
is whatever the plan happened to probe. The reply is a PLAN that the orchestrator turns into
shell commands. So an attacker who controls this URL gets exfiltration and remote code
execution in one move, and the only admission test used to be `GET /health` answering
`{"status":"ok"}` — satisfiable by any HTTP server in one line, over cleartext, unauthenticated.

Loopback keeps its old ergonomics: the parent agent owns that process and the bytes never leave
the machine. Anything else must be encrypted and authenticated, or the agent refuses to start.
"""

import pytest
from src import config
from src.llm_backend import Provider

# NOTE ON IMPORT STYLE: everything below reaches config through the MODULE, never through a
# `from src.config import X` binding. `test_reproducibility.py` and `test_artifact_capture.py`
# call `importlib.reload(src.config)` to exercise import-time behaviour, and a reload rebuilds
# every class the module defines — including ConfigError. A test holding an import-time
# reference would then be asserting against a class object the code under test no longer
# raises, and would fail depending only on collection order.


def _policy(monkeypatch, *, enabled=True, url="http://127.0.0.1:8081", token=""):
    monkeypatch.setattr(config, "ORACLE_ENABLED", enabled)
    monkeypatch.setattr(config, "ORACLE_URL", url)
    monkeypatch.setattr(config, "ORACLE_TOKEN", token)
    return config._assert_oracle_transport_is_safe


def test_loopback_http_stays_allowed(monkeypatch):
    """Requiring TLS to reach 127.0.0.1 would be ceremony, not security."""
    _policy(monkeypatch, url="http://127.0.0.1:8081")()
    _policy(monkeypatch, url="http://localhost:8081")()


def test_remote_cleartext_is_refused(monkeypatch):
    check = _policy(monkeypatch, url="http://oracle.corp.example", token="s3cret")
    with pytest.raises(config.ConfigError) as exc:
        check()
    assert "https" in str(exc.value)


def test_remote_https_without_a_credential_is_refused(monkeypatch):
    """An unauthenticated endpoint that returns executable plans is an unauthenticated
    code-execution channel."""
    check = _policy(monkeypatch, url="https://oracle.corp.example", token="")
    with pytest.raises(config.ConfigError) as exc:
        check()
    assert "SISTEMISTA_ORACLE_TOKEN" in str(exc.value)


def test_remote_https_with_a_credential_is_allowed(monkeypatch):
    _policy(monkeypatch, url="https://oracle.corp.example", token="s3cret")()


def test_a_disabled_oracle_is_not_policed(monkeypatch):
    """Nothing is sent, so the transport cannot leak. This is the escape hatch the error
    messages point at."""
    _policy(monkeypatch, enabled=False, url="http://evil.example", token="")()


def test_the_credential_is_actually_sent():
    p = Provider("oracle", "https://oracle.corp.example", token="s3cret")
    assert p._headers["Authorization"] == "Bearer s3cret"


def test_no_credential_means_no_authorization_header():
    """An owned loopback server needs no credential; do not invent one."""
    p = Provider("nav-4b", "http://127.0.0.1:8090")
    assert "Authorization" not in p._headers
