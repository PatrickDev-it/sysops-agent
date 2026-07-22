"""The eval pipeline must resolve llama-server from PORTABLE sources, never a hardcoded external
path. A benchmark that only runs on one machine (because the binary path is baked into source) is
not reproducible — it is the single biggest epistemic limit a measurement can have.

Resolution order: SISTEMISTA_LLAMA_SERVER_BIN → vendored workspace/bin → PATH → a loud, named miss.
"""

from pathlib import Path

from src import config


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("SISTEMISTA_LLAMA_SERVER_BIN", str(Path("X:/custom/llama-server.exe")))
    assert config._resolve_llama_server_bin() == Path("X:/custom/llama-server.exe")


def test_path_fallback_when_no_override_and_not_vendored(monkeypatch):
    # Assumes workspace/bin/llama-server.exe is NOT vendored in this checkout (it is gitignored;
    # only the README is tracked). If it were vendored, that would legitimately win over PATH.
    monkeypatch.delenv("SISTEMISTA_LLAMA_SERVER_BIN", raising=False)
    monkeypatch.setattr(config.shutil, "which", lambda name: "C:/tools/llama-server.exe")
    assert config._resolve_llama_server_bin() == Path("C:/tools/llama-server.exe")


def test_no_binary_returns_loud_vendored_path(monkeypatch):
    monkeypatch.delenv("SISTEMISTA_LLAMA_SERVER_BIN", raising=False)
    monkeypatch.setattr(config.shutil, "which", lambda name: None)
    got = config._resolve_llama_server_bin()
    assert got.parent.name == "bin"
    assert got.name.startswith("llama-server")
    assert not got.exists()  # the point: a miss is a non-existent path that fails loudly, named


def test_no_hardcoded_external_path_ever_returns(monkeypatch):
    """Regression guard: the external Cowork path that made the pipeline non-portable must not return."""
    monkeypatch.delenv("SISTEMISTA_LLAMA_SERVER_BIN", raising=False)
    monkeypatch.setattr(config.shutil, "which", lambda name: None)
    got = str(config._resolve_llama_server_bin())
    assert "Cowork" not in got
    assert "Downloads" not in got
