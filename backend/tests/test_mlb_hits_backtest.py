"""Unit tests for MLB hits heuristic + shadow ML backtest helpers (no network)."""

import pytest

from app.services.etl.mlb.hits import (
    combined_score_heuristic,
    lineup_heuristic_score_aggregate,
    project_lineup_hits_heuristic,
)
from app.services.etl.mlb.hits_classifier import (
    build_lineup_hit_features,
    predict_p_one_plus_hit,
)
from app.services.etl.mlb.backtest.model_runner import BacktestModelRunner
from app.services.etl.mlb.backtest.scorer import BacktestScorer


def test_combined_score_heuristic_gates_fail_returns_zero():
    assert (
        combined_score_heuristic(
            hits_in_last_10_games=3,
            season_avg_vs_handed=0.300,
            batting_average_vs_pitcher=0.310,
            at_bats_vs_pitcher=20,
            home_runs_last_10_games=2,
            batting_order_position=100,
        )
        == 0.0
    )


def test_combined_score_heuristic_passing_gates_positive():
    score = combined_score_heuristic(
        hits_in_last_10_games=8,
        season_avg_vs_handed=0.290,
        batting_average_vs_pitcher=0.300,
        at_bats_vs_pitcher=15,
        home_runs_last_10_games=3,
        batting_order_position=100,
    )
    assert score >= 2.0


def test_combined_score_heuristic_matches_production_weights():
    score_top = combined_score_heuristic(
        9,
        0.300,
        0.320,
        18,
        4,
        100,
    )
    score_bottom = combined_score_heuristic(
        9,
        0.300,
        0.320,
        18,
        4,
        900,
    )
    assert score_top > score_bottom


def test_lineup_aggregate_sums_batter_scores():
    pitcher_stats = {"away_pitcher_stats": {"whip": 1.2, "k9": 9.0}}
    lineup_data = {
        "home_batters": [
            {
                "hits_last_10_games": 8,
                "season_avg_vs_handed": 0.290,
                "batting_average_vs_pitcher": 0.300,
                "at_bats_vs_pitcher": 12,
                "home_runs_last_10_games": 2,
                "batting_order_position": 100,
            },
            {
                "hits_last_10_games": 7,
                "season_avg_vs_handed": 0.280,
                "batting_average_vs_pitcher": 0.295,
                "at_bats_vs_pitcher": 10,
                "home_runs_last_10_games": 1,
                "batting_order_position": 200,
            },
        ],
    }
    agg = lineup_heuristic_score_aggregate(
        pitcher_stats, lineup_data, "home", features={}
    )
    assert agg == pytest.approx(
        combined_score_heuristic(8, 0.290, 0.300, 12, 2, 100)
        + combined_score_heuristic(7, 0.280, 0.295, 10, 1, 200),
        rel=1e-6,
    )


def test_project_lineup_hits_in_reasonable_range():
    pitcher_stats = {
        "away_pitcher_stats": {"whip": 1.25, "k9": 8.5},
        "home_pitcher_stats": {"whip": 1.40, "k9": 7.5},
    }
    features = {"home_lineup_ops": 0.78, "away_lineup_ops": 0.74, "park_factor": 1.05}
    home_h = project_lineup_hits_heuristic(pitcher_stats, {}, "home", features=features)
    away_h = project_lineup_hits_heuristic(pitcher_stats, {}, "away", features=features)
    assert 3.0 <= home_h <= 16.0
    assert 3.0 <= away_h <= 16.0


def test_predict_p_one_plus_hit_monotonic_ba():
    low = predict_p_one_plus_hit(
        {
            "rolling_ba": 0.220,
            "pitcher_whip": 1.35,
            "pitcher_k9": 8.0,
            "park_factor": 1.0,
            "is_home": 0.0,
        }
    )
    high = predict_p_one_plus_hit(
        {
            "rolling_ba": 0.320,
            "pitcher_whip": 1.35,
            "pitcher_k9": 8.0,
            "park_factor": 1.0,
            "is_home": 0.0,
        }
    )
    assert 0.0 < low < high < 1.0


def test_build_lineup_hit_features_from_ops():
    feat = build_lineup_hit_features(
        "home",
        {},
        {"away_pitcher_stats": {"whip": 1.1, "k9": 10.0}},
        {"home_lineup_ops": 0.81, "park_factor": 1.1},
    )
    assert feat["rolling_ba"] == pytest.approx(0.81)
    assert feat["pitcher_whip"] == pytest.approx(1.1)
    assert feat["is_home"] == 1.0


def test_model_runner_predict_hits_returns_heuristic_and_ml():
    runner = BacktestModelRunner(models_to_test={"hits"})
    game = type("G", (), {"game_id": 1})()
    out = runner.predict_hits(
        game,
        {},
        {
            "home_pitcher_stats": {"whip": 1.3, "k9": 8.0},
            "away_pitcher_stats": {"whip": 1.4, "k9": 7.5},
        },
        features={
            "home_lineup_ops": 0.76,
            "away_lineup_ops": 0.72,
            "park_factor": 1.0,
        },
    )
    assert "home_heuristic" in out
    assert "home_ml_prob" in out
    assert "home_projected_hits" in out
    assert 0.0 < out["home_ml_prob"] < 1.0


def test_scorer_hit_metrics_methods():
    scorer = BacktestScorer()
    scorer.add_hit_result(
        "home",
        8.0,
        9,
        heuristic=5.5,
        ml_prob=0.62,
    )
    scorer.add_hit_result(
        "away",
        7.0,
        4,
        heuristic=4.0,
        ml_prob=0.40,
    )
    metrics = scorer.compute_hit_metrics()
    assert metrics["heuristic_mae"] == pytest.approx(2.0, abs=0.01)
    assert metrics["ml_board_accuracy"] == pytest.approx(0.5, abs=0.01)
    assert "heuristic" in metrics["methods"]
    assert "ml_board" in metrics["methods"]
