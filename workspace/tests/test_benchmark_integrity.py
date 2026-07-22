"""A metric that asserts a capability without checking it is worse than an absent metric:
a reviewer reads it and stops looking.

`reports/leaderboard.json` compared four agents. Three of them — `claude-code`, `codex-cli`,
`openhands` — appear in no `.py` file in this repository and were never run. Seven of eleven
metrics were identical to sixteen significant digits, and `claude-code.overall` was exactly
`sistemista.overall + 0.01`. Meanwhile the only scorecards ever produced came from the `dry`
adapter, which executes nothing, at 0.53-0.70 overall over 16-40 cases.

These tests make that class of artifact impossible to produce again, rather than merely
forbidden by a comment.
"""

import pytest
from benchmarks.osbench.scoring.metrics import Scorecard
from benchmarks.osbench.scoring.report import FabricatedComparison, write_comparison
from src.config import ROOT

REPORTS = ROOT / "benchmarks" / "osbench" / "reports"


def _card(overall: float, *, executed: bool, adapter: str, n_cases: int = 16) -> Scorecard:
    metrics = {
        "autonomous_resolution_rate": overall,
        "safety": 1.0,
        "reasoning_quality": 0.4,
        "recovery_capability": 1.0,
        "reliability": overall,
    }
    return Scorecard(
        per_case=[],
        metrics=metrics,
        by_difficulty={},
        by_domain={},
        by_os={},
        overall=overall,
        n_cases=n_cases,
        n_runs=n_cases,
        adapter=adapter,
        executed=executed,
    )


def test_a_leaderboard_cannot_be_built_from_stubs():
    cards = {
        "sistemista": _card(0.86, executed=False, adapter="dry"),
        "claude-code": _card(0.87, executed=False, adapter="dry"),
    }
    with pytest.raises(FabricatedComparison, match="not executed"):
        write_comparison(cards)


def test_a_leaderboard_cannot_mix_executed_and_stub_agents():
    """The exact shape of the fabrication: one real agent, competitors that never ran."""
    cards = {
        "sistemista": _card(0.86, executed=True, adapter="live"),
        "claude-code": _card(0.87, executed=False, adapter="dry"),
    }
    with pytest.raises(FabricatedComparison) as e:
        write_comparison(cards)
    assert "claude-code" in str(e.value)


def test_a_leaderboard_needs_at_least_two_executed_agents():
    with pytest.raises(FabricatedComparison, match="at least two"):
        write_comparison({"sistemista": _card(0.86, executed=True, adapter="live")})


def test_agents_must_be_scored_on_the_same_cases():
    cards = {
        "a": _card(0.8, executed=True, adapter="live", n_cases=16),
        "b": _card(0.9, executed=True, adapter="live", n_cases=127),
    }
    with pytest.raises(FabricatedComparison, match="different case counts"):
        write_comparison(cards)


def test_a_scorecard_knows_whether_it_measured_anything():
    assert not Scorecard([], {}, {}, {}, {}, 0.0, 0, 0).executed
    assert Scorecard([], {}, {}, {}, {}, 0.0, 0, 0).adapter == "unknown"


def test_the_dry_adapter_declares_that_it_executes_nothing():
    from benchmarks.osbench.run import DryRunAdapter

    assert DryRunAdapter.executes is False


def test_no_leaderboard_survives_in_reports():
    """The fabricated file is quarantined in `_attic/`, with its arithmetic, not in reports/."""
    assert not (REPORTS / "leaderboard.json").exists()
    assert not (REPORTS / "leaderboard.md").exists()


def test_every_published_scorecard_declares_its_provenance():
    import json

    for f in REPORTS.glob("*scorecard_*.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        assert "is_measurement" in d, f"{f.name} does not say whether it measured anything"
        if not d["is_measurement"]:
            assert f.name.startswith("STUB_"), (
                f"{f.name} scores a stub but its filename does not say so"
            )
