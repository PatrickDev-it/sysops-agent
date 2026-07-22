"""A borrowed-oracle transport failure must degrade to the owned model, never crash the run.

Measured (agent_eval baseline, django case): the oracle connection was reset mid-response
(`ConnectionResetError [WinError 10054]`) during planning. That error is a raw OSError raised
while READING the body — not a `urllib.error.URLError` — so `Provider._post` did not catch it and
it propagated uncaught, killing the whole run and scoring a phantom capability FAIL. Two boundaries
close it: `_post` normalizes every transport failure into a typed `ProviderError` (the single HTTP
owner), and `model_router._complete` degrades a `ProviderError` FROM THE ORACLE to the owned 4B —
while a failure from an owned server still surfaces, never silently masked.
"""

import urllib.request

import pytest
from src.llm_backend import Completion, Provider, ProviderError


def _ok_completion() -> Completion:
    return Completion(
        text="ok",
        prompt_n=1,
        predicted_n=1,
        cache_n=0,
        prefill_ms=0.0,
        decode_tps=0.0,
        stop_type="",
    )


def test_connection_reset_becomes_provider_error(monkeypatch):
    """The django crash, pinned: a mid-response reset must be a typed ProviderError, not an OSError."""

    def _reset(*a, **k):
        raise ConnectionResetError(10054, "An existing connection was forcibly closed")

    monkeypatch.setattr(urllib.request, "urlopen", _reset)
    p = Provider("oracle", "http://127.0.0.1:9")
    with pytest.raises(ProviderError):
        p.complete("hi", n_predict=1)


def test_oracle_network_error_degrades_to_owned_nav(monkeypatch):
    """A ProviderError from the oracle degrades to the owned nav and the call still returns."""
    from src import model_router as mr

    class _Oracle(Provider):
        def complete(self, *a, **k):
            raise ProviderError("oracle connection failed")

    class _Nav(Provider):
        def complete(self, *a, **k):
            return _ok_completion()

    nav = _Nav("nav-4b", "http://127.0.0.1:8")
    monkeypatch.setattr(mr, "_nav", lambda: nav)
    oracle = _Oracle(mr._ORACLE_NAME, "http://127.0.0.1:9")

    out = mr._complete(oracle, "hi", template="supervisor.jinja", n_predict=8, sampler={})
    assert out.text == "ok"


def test_local_owned_server_failure_is_not_masked(monkeypatch):
    """A ProviderError from an OWNED server is a real fault — it must surface, not degrade forever."""
    from src import model_router as mr

    class _DeadNav(Provider):
        def complete(self, *a, **k):
            raise ProviderError("nav-4b unreachable")

    nav = _DeadNav("nav-4b", "http://127.0.0.1:8")
    monkeypatch.setattr(mr, "_nav", lambda: nav)

    with pytest.raises(ProviderError):
        mr._complete(nav, "hi", template="supervisor.jinja", n_predict=8, sampler={})


class _FakeClock:
    """Stands in for the `time` module inside model_router only.

    Patching `mr.time.monotonic` would mutate the stdlib module for every other consumer in
    the process, including pytest-timeout. Replacing the module reference keeps it local.
    """

    def __init__(self) -> None:
        self.t = 0.0

    def monotonic(self) -> float:
        return self.t

    def perf_counter(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def test_a_slow_endpoint_cannot_outlive_the_call_deadline(monkeypatch):
    """`urllib`'s timeout is per socket operation, not per request.

    A server that trickles one byte just inside REQUEST_TIMEOUT_S never trips it, and the four
    retry attempts around it had no aggregate bound — worst case a single planning call could
    occupy the agent indefinitely with no output and no way to observe why. The deadline is
    wall-clock over the whole logical call, retries included.

    Driven through the context-overflow path because that is the one that legitimately loops:
    it shrinks the budget and retries rather than surfacing, which is exactly the shape that
    could spin without a wall-clock bound.
    """
    from src import model_router as mr
    from src.llm_backend import ProviderContextError

    clock = _FakeClock()
    monkeypatch.setattr(mr, "time", clock)

    class _Slow(Provider):
        def complete(self, *a, **k):
            clock.t += mr.CALL_DEADLINE_S * 0.6  # each attempt burns most of the budget
            raise ProviderContextError("context exceeded")

    provider = _Slow("nav-4b", "http://127.0.0.1:8")

    with pytest.raises(ProviderError) as exc:
        mr._complete(provider, "x" * 4096, template="supervisor.jinja", n_predict=8192, sampler={})
    assert "deadline" in str(exc.value)
    assert clock.t > mr.CALL_DEADLINE_S


def test_the_deadline_does_not_fire_on_a_healthy_call(monkeypatch):
    """The guard must bound the pathological case without touching the normal one."""
    from src import model_router as mr

    clock = _FakeClock()
    monkeypatch.setattr(mr, "time", clock)

    class _Fast(Provider):
        def complete(self, *a, **k):
            clock.t += 0.25
            return _ok_completion()

    out = mr._complete(
        _Fast("nav-4b", "http://127.0.0.1:8"),
        "hi",
        template="supervisor.jinja",
        n_predict=8,
        sampler={},
    )
    assert out.text == "ok"


def test_backoff_is_deterministic_under_deterministic_mode(monkeypatch):
    """A random sleep would reintroduce exactly the run-to-run variation the seed removes."""
    from src import model_router as mr

    monkeypatch.setattr(mr, "DETERMINISTIC", True)
    assert mr._backoff(0) == mr._backoff(0) == 0.5
    assert mr._backoff(3) == 4.0

    monkeypatch.setattr(mr, "DETERMINISTIC", False)
    # base * (0.5 + random()) — for attempt 0 the base is 0.5, so the band is [0.25, 0.75).
    samples = [mr._backoff(0) for _ in range(50)]
    assert all(0.25 <= s < 0.75 for s in samples)
    assert len(set(samples)) > 1, "jitter must actually vary outside DETERMINISTIC"
    assert all(mr._backoff(10) <= 8.0 for _ in range(20)), "backoff must stay capped"
