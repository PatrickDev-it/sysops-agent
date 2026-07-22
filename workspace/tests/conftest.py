"""Single owner of the test suite's import path and of its isolation from production state.

IMPORT PATH. Eight test modules each opened with the same three lines — `sys.path.insert(0,
...)` computed from `__file__` — to make `src` importable. Eight copies of one fact, each of
which had to be re-counted whenever a file moved. pytest imports `conftest.py` before
collecting anything under its directory, so one insert here replaces all of them.

STATE ISOLATION. This file used to redirect `sys.path` and nothing else, which meant the test
suite and `benchmarks/run_suite.py` both opened the OPERATOR'S memory store. `Orchestrator.run`
calls `memory.clear_session_events()` on startup, so every benchmark run deleted the production
episodic log and wrote its own synthetic cases in its place — and those then appeared as
`history` in the next real run's planner prompt. The measurement contaminated the thing it
measured, in a way visible only as a planner that had somehow learned about `stress_frameworks`
cases nobody ran.

Redirecting `config.MEMORY_DIR` alone would not have worked before now: `memory.py` computed
`DB_PATH` and friends from it at IMPORT time, so config was the nominal owner of the layout and
memory the effective one. Those are functions now, resolved per call, which is what makes this
fixture possible at all.
"""

import sys
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parent.parent

if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))


_STATE_DIRS = ("MEMORY_DIR", "RUNTIME_DIR", "KB_MEMORY_DIR", "TELEMETRY_DIR", "BENCHMARK_DIR")


@pytest.fixture(scope="session")
def _state_root(tmp_path_factory):
    """One throwaway directory tree for the whole session, reaped with pytest's tmp root."""
    return tmp_path_factory.mktemp("sistemista_state")


@pytest.fixture(autouse=True)
def isolate_persistent_state(_state_root):
    """Redirect every on-disk store to the throwaway tree, BEFORE EACH TEST.

    Autouse, so isolation is never something a test opts into: the test that forgets is
    exactly the one that wipes the operator's memory.

    Re-applied per test rather than once per session, because a session-scoped redirect does
    not survive `importlib.reload(src.config)` — and `test_reproducibility.py` and
    `test_artifact_capture.py` both reload config to exercise import-time behaviour. A reload
    re-executes the module and rebinds MEMORY_DIR to the production path, silently
    un-isolating every test collected after it. That is not a hypothetical: it is what the
    first version of this fixture caught, as 439 errors.
    """
    from src import config

    saved = {name: getattr(config, name) for name in ("VAR", *_STATE_DIRS)}
    config.VAR = _state_root
    for name in _STATE_DIRS:
        path = _state_root / name.removesuffix("_DIR").lower()
        setattr(config, name, path)
        path.mkdir(parents=True, exist_ok=True)

    # Assert the redirect actually took. A module that re-derives its paths from `__file__`
    # at import time — the defect this suite already paid for once, in memory.py — would
    # escape the redirect silently, and the first symptom would be an empty episodic log on
    # the operator's machine.
    from src import memory

    production = (config.SRC.parent / "var" / "memory").resolve()
    assert memory._memory_dir().resolve() != production, (
        f"the memory store resolved to the production path {production}; some module froze "
        f"it at import time instead of reading config at call time"
    )

    yield _state_root

    for name, value in saved.items():
        setattr(config, name, value)
