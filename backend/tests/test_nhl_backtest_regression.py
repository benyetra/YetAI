"""Offline regression gates for NHL quick backtest metrics (no network/DB)."""

from pathlib import Path

import pytest

from app.services.etl.nhl.backtest.metrics import (
    DEFAULT_NHL_BACKTEST_TOLERANCES,
    check_metrics_against_baseline,
    summarize_nhl_backtest_metrics,
)
from app.services.etl.nhl.backtest.runner import score_synthetic_rows
from app.services.etl.nhl.backtest.scorer import NHLBacktestScorer

FIXTURE_BASELINE = (
    Path(__file__).resolve().parent / "fixtures" / "nhl_backtest_quick_baseline.json"
)


def _synthetic_nested_metrics(
    *,
    goalie_mae: float = 3.5,
    sog_mae: float = 1.2,
    totals_mae: float = 0.8,
    ou_hit_rate: float = 0.52,
) -> dict:
    return {
        "goalie_metrics": {"n_goalie": 10, "goalie_mae": goalie_mae},
        "sog_metrics": {"n_sog": 20, "sog_mae": sog_mae},
        "totals_metrics": {"n_totals": 5, "totals_mae": totals_mae},
        "aggregate_ou": {"ou_hit_rate": ou_hit_rate, "ou_n": 30},
    }


def _build_scorer_from_synthetic_rows() -> NHLBacktestScorer:
    rows = [
        {"market": "goalie", "predicted": 28.0, "actual": 30, "line": 27.5},
        {"market": "goalie", "predicted": 26.0, "actual": 25, "line": 26.5},
        {"market": "sog", "predicted": 3.5, "actual": 4, "line": 3.5},
        {"market": "sog", "predicted": 2.0, "actual": 2, "line": 2.5},
        {"market": "totals", "predicted": 6.2, "actual": 6, "line": 6.0},
        {"market": "totals", "predicted": 5.8, "actual": 7, "line": 6.5},
    ]
    return score_synthetic_rows(rows)


def test_summarize_nhl_backtest_metrics_from_nested_dict():
    summary = summarize_nhl_backtest_metrics(_synthetic_nested_metrics())
    assert summary["goalie_mae"] == pytest.approx(3.5)
    assert summary["sog_mae"] == pytest.approx(1.2)
    assert summary["totals_mae"] == pytest.approx(0.8)
    assert summary["ou_hit_rate"] == pytest.approx(0.52)


def test_summarize_nhl_backtest_metrics_from_scorer():
    scorer = _build_scorer_from_synthetic_rows()
    summary = summarize_nhl_backtest_metrics(scorer)
    assert summary["n_goalie"] == 2
    assert summary["n_sog"] == 2
    assert summary["n_totals"] == 2
    assert "goalie_mae" in summary
    assert "ou_hit_rate" in summary


def test_scorer_goalie_mae_and_ou():
    scorer = NHLBacktestScorer()
    scorer.add_goalie_result(28.0, 30, saves_line=27.5)
    scorer.add_goalie_result(26.0, 25, saves_line=26.5)
    goalie = scorer.compute_goalie_metrics()
    assert goalie["goalie_mae"] == pytest.approx(1.5)
    assert goalie["goalie_ou_hit_rate"] == pytest.approx(1.0)


def test_check_metrics_same_as_baseline_passes():
    import json

    with FIXTURE_BASELINE.open(encoding="utf-8") as f:
        metrics = json.load(f)["metrics"]
    result = check_metrics_against_baseline(
        metrics, FIXTURE_BASELINE, DEFAULT_NHL_BACKTEST_TOLERANCES
    )
    assert result.passed
    assert result.failures == []


def test_check_metrics_better_than_baseline_passes():
    better = {
        "goalie_mae": 3.0,
        "sog_mae": 1.0,
        "totals_mae": 0.6,
        "ou_hit_rate": 0.58,
    }
    result = check_metrics_against_baseline(better, FIXTURE_BASELINE)
    assert result.passed


def test_check_metrics_worse_goalie_mae_fails():
    worse = {
        "goalie_mae": 5.0,
        "sog_mae": 1.2,
        "totals_mae": 0.8,
        "ou_hit_rate": 0.52,
    }
    result = check_metrics_against_baseline(worse, FIXTURE_BASELINE)
    assert not result.passed
    assert any("goalie_mae" in msg for msg in result.failures)


def test_check_metrics_worse_sog_mae_fails():
    worse = {
        "goalie_mae": 3.5,
        "sog_mae": 2.0,
        "totals_mae": 0.8,
        "ou_hit_rate": 0.52,
    }
    result = check_metrics_against_baseline(worse, FIXTURE_BASELINE)
    assert not result.passed
    assert any("sog_mae" in msg for msg in result.failures)


def test_check_metrics_worse_totals_mae_fails():
    worse = {
        "goalie_mae": 3.5,
        "sog_mae": 1.2,
        "totals_mae": 1.5,
        "ou_hit_rate": 0.52,
    }
    result = check_metrics_against_baseline(worse, FIXTURE_BASELINE)
    assert not result.passed
    assert any("totals_mae" in msg for msg in result.failures)


def test_check_metrics_worse_ou_hit_rate_fails():
    worse = {
        "goalie_mae": 3.5,
        "sog_mae": 1.2,
        "totals_mae": 0.8,
        "ou_hit_rate": 0.45,
    }
    result = check_metrics_against_baseline(worse, FIXTURE_BASELINE)
    assert not result.passed
    assert any("ou_hit_rate" in msg for msg in result.failures)


def test_ci_gate_fixture_metrics_within_tolerance():
    import json

    with FIXTURE_BASELINE.open(encoding="utf-8") as f:
        metrics = json.load(f)["metrics"]
    result = check_metrics_against_baseline(metrics, FIXTURE_BASELINE)
    assert result.passed, result.failures
