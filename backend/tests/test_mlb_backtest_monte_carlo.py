"""Backtest scorer integration for Monte Carlo game layer."""

from app.services.etl.mlb.backtest.scorer import BacktestScorer


def test_scorer_monte_carlo_metrics():
    scorer = BacktestScorer()
    prediction = {
        "predicted_home_wp": 0.58,
        "predicted_total": 9.0,
        "predicted_run_line": 0.5,
        "mc_home_wp": 0.54,
        "mc_total": 8.7,
        "mc_sim": {"home_lambda": 4.8, "away_lambda": 4.1, "dispersion": 1.35},
    }
    actuals = {
        "actual_winner": "home",
        "actual_total": 10,
        "home_score": 6,
        "away_score": 4,
    }
    metadata = {"game_date": "2024-07-01", "market_total": 8.5}

    scorer.add_game_result(prediction, actuals, metadata)
    game_metrics = scorer.compute_game_metrics()

    mc = game_metrics.get("monte_carlo")
    assert mc is not None
    assert mc["n_games"] == 1
    assert mc["brier_score"] is not None
    assert mc.get("ou_accuracy_market") is not None
    assert mc["ou_market_total"] == 1
