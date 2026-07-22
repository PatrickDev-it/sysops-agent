"""A benchmark that is not reproducible measures nothing.

The planner sampled at `temperature=0.7, top_k=20, top_p=0.8` and no seed was ever pinned.
Two 10-task pilots were therefore two draws from a stochastic process, and the
"prediction / before / after / verdict" table that compared them compared samples, not
configurations. Three "confirmed" and three "falsified" were six draws. An entire measurement
cycle was spent reading noise as signal.

Fixing the seed is necessary and NOT sufficient. MEASURED against llama-server (Qwen3-0.6B,
greedy, `seed=42`, same prompt, three calls):

    cache_prompt = true   ->  2 distinct outputs   (cache_n [0, 7, 7])
    cache_prompt = false  ->  1 distinct output    (cache_n [0, 0, 0])

A prefix-cache hit changes the prefill batch shape; the batch shape changes the order of
floating-point reductions; the logits move. So DETERMINISTIC mode disables the prefix cache
too, and pays for it: prefill returns to ~608 ms from ~16.4 ms. A deterministic run's latency
is therefore not comparable with production latency, and must never be quoted as such.
"""

import importlib

import pytest
from src.config import SRC


def _config(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import src.config

    return importlib.reload(src.config)


def test_production_default_is_stochastic_and_unseeded(monkeypatch):
    monkeypatch.delenv("SISTEMISTA_DETERMINISTIC", raising=False)
    monkeypatch.delenv("SISTEMISTA_SEED", raising=False)
    cfg = _config(monkeypatch)
    assert cfg.DETERMINISTIC is False
    assert cfg.SEED is None
    # A planner that always emits the same plan cannot escape a local optimum on a retry.
    assert cfg.PLANNING["temperature"] == 0.7


def test_deterministic_mode_is_greedy_everywhere_and_seeded(monkeypatch):
    cfg = _config(monkeypatch, SISTEMISTA_DETERMINISTIC="1")
    assert cfg.SEED == 42
    for preset in (cfg.PLANNING, cfg.STRUCTURED, cfg.GREEDY):
        assert preset["temperature"] == 0.0
        assert preset["top_k"] == 1


def test_seed_is_overridable(monkeypatch):
    cfg = _config(monkeypatch, SISTEMISTA_DETERMINISTIC="1", SISTEMISTA_SEED="1234")
    assert cfg.SEED == 1234


def test_deterministic_mode_disables_the_prefix_cache(monkeypatch):
    """The measurement above, pinned: the seed alone leaves the cache free to move the logits."""
    src = (SRC / "model_router.py").read_text(encoding="utf-8")
    assert "cache_prompt=not DETERMINISTIC" in src, (
        "DETERMINISTIC mode must disable the prefix cache: a cache hit changes the prefill "
        "batch shape and therefore the logits, so a fixed seed does not suffice"
    )


def test_the_provider_only_sends_a_seed_when_one_is_set(monkeypatch):
    """An unseeded production run must not silently become deterministic."""
    from src.llm_backend import Provider

    sent = {}

    class _P(Provider):
        def _post(self, path, body, timeout):
            sent.update(body)
            return {"content": "{}", "timings": {}}

    p = _P("t", "http://x")
    p.complete("hi", n_predict=1)
    assert "seed" not in sent
    p.complete("hi", n_predict=1, seed=7)
    assert sent["seed"] == 7


@pytest.fixture(autouse=True)
def _restore():
    yield
    import src.config

    importlib.reload(src.config)
