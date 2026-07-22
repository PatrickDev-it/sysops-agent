"""The environment is hostile input, and config is the only place that parses it.

`_env_flag` was `os.environ.get(name, default) not in ("0", "false", "no")` — case-sensitive,
three falsey spellings. So `"False"`, `"FALSE"`, `"off"`, `"N"` and `""` all evaluated to True,
on the six flags that govern whether the oracle is contacted, whether a run is deterministic,
and which executor path is taken.

The operational consequence is the one worth pinning: someone setting `SISTEMISTA_ORACLE=False`
is trying to stop workspace context from leaving the machine. They got the oracle enabled, with
no warning. A knob whose value cannot be parsed is a knob whose setting is unknown, so parsing
now fails loudly instead of guessing.
"""

import pytest
from src import config

# NOTE ON IMPORT STYLE: everything below reaches config through the MODULE, never through a
# `from src.config import X` binding. `test_reproducibility.py` and `test_artifact_capture.py`
# call `importlib.reload(src.config)` to exercise import-time behaviour, and a reload rebuilds
# every class the module defines — including ConfigError. A test holding an import-time
# reference would then be asserting against a class object the code under test no longer
# raises, and would fail depending only on collection order.


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "True", "yes", "Y", "on", "  on  ", "t"])
def test_truthy_spellings(monkeypatch, raw):
    monkeypatch.setenv("SIST_TEST_FLAG", raw)
    assert config._env_flag("SIST_TEST_FLAG", False) is True


@pytest.mark.parametrize("raw", ["0", "false", "FALSE", "False", "no", "N", "off", "Off", "", "  "])
def test_falsey_spellings_that_used_to_read_as_true(monkeypatch, raw):
    """Every value here except "0", "false" and "no" was previously True."""
    monkeypatch.setenv("SIST_TEST_FLAG", raw)
    assert config._env_flag("SIST_TEST_FLAG", True) is False


def test_the_exact_reported_case(monkeypatch):
    """`SISTEMISTA_ORACLE=False` must disable the oracle, not enable it."""
    monkeypatch.setenv("SISTEMISTA_ORACLE", "False")
    assert config._env_flag("SISTEMISTA_ORACLE", True) is False


@pytest.mark.parametrize("raw", ["maybe", "2", "disabled", "sì", "-1"])
def test_an_unparsable_flag_raises_rather_than_defaulting(monkeypatch, raw):
    monkeypatch.setenv("SIST_TEST_FLAG", raw)
    with pytest.raises(config.ConfigError) as exc:
        config._env_flag("SIST_TEST_FLAG", True)
    assert "SIST_TEST_FLAG" in str(exc.value), "the error must name the offending variable"


def test_absent_flag_uses_the_declared_default(monkeypatch):
    monkeypatch.delenv("SIST_TEST_FLAG", raising=False)
    assert config._env_flag("SIST_TEST_FLAG", True) is True
    assert config._env_flag("SIST_TEST_FLAG", False) is False


def test_int_parsing_names_the_variable(monkeypatch):
    """A bare int() raised from an import statement, naming config.py rather than the typo."""
    monkeypatch.setenv("SIST_TEST_PORT", "80a0")
    with pytest.raises(config.ConfigError) as exc:
        config._env_int("SIST_TEST_PORT", 8090)
    assert "SIST_TEST_PORT" in str(exc.value)


def test_int_bounds_are_enforced(monkeypatch):
    monkeypatch.setenv("SIST_TEST_PORT", "99999")
    with pytest.raises(config.ConfigError):
        config._env_int("SIST_TEST_PORT", 8090, minimum=1, maximum=65535)


def test_float_parsing_rejects_prose(monkeypatch):
    monkeypatch.setenv("SIST_TEST_T", "five")
    with pytest.raises(config.ConfigError):
        config._env_float("SIST_TEST_T", 2.0)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://127.0.0.1:8081", True),
        ("http://localhost:8081", True),
        ("http://[::1]:8081", True),
        ("https://oracle.corp.example", False),
        ("http://10.0.0.5:8081", False),
        ("http://evil.example", False),
    ],
)
def test_loopback_detection(url, expected):
    assert config._is_loopback(url) is expected
