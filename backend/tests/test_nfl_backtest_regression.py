"""Offline regression gates for NFL quick backtest metrics (no network/DB)."""

from pathlib import Path

import pytest

from app.services.etl.nfl.backtest.metrics import (
    DEFAULT_NFL_BACKTEST_TOLERANCES,
    check_metrics_against_baseline,
    summarize_nfl_backtest_metrics,
)
from app.services.etl.nfl.backtest.runner import score_synthetic_rows
from app.services.etl.nfl.backtest.scorer import NFLBacktestScorer

FIXTURE_BASELINE = (
    Path(__file__).resolve().parent / "fixtures" / "nfl_backtest_quick_baseline.json"
)


def _synthetic_nested_metrics(
    *,
    qb_mae: float = 42.0,
    kicker_mae: float = 0.55,
    ou_hit_rate: float = 0.51,
) -> dict:
    return {
        "qb_metrics": {
            "n_qb": 20,
            "qb_mae": qb_mae,
            "qb_ou_hit_rate": 0.52,
            "qb_ou_n": 15,
        },
        "kicker_metrics": {
            "n_kicker": 15,
            "kicker_mae": kicker_mae,
            "kicker_ou_hit_rate": 0.5,
            "kicker_ou_n": 12,
        },
        "aggregate_ou": {"ou_hit_rate": ou_hit_rate, "ou_n": 25},
    }


def _build_scorer_from_synthetic_rows() -> NFLBacktestScorer:
    rows = [
        {"market": "qb", "predicted": 245.0, "actual": 260, "line": 250.5},
        {"market": "qb", "predicted": 210.0, "actual": 198, "line": 215.5},
        {"market": "kicker", "predicted": 1.8, "actual": 2},
        {"market": "kicker", "predicted": 1.1, "actual": 1},
    ]
    return score_synthetic_rows(rows)


def test_summarize_nfl_backtest_metrics_from_nested_dict():
    summary = summarize_nfl_backtest_metrics(_synthetic_nested_metrics())
    assert summary["qb_mae"] == pytest.approx(42.0)
    assert summary["kicker_mae"] == pytest.approx(0.55)
    assert summary["ou_hit_rate"] == pytest.approx(0.51)


def test_summarize_nfl_backtest_metrics_from_scorer():
    scorer = _build_scorer_from_synthetic_rows()
    summary = summarize_nfl_backtest_metrics(scorer)
    assert summary["n_qb"] == 2
    assert summary["n_kicker"] == 2
    assert "qb_mae" in summary


def test_scorer_qb_mae_and_ou():
    scorer = NFLBacktestScorer()
    scorer.add_qb_result(245.0, 260, ou_line=250.5)
    scorer.add_qb_result(210.0, 198, ou_line=215.5)
    qb = scorer.compute_qb_metrics()
    assert qb["qb_mae"] == pytest.approx(13.5)
    assert qb["qb_ou_hit_rate"] == pytest.approx(0.5)


def test_scorer_kicker_mae():
    scorer = NFLBacktestScorer()
    scorer.add_kicker_result(1.8, 2)
    scorer.add_kicker_result(1.1, 1)
    kicker = scorer.compute_kicker_metrics()
    assert kicker["kicker_mae"] == pytest.approx(0.15)


def test_check_metrics_same_as_baseline_passes():
    import json

    with FIXTURE_BASELINE.open(encoding="utf-8") as f:
        metrics = json.load(f)["metrics"]
    result = check_metrics_against_baseline(
        metrics, FIXTURE_BASELINE, DEFAULT_NFL_BACKTEST_TOLERANCES
    )
    assert result.passed
    assert result.failures == []


def test_check_metrics_worse_qb_mae_fails():
    worse = {
        "qb_mae": 55.0,
        "kicker_mae": 0.55,
        "ou_hit_rate": 0.51,
    }
    result = check_metrics_against_baseline(worse, FIXTURE_BASELINE)
    assert not result.passed
    assert any("qb_mae" in msg for msg in result.failures)


def test_check_metrics_worse_kicker_mae_fails():
    worse = {
        "qb_mae": 42.0,
        "kicker_mae": 1.0,
        "ou_hit_rate": 0.51,
    }
    result = check_metrics_against_baseline(worse, FIXTURE_BASELINE)
    assert not result.passed
    assert any("kicker_mae" in msg for msg in result.failures)


def test_check_metrics_worse_ou_hit_rate_fails():
    worse = {
        "qb_mae": 42.0,
        "kicker_mae": 0.55,
        "ou_hit_rate": 0.44,
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
