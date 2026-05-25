"""Offline regression gates for MLB quick backtest metrics (no network)."""

from pathlib import Path

import pytest

from app.services.etl.mlb.backtest.metrics import (
    DEFAULT_BACKTEST_TOLERANCES,
    check_metrics_against_baseline,
    summarize_backtest_metrics,
)
from app.services.etl.mlb.backtest.scorer import BacktestScorer

FIXTURE_BASELINE = (
    Path(__file__).resolve().parent / "fixtures" / "mlb_backtest_quick_baseline.json"
)


def _synthetic_game_metrics(
    *,
    brier: float = 0.22,
    ml_accuracy: float = 0.6,
    n_games: int = 10,
) -> dict:
    return {
        "game_metrics": {
            "n_games": n_games,
            "brier_score": brier,
            "ml_accuracy": ml_accuracy,
        },
        "hit_metrics": {"hit_mae": 1.0, "n_predictions": n_games * 2},
    }


def _add_minimal_game(scorer: BacktestScorer, home_wp: float, home_won: bool) -> None:
    prediction = {
        "predicted_home_wp": home_wp,
        "predicted_total": 8.0,
        "predicted_run_line": 0.5 if home_wp > 0.5 else -0.5,
    }
    actuals = {
        "actual_winner": "home" if home_won else "away",
        "actual_total": 8,
        "home_score": 5 if home_won else 2,
        "away_score": 2 if home_won else 5,
    }
    scorer.add_game_result(prediction, actuals, {"game_date": "2024-06-01"})


def test_summarize_backtest_metrics_from_nested_dict():
    summary = summarize_backtest_metrics(_synthetic_game_metrics())
    assert summary["n_games"] == 10
    assert summary["mean_brier"] == pytest.approx(0.22)
    assert summary["moneyline_accuracy"] == pytest.approx(0.6)
    assert summary["hit_mae"] == pytest.approx(1.0)


def test_summarize_backtest_metrics_from_scorer():
    scorer = BacktestScorer()
    _add_minimal_game(scorer, 0.7, True)
    _add_minimal_game(scorer, 0.3, False)
    scorer.add_hit_result("home", 4.0, 4)
    summary = summarize_backtest_metrics(scorer)
    assert summary["n_games"] == 2
    assert "mean_brier" in summary
    assert "moneyline_accuracy" in summary
    assert summary["hit_mae"] == pytest.approx(0.0)


def test_check_metrics_same_as_baseline_passes():
    baseline_metrics = {
        "mean_brier": 0.24,
        "moneyline_accuracy": 0.55,
        "hit_mae": 1.25,
        "n_games": 20,
    }
    result = check_metrics_against_baseline(
        baseline_metrics, FIXTURE_BASELINE, DEFAULT_BACKTEST_TOLERANCES
    )
    assert result.passed
    assert result.failures == []


def test_check_metrics_better_than_baseline_passes():
    better = {
        "mean_brier": 0.20,
        "moneyline_accuracy": 0.62,
        "hit_mae": 0.9,
        "n_games": 20,
    }
    result = check_metrics_against_baseline(better, FIXTURE_BASELINE)
    assert result.passed


def test_check_metrics_worse_brier_fails():
    worse = {
        "mean_brier": 0.30,
        "moneyline_accuracy": 0.55,
        "hit_mae": 1.25,
        "n_games": 20,
    }
    result = check_metrics_against_baseline(worse, FIXTURE_BASELINE)
    assert not result.passed
    assert any("mean_brier" in msg for msg in result.failures)


def test_check_metrics_worse_ml_accuracy_fails():
    worse = {
        "mean_brier": 0.24,
        "moneyline_accuracy": 0.48,
        "hit_mae": 1.25,
        "n_games": 20,
    }
    result = check_metrics_against_baseline(worse, FIXTURE_BASELINE)
    assert not result.passed
    assert any("moneyline_accuracy" in msg for msg in result.failures)


def test_check_metrics_worse_hit_mae_fails():
    worse = {
        "mean_brier": 0.24,
        "moneyline_accuracy": 0.55,
        "hit_mae": 2.0,
        "n_games": 20,
    }
    result = check_metrics_against_baseline(worse, FIXTURE_BASELINE)
    assert not result.passed
    assert any("hit_mae" in msg for msg in result.failures)


def test_ci_gate_fixture_metrics_within_tolerance():
    """Committed baseline is the reference; identical metrics must pass CI."""
    import json

    with FIXTURE_BASELINE.open(encoding="utf-8") as f:
        payload = json.load(f)
    metrics = payload["metrics"]
    result = check_metrics_against_baseline(metrics, FIXTURE_BASELINE)
    assert result.passed, result.failures
